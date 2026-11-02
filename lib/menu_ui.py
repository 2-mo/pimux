# pimux-managed: grouped, keyboard and mouse action menu.
"""Use the home screen's navigation tree in the client-local action popup."""

import argparse
from pathlib import Path

from rich.console import Group
from rich.text import Text

from gpu_ui import TITLE_STYLE, key_hints, run_screen, screen, tr
from inspect_ui import text
from navigation import entries, row, visible


class Menu:
    def __init__(self, result, *, pinned=False):
        self.result = Path(result)
        self.nodes = entries("menu", pinned=pinned)
        self.expanded = {"resources", "network", "settings"}
        self.selected = "workspace"
        self.offset = 0
        self.page_size = 1

    def choose(self, node):
        if not node.parent:
            if node.identity in self.expanded:
                self.expanded.remove(node.identity)
            else:
                self.expanded.add(node.identity)
            return False
        self.result.write_text(node.identity + "\n")
        return True

    def on_key(self, key):
        name = getattr(key, "name", None) or key
        if not isinstance(name, str):
            return False
        nodes = visible(self.nodes, self.expanded)
        index = next((i for i, node in enumerate(nodes) if node.identity == self.selected), 0)
        node = nodes[index]
        if name in {"q", "KEY_ESCAPE"}:
            return True
        if name == "MOUSE_LEFT":
            _, y = key.mouse_xy
            index = self.offset + y - 2
            if 0 <= y - 2 < self.page_size and index < len(nodes):
                self.selected = nodes[index].identity
                return self.choose(nodes[index])
            return False
        steps = {"KEY_UP": -1, "KEY_DOWN": 1, "k": -1, "j": 1,
                 "MOUSE_SCROLL_UP": -3, "MOUSE_SCROLL_DOWN": 3,
                 "KEY_PGUP": -self.page_size, "KEY_PGDOWN": self.page_size}
        if name in steps:
            self.selected = nodes[max(0, min(len(nodes) - 1, index + steps[name]))].identity
        elif name in {"KEY_LEFT", "h"}:
            if node.parent:
                self.selected = node.parent
            else:
                self.expanded.discard(node.identity)
        elif name == "KEY_RIGHT":
            if not node.parent:
                self.expanded.add(node.identity)
        elif name == "KEY_ENTER":
            return self.choose(node)
        else:
            target = next((item for item in self.nodes if item.parent and item.key == name), None)
            if target:
                return self.choose(target)
        return False

    def render(self, width, height):
        nodes = visible(self.nodes, self.expanded)
        index = next((i for i, node in enumerate(nodes) if node.identity == self.selected), 0)
        self.page_size = max(1, height - 3)
        self.offset = max(0, min(self.offset, len(nodes) - self.page_size, index))
        if index >= self.offset + self.page_size:
            self.offset = index - self.page_size + 1
        heading = text(tr("PiMux · Work terminal", "PiMux · 工作终端"), TITLE_STYLE)
        heading.append(f"  [{index + 1}/{len(nodes)}]", style="#8993a7")
        heading.no_wrap, heading.overflow = True, "ellipsis"
        body = [heading, Text("")]
        for index in range(self.offset, min(len(nodes), self.offset + self.page_size)):
            node = nodes[index]
            last = index + 1 == len(nodes) or nodes[index + 1].parent != node.parent
            body.append(row(node, expanded=node.identity in self.expanded, last=last,
                            selected=node.identity == self.selected, width=width))
        hints = [("↑↓", tr("select", "选择")), ("←→", tr("expand", "展开")),
                 ("Enter", tr("open", "进入")), ("q", tr("back", "返回"))]
        return screen(Group(*body), key_hints(hints), width, height)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result")
    parser.add_argument("--pinned", action="store_true")
    args = parser.parse_args()
    view = Menu(args.result, pinned=args.pinned)
    return run_screen(view.render, view.on_key, lambda: None, interval=60)


if __name__ == "__main__":
    raise SystemExit(main())
