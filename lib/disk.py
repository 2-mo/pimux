# pimux-managed: read-only filesystem capacity and on-demand directory usage.
"""Show mounted filesystems without letting one stalled network mount block the view.

Capacity is read per mount in a short-lived child process with a deadline, so a
hung NFS or FUSE server leaves only its own row unavailable. Directory sizes
come from du, run only on request and cancellable; nothing is ever written.
"""

import argparse
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from rich.console import Group
from rich.table import Column, Table
from rich.text import Text

from gpu_ui import MUTED_STYLE, TITLE_STYLE, SELECTED_STYLE, console, key_hints, run_screen, screen, tr
from inspect_ui import text

WARNING = 90
# Kernel and container views that report no user storage of their own.
PSEUDO = {"proc", "sysfs", "devtmpfs", "devpts", "devfs", "tmpfs", "ramfs", "cgroup", "cgroup2",
          "securityfs", "pstore", "bpf", "tracefs", "debugfs", "configfs", "fusectl", "mqueue",
          "hugetlbfs", "autofs", "binfmt_misc", "efivarfs", "nsfs", "rpc_pipefs", "selinuxfs",
          "squashfs", "fuse.lxcfs", "fuse.portal", "fuse.gvfsd-fuse", "fuse.snapfuse", "nullfs"}
# Boot partitions and per-container or per-package mounts are noise by default.
HIDDEN = ("/boot", "/efi", "/snap", "/var/snap", "/run", "/var/lib/docker", "/var/lib/containers",
          "/var/lib/kubelet", "/System/Volumes", "/private/var/vm")
STATVFS = ("import os, sys\ns = os.statvfs(sys.argv[1])\n"
           "print(s.f_frsize or s.f_bsize, s.f_blocks, s.f_bfree, s.f_bavail, s.f_files, s.f_ffree)")


@dataclass(frozen=True)
class Mount:
    path: str
    device: str
    kind: str
    hidden: bool = False


@dataclass(frozen=True)
class Usage:
    total: int
    used: int
    free: int
    inodes: int
    inodes_used: int

    @property
    def percent(self):
        # Match df: reserved blocks count as neither used nor available.
        return 100 * self.used / (self.used + self.free) if self.used + self.free else 0

    @property
    def inode_percent(self):
        return 100 * self.inodes_used / self.inodes if self.inodes else None


def _unescape(value):
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)


def hidden(path):
    return any(path == prefix or path.startswith(prefix + "/") for prefix in HIDDEN)


def parse_mountinfo(content):
    """Keep one whole-filesystem mount per device; bind mounts of subdirectories repeat it."""
    by_path = {}
    for line in content.splitlines():
        left, separator, right = line.partition(" - ")
        fields, tail = left.split(), right.split()
        if not separator or len(fields) < 5 or len(tail) < 2:
            continue
        device_id, root, path = fields[2], _unescape(fields[3]), _unescape(fields[4])
        # A later mount on the same path hides the earlier one.
        by_path[path] = (device_id, root, Mount(path, _unescape(tail[1]), tail[0], hidden(path)))
    chosen = {}
    for device_id, root, mount in by_path.values():
        if mount.kind in PSEUDO:
            continue
        rank = (root != "/", mount.hidden, len(mount.path))
        if device_id not in chosen or rank < chosen[device_id][0]:
            chosen[device_id] = (rank, mount)
    return sorted((mount for _, mount in chosen.values()), key=lambda mount: mount.path)


def parse_macos_mounts(output):
    mounts = []
    for line in output.splitlines():
        match = re.fullmatch(r"(.+) on (.+) \(([^,)]+)(?:, ([^)]*))?\)", line)
        if not match or match[3] in PSEUDO:
            continue
        options = (match[4] or "").split(", ")
        mounts.append(Mount(match[2], match[1], match[3], hidden(match[2]) or "nobrowse" in options))
    return sorted(mounts, key=lambda mount: mount.path)


def list_mounts():
    if sys.platform == "darwin":
        try:
            output = subprocess.run(["/sbin/mount"], capture_output=True, text=True, errors="replace",
                                    timeout=3, env={"LC_ALL": "C"}).stdout
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError(tr("Could not list mounted filesystems.", "无法读取已挂载的文件系统。")) from None
        return parse_macos_mounts(output)
    try:
        return parse_mountinfo(Path("/proc/self/mountinfo").read_text(errors="replace"))
    except OSError:
        raise RuntimeError(tr("Could not list mounted filesystems.", "无法读取已挂载的文件系统。")) from None


def parse_statvfs(output):
    size, blocks, free, available, inodes, inodes_free = (int(value) for value in output.split())
    return Usage(blocks * size, (blocks - free) * size, available * size, inodes, inodes - inodes_free)


def read_usage(mounts, timeout=2):
    """Return Usage, or None for a mount that failed or missed the shared deadline."""
    children = {}
    for mount in mounts:
        try:
            children[mount.path] = subprocess.Popen(
                [sys.executable, "-I", "-S", "-c", STATVFS, mount.path],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError:
            children[mount.path] = None
    deadline = time.monotonic() + timeout
    usage = {}
    for path, child in children.items():
        if child is None:
            usage[path] = None
            continue
        try:
            output, _ = child.communicate(timeout=max(0.01, deadline - time.monotonic()))
            usage[path] = parse_statvfs(output) if child.returncode == 0 else None
        except subprocess.TimeoutExpired:
            # A child blocked in the kernel may outlive the kill; never wait for it.
            child.kill()
            usage[path] = None
        except ValueError:
            usage[path] = None
    return usage


def size_label(value):
    """Round up like df -h, so a nearly full disk never looks emptier than it is."""
    for index, unit in enumerate("BKMGTP"):
        scaled = value / 1024 ** index
        if index and scaled < 10:
            scaled = math.ceil(scaled * 10) / 10
            if scaled < 10:
                return f"{scaled:.1f}{unit}"
        if math.ceil(scaled) < 1024 or unit == "P":
            return f"{math.ceil(scaled)}{unit}"


def percent_label(value):
    return "—" if value is None else f"{math.ceil(round(value, 6))}%"


def tone(*percents):
    return "#e5a35b" if any(value is not None and value >= WARNING for value in percents) else "#63c5f8"


def bar(percent, width, style):
    filled = round(width * max(0, min(100, percent)) / 100)
    line = Text("━" * filled, style=style)
    line.append("·" * (width - filled), style=MUTED_STYLE)
    return line


def containing(mounts, path):
    matches = [mount for mount in mounts if path == mount.path or path.startswith(mount.path.rstrip("/") + "/")]
    return max(matches, key=lambda mount: len(mount.path)) if matches else None


class Scan:
    """One cancellable du run; children appear as du finishes each of them."""

    def __init__(self, path):
        self.path = path
        self.children = []
        self.total = None
        self.errors = 0
        self.started = time.monotonic()
        self.elapsed = None
        self.failure = ""
        self.lock = threading.Lock()
        try:
            self.process = subprocess.Popen(["du", "-x", "-k", "-d", "1", "--", path], stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, env={**os.environ, "LC_ALL": "C"})
        except OSError:
            self.process = None
            self.failure = tr("du is unavailable.", "找不到 du。")
            self.elapsed = 0
            return
        threading.Thread(target=self._errors, daemon=True).start()
        threading.Thread(target=self._read, daemon=True).start()

    def _errors(self):
        for _ in self.process.stderr:
            with self.lock:
                self.errors += 1

    def _read(self):
        for raw in self.process.stdout:
            size, separator, path = raw.decode(errors="replace").rstrip("\n").partition("\t")
            if not separator or not size.isdigit():
                continue
            with self.lock:
                if os.path.normpath(path) == os.path.normpath(self.path):
                    self.total = int(size) * 1024
                else:
                    self.children.append((int(size) * 1024, path))
        code = self.process.wait()
        with self.lock:
            self.elapsed = time.monotonic() - self.started
            if code and self.total is None:
                self.failure = tr("Directory could not be read.", "目录无法读取。")

    @property
    def running(self):
        return self.elapsed is None

    def snapshot(self):
        with self.lock:
            return sorted(self.children, reverse=True), self.total, self.errors, self.failure

    def cancel(self):
        if self.process and self.running:
            self.process.kill()


class DiskView:
    def __init__(self, cwd, *, show_all=False):
        self.cwd = cwd
        self.show_all = show_all
        self.mounts, self.usage, self.error = [], {}, ""
        self.read_at = None
        self.selected = 0
        self.scan = None
        self.scans = {}
        self.chosen = 0
        self.offset = 0
        self.page_size = 1
        self.rows_top = 0

    def visible(self):
        return [mount for mount in self.mounts if self.show_all or not mount.hidden]

    def refresh(self, force=False):
        if not force and self.read_at is not None and time.monotonic() - self.read_at < 5:
            return
        try:
            mounts = list_mounts()
            self.usage = read_usage([mount for mount in mounts if self.show_all or not mount.hidden])
            # Zero-sized statistics identify remaining pseudo filesystems; unanswered mounts stay listed.
            self.mounts = [mount for mount in mounts
                           if self.usage.get(mount.path) is None or self.usage[mount.path].total > 0]
            self.error = ""
        except RuntimeError as error:
            self.mounts, self.usage, self.error = [], {}, str(error)
        self.read_at = time.monotonic()
        self.selected = min(self.selected, max(0, len(self.visible()) - 1))

    def open_scan(self, path):
        path = os.path.normpath(path)
        if self.scan and self.scan.running:
            self.scan.cancel()
        if path not in self.scans or self.scans[path].failure:
            self.scans[path] = Scan(path)
        self.scan, self.chosen, self.offset = self.scans[path], 0, 0

    def close(self):
        for scan in self.scans.values():
            scan.cancel()

    def on_key(self, key):
        name = getattr(key, "name", None) or key
        if not isinstance(name, str):
            return False
        if name in {"MOUSE_SCROLL_UP", "MOUSE_SCROLL_DOWN"}:
            name = "KEY_UP" if name == "MOUSE_SCROLL_UP" else "KEY_DOWN"
        if self.scan:
            return self._scan_key(name, key)
        mounts = self.visible()
        if name in {"q", "KEY_ESCAPE"}:
            return True
        if name == "MOUSE_LEFT":
            index = key.mouse_xy[1] - self.rows_top
            if 0 <= index < len(mounts):
                self.selected = index
            return False
        steps = {"KEY_UP": -1, "KEY_DOWN": 1, "k": -1, "j": 1}
        if name in steps:
            self.selected = max(0, min(len(mounts) - 1, self.selected + steps[name]))
        elif name == "a":
            self.show_all = not self.show_all
            self.refresh(force=True)
        elif name == "r":
            self.read_at = None
        elif name == "KEY_ENTER" and mounts:
            self.open_scan(mounts[self.selected].path)
        elif name == ".":
            self.open_scan(self.cwd)
        return False

    def _scan_key(self, name, key):
        children = self.scan.snapshot()[0]
        if name in {"q", "KEY_ESCAPE"}:
            self.scan.cancel()
            self.scan = None
            return False
        if name == "MOUSE_LEFT":
            index = self.offset + key.mouse_xy[1] - self.rows_top
            if 0 <= index - self.offset < self.page_size and index < len(children):
                self.chosen = index
            return False
        steps = {"KEY_UP": -1, "KEY_DOWN": 1, "k": -1, "j": 1,
                 "KEY_PGUP": -self.page_size, "KEY_PGDOWN": self.page_size}
        if name in steps:
            self.chosen = max(0, min(len(children) - 1, self.chosen + steps[name]))
        elif name in {"KEY_ENTER", "KEY_RIGHT"} and children and os.path.isdir(children[self.chosen][1]) \
                and not os.path.islink(children[self.chosen][1]):
            self.open_scan(children[self.chosen][1])
        elif name in {"KEY_BACKSPACE", "KEY_LEFT", "\x7f", "\x08"} and self.scan.path != "/":
            self.open_scan(os.path.dirname(self.scan.path))
        elif name == "r":
            self.scans.pop(self.scan.path, None)
            self.open_scan(self.scan.path)
        return False

    def render(self, width, height):
        if self.scan:
            return self._render_scan(width, height)
        mounts = self.visible()
        here = containing(mounts, self.cwd)
        heading = text("PiMux · " + tr("Disk", "磁盘"), TITLE_STYLE)
        heading.append(f"  {len(mounts)} " + tr("filesystems", "个文件系统") +
                       ("" if self.show_all else " · " + tr("a shows all", "a 显示全部")), style=MUTED_STYLE)
        heading.no_wrap, heading.overflow = True, "ellipsis"
        wide = width >= 72
        bar_width = max(4, min(24, width - 64)) if wide else 0
        columns = [Column(ratio=1, no_wrap=True, overflow="ellipsis"),
                   Column(width=6, justify="right"), Column(width=6, justify="right"),
                   Column(width=6, justify="right"), Column(width=5, justify="right")]
        if wide:
            columns[1:1] = [Column(width=10, no_wrap=True, overflow="ellipsis")]
            columns[-1:-1] = [Column(width=bar_width)]
            columns.append(Column(width=7, justify="right"))
        table = Table.grid(*columns, padding=(0, 1), expand=True)
        labels = [tr("Mount", "挂载点"), tr("Size", "总量"), tr("Used", "已用"), tr("Free", "可用"), tr("Use", "占用")]
        if wide:
            labels[1:1] = [tr("Type", "类型")]
            labels[-1:-1] = [""]
            labels.append(tr("Inodes", "inode"))
        table.add_row(*(text(label, MUTED_STYLE) for label in labels))
        for index, mount in enumerate(mounts):
            usage = self.usage.get(mount.path)
            name = text(("› " if index == self.selected else "  ") + mount.path,
                        "bold #63c5f8" if index == self.selected else "#d8dce4")
            if mount is here:
                name.append(" ●", style="#b7a1e8")
            if usage is None:
                name.append("  " + tr("no response", "无响应"), style="#e5a35b")
                cells = [name, *(text("—", MUTED_STYLE) for _ in range(4))]
                if wide:
                    cells[1:1] = [text(mount.kind.removeprefix("fuse."), MUTED_STYLE)]
                    cells[-1:-1] = [Text("")]
                    cells.append(text("—", MUTED_STYLE))
            else:
                style = tone(usage.percent, usage.inode_percent)
                cells = [name, text(size_label(usage.total)), text(size_label(usage.used)),
                         text(size_label(usage.free), style), text(percent_label(usage.percent), style)]
                if wide:
                    cells[1:1] = [text(mount.kind.removeprefix("fuse."), MUTED_STYLE)]
                    cells[-1:-1] = [bar(usage.percent, bar_width, style)]
                    cells.append(text(percent_label(usage.inode_percent), tone(usage.inode_percent)
                                      if usage.inode_percent is not None else MUTED_STYLE))
            table.add_row(*cells, style=SELECTED_STYLE if index == self.selected else "")
        self.rows_top = 3
        body = [heading, Text("")]
        if self.error:
            body.append(text(self.error, "red"))
        elif not mounts:
            body.append(text(tr("No filesystems found", "没有找到文件系统"), MUTED_STYLE))
        else:
            body.append(table)
            mount = mounts[self.selected]
            details = text(tr("Device: ", "设备：") + mount.device + " · " + mount.kind, MUTED_STYLE)
            body.extend([Text(""), details])
            if here:
                body.append(text("● " + tr("Current directory: ", "当前目录：") + self.cwd, MUTED_STYLE))
        hints = [("↑↓", tr("select", "选择")), ("Enter", tr("folder sizes", "目录占用")),
                 (".", tr("current dir", "当前目录")), ("a", tr("all", "全部")), ("q", tr("back", "返回"))]
        if width < 65:
            hints = [("↑↓", ""), ("Enter", tr("sizes", "占用")), ("q", tr("back", "返回"))]
        return screen(Group(*body), key_hints(hints), width, height)

    def _render_scan(self, width, height):
        children, total, errors, failure = self.scan.snapshot()
        heading = text("PiMux · " + tr("Folder sizes", "目录占用") + "  ", TITLE_STYLE)
        heading.append_text(text(self.scan.path, "#d8dce4"))
        heading.no_wrap, heading.overflow = True, "ellipsis"
        elapsed = self.scan.elapsed if not self.scan.running else time.monotonic() - self.scan.started
        if failure:
            status = text(failure, "red")
        elif self.scan.running:
            status = text(tr(f"Scanning · {len(children)} done · {elapsed:.0f}s · Esc stops",
                             f"统计中 · 已完成 {len(children)} 项 · {elapsed:.0f} 秒 · Esc 停止"), "#e5a35b")
        else:
            status = text(tr(f"Total {size_label(total or 0)} · {len(children)} entries · {elapsed:.1f}s",
                             f"合计 {size_label(total or 0)} · {len(children)} 项 · 用时 {elapsed:.1f} 秒"), MUTED_STYLE)
        if errors:
            status.append(tr(f" · {errors} unreadable", f" · {errors} 项无权限读取"), style="#e5a35b")
        self.rows_top = 3
        self.page_size = max(1, height - 5)
        self.chosen = min(self.chosen, max(0, len(children) - 1))
        if self.chosen < self.offset:
            self.offset = self.chosen
        elif self.chosen >= self.offset + self.page_size:
            self.offset = self.chosen - self.page_size + 1
        largest = children[0][0] if children else 0
        bar_width = max(4, min(30, width - 40))
        table = Table.grid(Column(width=7, justify="right"), Column(width=bar_width),
                           Column(ratio=1, no_wrap=True, overflow="ellipsis"), padding=(0, 1), expand=True)
        for index in range(self.offset, min(len(children), self.offset + self.page_size)):
            size, path = children[index]
            selected = index == self.chosen
            name = text(("› " if selected else "  ") + os.path.basename(path) +
                        ("/" if os.path.isdir(path) and not os.path.islink(path) else ""),
                        "bold #63c5f8" if selected else "#d8dce4")
            table.add_row(text(size_label(size)), bar(100 * size / largest if largest else 0, bar_width, "#63c5f8"),
                          name, style=SELECTED_STYLE if selected else "")
        hints = [("↑↓", tr("select", "选择")), ("Enter", tr("open", "进入")), ("⌫", tr("parent", "上一级")),
                 ("r", tr("rescan", "重新统计")), ("q", tr("disks", "返回磁盘"))]
        if width < 65:
            hints = [("↑↓", ""), ("Enter", ""), ("⌫", ""), ("q", tr("back", "返回"))]
        return screen(Group(heading, status, Text(""), table), key_hints(hints), width, height)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pimux disk", description=tr("Filesystem capacity and on-demand folder sizes",
                                          "查看磁盘容量，并按需统计目录占用"))
    parser.add_argument("path", nargs="?", help=tr("Open folder sizes for this directory",
                                                   "直接统计此目录下各项占用"))
    parser.add_argument("--all", action="store_true", help=tr("Include boot and system mounts",
                                                              "包含启动分区和系统挂载"))
    parser.add_argument("--once", action="store_true", help=tr("Print once and exit", "输出一次后退出"))
    args = parser.parse_args(argv)
    if args.path is not None and not os.path.isdir(args.path):
        parser.error(tr("Not a directory: ", "不是目录：") + args.path)
    view = DiskView(os.getcwd(), show_all=args.all)
    try:
        if args.path is not None:
            view.open_scan(os.path.abspath(args.path))
        if args.once or not console.is_terminal or not sys.stdin.isatty():
            view.refresh(force=True)
            while view.scan and view.scan.running:
                time.sleep(0.1)
            lines = len(view.scan.children) + 5 if view.scan else len(view.visible()) + 8
            console.print(view.render(console.width, lines))
            return 1 if view.error or (view.scan and view.scan.failure) else 0
        return run_screen(view.render, view.on_key, view.refresh, interval=1)
    finally:
        view.close()


if __name__ == "__main__":
    raise SystemExit(main())
