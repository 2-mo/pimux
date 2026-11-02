# pimux-managed: standalone GPU dashboard adapted from RIPO's pi gpu (Apache-2.0).
# Modified for standalone installation, PiMux language selection and mouse navigation.
# See LICENSE.
"""Read-only GPU telemetry and compact cards for the PiMux popup."""

import argparse
import csv
from collections import deque
from dataclasses import dataclass
import io
import math
from pathlib import Path
import shlex
import subprocess
import sys
import time

from rich.console import Group
from rich.table import Column, Table
from rich.text import Text

from gpu_ui import MUTED_STYLE, SELECTED_STYLE, TITLE_STYLE, console, key_hints, status_text, run_screen, screen, tr

_FIELDS = "index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit"


class GPUReadError(RuntimeError):
    """The telemetry command could not provide a valid snapshot."""


@dataclass(frozen=True)
class GPU:
    index: int
    name: str
    utilization: float | None
    memory_used: float | None
    memory_total: float | None
    temperature: float | None
    power_draw: float | None
    power_limit: float | None

    @property
    def memory_percent(self):
        if self.memory_used is None or not self.memory_total:
            return None
        return 100 * self.memory_used / self.memory_total


def _number(value):
    value = value.strip()
    if value in {"N/A", "[N/A]", "[Not Supported]", "Not Supported", ""}:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite telemetry")
    return number


def parse_gpus(output):
    """Parse nvidia-smi CSV with nounits; unsupported measurements stay unknown."""
    rows = []
    try:
        for fields in csv.reader(io.StringIO(output), skipinitialspace=True):
            if not fields or all(not field.strip() for field in fields):
                continue
            if len(fields) != 8:
                raise ValueError("expected eight fields")
            index, name, *metrics = fields
            rows.append(GPU(int(index), name.strip(), *(_number(value) for value in metrics)))
    except (ValueError, csv.Error) as exc:
        raise GPUReadError(tr("Could not parse GPU telemetry", "显卡数据无法解析")) from exc
    return rows


def query_gpus():
    """Take one bounded snapshot without creating processes or state beyond the query."""
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={_FIELDS}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except FileNotFoundError as exc:
        raise GPUReadError(tr("NVIDIA driver tool nvidia-smi was not found", "未找到 NVIDIA 驱动工具 nvidia-smi")) from exc
    except subprocess.TimeoutExpired as exc:
        raise GPUReadError(tr("GPU query timed out (3 seconds)", "显卡读取超时（3 秒）")) from exc
    except OSError as exc:
        raise GPUReadError(tr("Could not query the NVIDIA driver: ", "无法查询 NVIDIA 驱动：") + str(exc)) from exc
    message = (result.stderr or result.stdout).strip()
    if message.strip(".").lower() == "no devices were found":
        return []
    if result.returncode:
        detail = " ".join(message.split())[:300] or f"exit {result.returncode}"
        raise GPUReadError(tr("GPU query failed: ", "显卡读取失败：") + detail)
    return parse_gpus(result.stdout)


@dataclass(frozen=True)
class GPUProcess:
    pid: int
    name: str
    memory_used: float | None
    command: str | None = None
    cwd: str | None = None


def _process_details(pid):
    """Read visible Linux process details; processes may exit between snapshots."""
    directory = Path(f"/proc/{pid}")
    try:
        argv = (directory / "cmdline").read_bytes().removesuffix(b"\0").split(b"\0")
        command = shlex.join(part.decode(errors="replace") for part in argv) if any(argv) else None
    except OSError:
        command = None
    try:
        cwd = str((directory / "cwd").readlink())
    except OSError:
        cwd = None
    return command, cwd


def query_processes(index):
    """Read compute processes and available command paths for the selected GPU."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "-i", str(index),
             "--query-compute-apps=pid,process_name,used_gpu_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GPUReadError(tr("Process query failed or timed out", "进程读取失败或超时")) from exc
    if result.returncode:
        raise GPUReadError(tr("Process query failed", "进程读取失败"))
    try:
        rows = [
            (int(pid), name.strip(), _number(memory))
            for pid, name, memory in csv.reader(io.StringIO(result.stdout), skipinitialspace=True)
        ]
    except (ValueError, csv.Error) as exc:
        raise GPUReadError(tr("Could not parse process data", "进程数据无法解析")) from exc
    return [GPUProcess(pid, name, memory, *_process_details(pid)) for pid, name, memory in rows]


def _field(value, width, precision):
    return f"{'N/A':>{width}}" if value is None else f"{value:{width}.{precision}f}"


def _percent(value):
    return f"{'N/A':>6}" if value is None else f"{value:5.1f}%"


def _utilization(value):
    label = status_text(("● " if value not in (None, 0) else "○ ") + _percent(value),
                        tone="muted" if value in (None, 0) else "success")
    if value not in (None, 0):
        label.stylize("bold")
    return label


def _memory(gpu):
    percent = gpu.memory_percent
    return status_text(_percent(percent),
                       tone="warning" if percent is not None and percent >= 90 else
                       "muted" if percent is None else "info")


def _capacity(gpu):
    return "/".join(_field(None if value is None else value / 1024, 6, 1)
                    for value in (gpu.memory_used, gpu.memory_total)) + " GiB"


def _thermals(gpu):
    line = status_text(_field(gpu.temperature, 3, 0) + "°C",
                       tone="warning" if gpu.temperature is not None and gpu.temperature >= 80 else "muted")
    line.append(f" {_field(gpu.power_draw, 6, 1)}/{_field(gpu.power_limit, 4, 0)}W", style=MUTED_STYLE)
    line.no_wrap = True
    line.overflow = "ellipsis"
    return line


def _trend(samples, width):
    """Draw a one-row Braille curve, one sample per cell on a fixed 0–100 scale."""
    samples = list(samples)[-width:]
    samples = [None] * (width - len(samples)) + samples
    cells = [0] * width
    dots = ((1, 2, 4, 64), (8, 16, 32, 128))
    previous = None
    for column, value in enumerate(samples):
        if value is None:
            previous = None
            continue
        x = column * 2 + 1
        y = round((100 - max(0, min(100, value))) * 3 / 100)
        start_x, start_y = previous if previous is not None else (x - 1, y)
        steps = max(x - start_x, abs(y - start_y))
        for step in range(steps + 1):
            px = round(start_x + (x - start_x) * step / steps)
            py = round(start_y + (y - start_y) * step / steps)
            cells[px // 2] |= dots[px % 2][py]
        previous = (x, y)
    line = Text()
    for cell, value in zip(cells, samples):
        line.append(chr(0x2800 + cell) if cell else " ",
                    style=MUTED_STYLE if value in (None, 0) else "green")
    return line


class Monitor:
    """Cache snapshots and at most 30 recent samples per GPU, only in memory."""

    def __init__(self, compact=False):
        self.compact = compact
        self.gpus = []
        self.error = None
        self.selected = 0
        self.columns = 1
        self.page_size = 1
        self.details = False
        self.detail_offset = 0
        self.detail_page_size = 1
        self.detail_total = 0
        self.process_gpu = None
        self.processes = []
        self.process_error = None
        self.history = {}
        self.last_sample = None
        self.page_start = 0
        self.tile_width = 15
        self.tile_height = 3

    def refresh(self):
        selected_id = self.gpus[self.selected].index if self.gpus else None
        try:
            self.gpus = query_gpus()
            self.error = None
        except GPUReadError as exc:
            self.gpus = []
            self.error = str(exc)
        now = time.monotonic()
        if self.last_sample is not None and now - self.last_sample > 3:
            self.history.clear()
        present = {gpu.index for gpu in self.gpus}
        self.history = {index: samples for index, samples in self.history.items() if index in present}
        for gpu in self.gpus:
            self.history.setdefault(gpu.index, deque(maxlen=30)).append(gpu.utilization)
        self.last_sample = now if self.gpus else None
        self.selected = next((i for i, gpu in enumerate(self.gpus) if gpu.index == selected_id),
                             min(self.selected, max(0, len(self.gpus) - 1)))
        if not self.gpus or self.gpus[self.selected].index != selected_id:
            self.detail_offset = 0
        self.process_gpu = None
        self.processes = []
        self.process_error = None
        if self.details and self.gpus:
            self.process_gpu = self.gpus[self.selected].index
            try:
                self.processes = query_processes(self.process_gpu)
            except GPUReadError as exc:
                self.process_error = str(exc)

    def on_key(self, key):
        name = getattr(key, "name", None)
        if name == "MOUSE_LEFT":
            x, y = key.mouse_xy
            row, line = divmod(y - 1, 4)
            column, cell = divmod(x, self.tile_width + 1)
            index = self.page_start + row * self.columns + column
            if (y >= 1 and x >= 0 and line < self.tile_height and cell < self.tile_width
                    and column < self.columns
                    and self.page_start <= index < min(len(self.gpus), self.page_start + self.page_size)):
                if self.selected != index:
                    self.detail_offset = 0
                self.selected = index
            return False
        if self.details:
            scroll = {"MOUSE_SCROLL_UP": -3, "MOUSE_SCROLL_DOWN": 3,
                      "KEY_PGUP": -self.detail_page_size, "KEY_PGDOWN": self.detail_page_size,
                      "KEY_HOME": -self.detail_total, "KEY_END": self.detail_total}
            step = scroll.get(name or key) if isinstance(name or key, str) else None
            if step is not None:
                self.detail_offset = max(0, min(self.detail_offset + step,
                                               self.detail_total - self.detail_page_size))
                return False
        if name in {"MOUSE_SCROLL_UP", "MOUSE_SCROLL_DOWN"}:
            key = "KEY_UP" if name == "MOUSE_SCROLL_UP" else "KEY_DOWN"
        if key in {"q", "KEY_ESCAPE"}:
            return True
        if key == "d":
            self.details = not self.details
            self.detail_offset = 0
        steps = {"KEY_UP": -self.columns, "KEY_DOWN": self.columns,
                 "KEY_LEFT": -1, "KEY_RIGHT": 1,
                 "KEY_PGUP": -self.page_size, "KEY_PGDOWN": self.page_size}
        if key in steps:
            self.detail_offset = 0
            self.selected = min(max(0, self.selected + steps[key]), max(0, len(self.gpus) - 1))
        return False

    def _layout(self, width):
        columns = 1 if self.compact else min(4, max(1, (width + 1) // 16))
        tile_width = min(15, max(1, width))
        return columns, tile_width

    def full_height(self, width):
        """Height needed to print every GPU in a single snapshot."""
        columns, _ = self._layout(width)
        rows = max(1, math.ceil(len(self.gpus) / columns))
        return rows * 4 + 1 + len(self._detail_lines(width))

    def _detail_lines(self, width=None):
        if not self.details or not self.gpus:
            return []
        gpu = self.gpus[self.selected]
        lines = [
            Text(f"GPU {gpu.index} · {gpu.name}", style=MUTED_STYLE),
            Text(_capacity(gpu), style=MUTED_STYLE),
            _thermals(gpu),
        ]
        if self.process_gpu != gpu.index:
            lines.append(Text(tr("Compute processes · loading", "计算进程 · 读取中"), style=MUTED_STYLE))
        elif self.process_error:
            lines.append(status_text(self.process_error, tone="error"))
        elif not self.processes:
            lines.append(Text(tr("Compute processes · none", "计算进程 · 无"), style=MUTED_STYLE))
        else:
            lines.append(Text(f"{'PID':>7} {'GiB':>5} " + tr("Process", "进程"), style=MUTED_STYLE))
            for process in self.processes:
                memory = None if process.memory_used is None else process.memory_used / 1024
                lines.append(Text(f"{process.pid:7d} {_field(memory, 5, 1)} {process.name}",
                                  style=MUTED_STYLE))
                if process.command and process.command != process.name:
                    lines.append(Text(tr("  Command: ", "  命令：") + process.command, style=MUTED_STYLE))
                lines.append(Text(tr("  Cwd: ", "  目录：") + (process.cwd or tr("unavailable", "不可见")),
                                  style=MUTED_STYLE))
        if width is None:
            return lines
        return [part for line in lines for part in line.wrap(console, max(1, width),
                                                             overflow="fold", no_wrap=False)]

    def _tile(self, gpu, selected, width, height=3):
        title = Text(f"{'›' if selected else ' '}GPU{gpu.index:2d} ")
        title.append_text(_utilization(gpu.utilization))
        trend = _trend(self.history.get(gpu.index, ()), width)
        percent = gpu.memory_percent
        label = _memory(gpu)
        bar_width = max(1, width - 9)
        filled = 0 if percent is None else round(bar_width * max(0, min(100, percent)) / 100)
        memory = Text("M ", style=MUTED_STYLE)
        memory.append("━" * filled, style=label.style)
        memory.append("·" * (bar_width - filled), style=MUTED_STYLE)
        memory.append(" ")
        memory.append_text(label)
        lines = [title, trend, memory]
        for line in lines:
            line.truncate(width, overflow="ellipsis")
            line.pad_right(width - line.cell_len)
            line.no_wrap = True
            if selected:
                line.stylize(SELECTED_STYLE)
        return Group(*lines[:height])

    def render(self, width, height):
        width = max(1, width)
        self.columns, tile_width = self._layout(width)
        detail_lines = self._detail_lines(width)
        # Keep a card, footer, and overflow indicators visible before adding details.
        detail_budget = max(0, height - 5 - (len(self.gpus) > self.columns))
        if detail_lines and height >= 5:
            detail_budget = max(1, detail_budget)
        self.detail_total = len(detail_lines)
        self.detail_page_size = max(1, detail_budget)
        self.detail_offset = max(0, min(self.detail_offset, self.detail_total - self.detail_page_size))
        detail_lines = detail_lines[self.detail_offset:self.detail_offset + detail_budget]
        detail_height = len(detail_lines)
        rows = max(1, (height - 1 - detail_height) // 4)
        if len(self.gpus) > rows * self.columns:
            rows = max(1, (height - 2 - detail_height) // 4)
        self.page_size = rows * self.columns
        start = self.selected // self.page_size * self.page_size
        visible = self.gpus[start:start + self.page_size]
        more_below = start + len(visible) < len(self.gpus)
        tile_height = min(3, max(1, height - 2 - detail_height - more_below))
        self.page_start, self.tile_width, self.tile_height = start, tile_width, tile_height
        heading = Text("PiMux · GPU", style=TITLE_STYLE, no_wrap=True, overflow="ellipsis")
        if len(visible) < len(self.gpus):
            heading.append(f"  {start + 1}–{start + len(visible)}/{len(self.gpus)}", style=MUTED_STYLE)
        if self.details and self.detail_total > detail_budget:
            heading.append(" · " + tr("details", "详情") +
                           f" {self.detail_offset + 1}–{self.detail_offset + len(detail_lines)}/{self.detail_total}",
                           style=MUTED_STYLE)
        content = []
        if self.error:
            content.append(Text(self.error, style="red", no_wrap=True, overflow="ellipsis"))
        elif not self.gpus:
            content.append(Text(tr("No GPUs found", "未发现 GPU"), style=MUTED_STYLE, no_wrap=True, overflow="ellipsis"))
        else:
            grid = Table.grid(*(Column(width=tile_width) for _ in range(self.columns)), padding=(0, 1))
            for offset in range(0, len(visible), self.columns):
                if offset:
                    grid.add_row(*(Text("") for _ in range(self.columns)))
                grid.add_row(*(self._tile(card, start + offset + col == self.selected,
                                         tile_width, tile_height)
                               for col, card in enumerate(visible[offset:offset + self.columns])))
            content.append(grid)
            if more_below:
                content.append(Text("…", style=MUTED_STYLE))
        content.extend(detail_lines)
        hint_width = tile_width if self.compact else width
        hints = [("d", tr("less", "收起") if self.details else tr("details", "详情")),
                 ("q", tr("back", "返回"))]
        footer = key_hints(hints)
        navigation = ([("PgUp/Dn", tr("scroll", "滚动") if self.details else "")]
                      if self.details or len(visible) < len(self.gpus) else []) + [("↑↓←→", "")]
        for hint in navigation:
            candidate = key_hints([hint, *hints])
            if candidate.cell_len <= hint_width:
                hints.insert(0, hint)
                footer = candidate
        footer.no_wrap = True
        footer.overflow = "ellipsis"
        return screen(Group(heading, *content), footer, width, height)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pimux gpu", description=tr("Read-only GPU monitor (refreshes every second)", "只读 GPU 监控（每秒刷新）"),
        epilog=tr("Arrows select, d toggles details, wheel/PgUp/PgDn scroll details, r refreshes, q/Esc returns.",
                  "方向键选卡，d 展开详情，滚轮/PgUp/PgDn 滚动详情，r 刷新，q/Esc 返回。"),
    )
    parser.add_argument("--once", action="store_true", help=tr("Print one snapshot", "输出一次后退出"))
    parser.add_argument("--compact", action="store_true", help=tr("Use a single column", "使用单列 GPU 小块"))
    args = parser.parse_args(argv)
    monitor = Monitor(compact=args.compact)
    if args.once or not console.is_terminal or not sys.stdin.isatty():
        monitor.refresh()
        console.print(monitor.render(console.width, monitor.full_height(console.width)))
        return 1 if monitor.error else 0
    return run_screen(monitor.render, monitor.on_key, monitor.refresh, interval=1)


if __name__ == "__main__":
    raise SystemExit(main())
