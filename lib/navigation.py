# pimux-managed: shared navigation model for the home screen and action menu.
"""One set of groups, labels and keys for both entry points."""

import argparse
from dataclasses import dataclass, replace
import sys

from rich.text import Text

from gpu_ui import tr


@dataclass(frozen=True)
class Entry:
    identity: str
    parent: str
    key: str
    english: str
    chinese: str
    icon: str = ""
    place: str = "both"

    @property
    def label(self):
        return tr(self.english, self.chinese)


GROUPS = [Entry("workspace", "", "", "Workspace", "工作区", "▦"),
          Entry("resources", "", "", "Resources", "资源", "◉"),
          Entry("network", "", "", "Network", "网络", "≋"),
          Entry("settings", "", "", "Settings", "设置", "◇")]

ITEMS = [
    Entry("manager", "workspace", "s", "Sessions / windows", "会话 / 窗口"),
    Entry("new-session", "workspace", "n", "New session", "新建会话", place="home"),
    Entry("new-window", "workspace", "c", "New window", "新建窗口", place="menu"),
    Entry("rename-window", "workspace", ",", "Rename window", "重命名窗口", place="menu"),
    Entry("pin", "workspace", "p", "Pin / unpin", "置顶 / 取消置顶"),
    Entry("path", "workspace", "P", "Full directory path", "完整目录路径", place="menu"),
    Entry("copy-path", "workspace", "y", "Copy directory", "复制当前目录", place="menu"),
    Entry("split-horizontal", "workspace", "|", "Split left / right", "左右分屏", place="menu"),
    Entry("split-vertical", "workspace", "-", "Split top / bottom", "上下分屏", place="menu"),
    Entry("layout", "workspace", "a", "Arrange panes", "调整分屏"),
    Entry("zoom", "workspace", "z", "Zoom / restore", "放大 / 恢复", place="menu"),
    Entry("close-pane", "workspace", "x", "Close pane (confirm)", "关闭分屏（确认）", place="menu"),
    Entry("detach", "workspace", "d", "Detach, keep tasks", "离开，保留任务", place="menu"),
    Entry("gpu", "resources", "g", "GPU details", "显卡详情"),
    Entry("ip", "network", "i", "IP & subnets", "IP 与子网"),
    Entry("ports", "network", "t", "Listening ports", "端口查看"),
    Entry("proxy", "network", "o", "Network proxy", "网络代理"),
    Entry("environment", "settings", "e", "Environment", "环境变量"),
    Entry("language", "settings", "l", "Language / 语言", "Language / 语言", place="menu"),
    Entry("help", "settings", "/", "Help", "快捷键帮助"),
    Entry("reload", "settings", "r", "Reload", "重载配置", place="menu"),
    Entry("update", "settings", "u", "Update PiMux", "更新 PiMux"),
]


def entries(place, *, pinned=False):
    result = []
    for group in GROUPS:
        result.append(group)
        for item in ITEMS:
            if item.parent != group.identity or item.place not in {"both", place}:
                continue
            if place == "home" and item.identity == "manager":
                item = replace(item, english="Sessions")
            if place == "home" and item.identity == "help":
                item = replace(item, key="?")
            if place == "menu" and item.identity == "pin":
                item = replace(item, english="Unpin session" if pinned else "Pin session",
                               chinese="取消置顶当前会话" if pinned else "置顶当前会话")
            result.append(item)
    return result


def visible(nodes, expanded):
    return [node for node in nodes if not node.parent or node.parent in expanded]


def row(node, *, expanded=False, last=False, selected=False, focused=True, width=None):
    line = Text("▌" if selected and focused else " ", style="#63c5f8")
    if not node.parent:
        line.append("▾ " if expanded else "▸ ", style="#8993a7")
        line.append(node.icon + " ", style="#63c5f8" if node.identity == "network" else "#b7a1e8")
        line.append(node.label, style="bold #b7a1e8")
    else:
        line.append("  └─ " if last else "  ├─ ", style="#687388")
        line.append(node.key + " ", style="bold color(215)")
        line.append(node.label, style="#63c5f8" if selected else "#d8dce4")
    line.no_wrap, line.overflow = True, "ellipsis"
    if selected and focused:
        if width:
            line.pad_right(max(0, width - line.cell_len))
        line.stylize("on #303b4e")
    return line


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", choices=["home", "menu"], required=True)
    args = parser.parse_args()
    for entry in entries(args.dump):
        sys.stdout.buffer.write(("\0".join((entry.identity, entry.parent, entry.key)) + "\0").encode())


if __name__ == "__main__":
    main()
