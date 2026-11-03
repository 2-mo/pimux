# pimux-managed: arrange an existing window without restarting its programs.
"""Client-local controls for tmux pane layouts, swaps and continuous resizing."""

import argparse
from dataclasses import dataclass
import subprocess

from rich.console import Group
from rich.text import Text

from gpu_ui import TITLE_STYLE, key_hints, run_screen, screen, tr
from inspect_ui import text


@dataclass(frozen=True)
class Pane:
    identity: str
    index: str
    program: str
    width: int
    height: int


class Layout:
    def __init__(self, binary, socket, pane):
        self.binary, self.socket, self.pane = binary, socket, pane
        self.window = self.title = ""
        self.panes = []
        self.selected = 0
        self.resizing = False
        self.notice = ""
        self.failed = False
        self.actions = [
            ("r", tr("Adjust size…", "调整大小…")),
            ("h", tr("Equal columns", "左右均分")),
            ("v", tr("Equal rows", "上下均分")),
            ("t", tr("Tile panes", "平铺分屏")),
            ("p", tr("Swap with previous pane", "与上一分屏换位")),
            ("n", tr("Swap with next pane", "与下一分屏换位")),
        ]

    def tmux(self, *args):
        try:
            result = subprocess.run([self.binary, "-S", self.socket, *args],
                                    capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError(tr("Pane query failed or timed out.", "分屏读取失败或超时。")) from None
        if result.returncode:
            raise RuntimeError(tr("The selected pane is no longer available; go back and select again.",
                                  "所选分屏已不可用，请返回重新选择。"))
        return result.stdout

    def refresh(self):
        try:
            self.window, self.title = self.tmux("display-message", "-p", "-t", self.pane,
                                               "#{window_id}\t#{window_name}").rstrip("\n").split("\t", 1)
            rows = self.tmux("list-panes", "-t", self.window, "-F",
                             "#{pane_id}\t#{pane_index}\t#{pane_current_command}\t#{pane_width}\t#{pane_height}")
            self.panes = []
            for row in rows.splitlines():
                identity, index, program, width, height = row.split("\t")
                self.panes.append(Pane(identity, index, program, int(width), int(height)))
            if not any(pane.identity == self.pane for pane in self.panes):
                raise RuntimeError(tr("The selected pane has closed.", "所选分屏已关闭。"))
        except (RuntimeError, ValueError) as error:
            self.panes = []
            self.failed = True
            self.notice = str(error)
            return False
        return True

    def apply(self, key):
        if not self.refresh():
            return
        self.failed, self.notice = False, ""
        try:
            if key == "r":
                self.resizing = True
                return
            self.resizing = False
            if key in {"h", "v", "t"}:
                self.tmux("select-layout", "-t", self.window,
                          {"h": "even-horizontal", "v": "even-vertical", "t": "tiled"}[key])
            else:
                if len(self.panes) < 2:
                    raise RuntimeError(tr("Swapping needs at least two panes.", "至少需要两个分屏才能换位。"))
                index = next(i for i, pane in enumerate(self.panes) if pane.identity == self.pane)
                other = self.panes[(index + (-1 if key == "p" else 1)) % len(self.panes)]
                self.tmux("swap-pane", "-d", "-s", self.pane, "-t", other.identity)
            self.notice = tr("Applied: ", "已应用：") + dict(self.actions)[key]
            self.refresh()
        except RuntimeError as error:
            self.notice, self.failed = str(error), True

    def on_key(self, key):
        name = getattr(key, "name", None) or key
        if not isinstance(name, str):
            return False
        if name == "KEY_ESCAPE" and self.resizing:
            self.resizing = False
            return False
        if name in {"q", "KEY_ESCAPE"}:
            return True
        if name in {"\t", "KEY_TAB", "KEY_BTAB"}:
            if self.refresh():
                index = next(i for i, pane in enumerate(self.panes) if pane.identity == self.pane)
                self.pane = self.panes[(index + (-1 if name == "KEY_BTAB" else 1)) % len(self.panes)].identity
                self.notice, self.failed = "", False
            return False
        if self.resizing:
            directions = {"KEY_LEFT": "-L", "KEY_RIGHT": "-R", "KEY_UP": "-U", "KEY_DOWN": "-D"}
            if name in directions and self.refresh():
                try:
                    self.tmux("resize-pane", "-t", self.pane, directions[name], "2" if name in {"KEY_LEFT", "KEY_RIGHT"} else "1")
                    self.notice, self.failed = "", False
                    self.refresh()
                except RuntimeError as error:
                    self.notice, self.failed = str(error), True
            elif name in {"KEY_ENTER", "r"}:
                self.resizing = False
            return False
        if name == "MOUSE_LEFT":
            _, y = key.mouse_xy
            if 0 <= y - 4 < len(self.actions):
                self.selected = y - 4
                self.apply(self.actions[self.selected][0])
        elif name in {"KEY_UP", "k", "KEY_DOWN", "j"}:
            self.selected = max(0, min(len(self.actions) - 1,
                                       self.selected + (-1 if name in {"KEY_UP", "k"} else 1)))
        elif name == "KEY_ENTER":
            self.apply(self.actions[self.selected][0])
        elif name in dict(self.actions):
            self.selected = next(i for i, action in enumerate(self.actions) if action[0] == name)
            self.apply(name)
        return False

    def render(self, width, height):
        heading = text(tr("PiMux · Arrange panes", "PiMux · 调整分屏"), TITLE_STYLE)
        current = next((pane for pane in self.panes if pane.identity == self.pane), None)
        summary = text(f"{self.title} · " + (tr("pane ", "分屏 ") + current.index +
                       f" · {current.program} · {current.width}×{current.height}" if current else ""), "#63c5f8")
        note = text(tr("Tab changes the target pane · layout is shared by this window's viewers",
                       "Tab 切换目标分屏 · 布局由此窗口的连接共享"), "dim")
        body = [heading, summary, note, Text("")]
        for index, (key, label) in enumerate(self.actions):
            line = text("▌ " if index == self.selected else "  ", "#63c5f8")
            line.append(key + "  ", style="bold color(215)")
            line.append(label)
            line.no_wrap, line.overflow = True, "ellipsis"
            if index == self.selected:
                line.pad_right(max(0, width - line.cell_len))
                line.stylize("on #303b4e")
            body.append(line)
        for line in (heading, summary, note):
            line.no_wrap, line.overflow = True, "ellipsis"
        if self.resizing:
            hints = [("←↑↓→", tr("resize", "调大小")), ("Enter/Esc", tr("done", "完成")), ("q", tr("back", "返回"))]
        else:
            hints = [("↑↓", tr("select", "选择")), ("Enter", tr("apply", "执行")),
                     ("Tab", tr("pane", "分屏")), ("q", tr("back", "返回"))]
        message = text(self.notice or (tr("Resizing · hold an arrow key to continue", "正在调整大小 · 长按方向键连续调整") if self.resizing else ""),
                       "red" if self.failed else "bold #63c5f8" if self.resizing else "#9ccf9e")
        message.no_wrap, message.overflow = True, "ellipsis"
        return screen(Group(*body), key_hints(hints), width, height, message=message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary")
    parser.add_argument("socket")
    parser.add_argument("pane")
    args = parser.parse_args()
    view = Layout(args.binary, args.socket, args.pane)
    return run_screen(view.render, view.on_key, view.refresh, interval=3)


if __name__ == "__main__":
    raise SystemExit(main())
