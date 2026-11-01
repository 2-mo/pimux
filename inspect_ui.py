# pimux-managed: scrollable, read-only terminal views.
"""A small document view shared by port inspection and window previews."""

import re
import sys

from rich.console import Group
from rich.text import Text

from gpu_ui import MUTED_STYLE, TITLE_STYLE, console, key_hints, run_screen, tr


def text(value, style=""):
    return Text(re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "?", str(value)), style=style)


class Document:
    def __init__(self, title, load, *, searchable=False):
        self.title, self.load, self.searchable = title, load, searchable
        self.blocks = []
        self.error = ""
        self.offset = 0
        self.page_size = 1
        self.total = 0
        self.query = ""
        self.searching = False

    def refresh(self):
        try:
            self.blocks = self.load()
            self.error = ""
        except (OSError, RuntimeError) as error:
            self.blocks = []
            self.error = str(error)

    def lines(self):
        if self.error:
            return [text(self.error, "red")]
        blocks = [block for block in self.blocks
                  if self.query.casefold() in "\n".join(line.plain for line in block).casefold()]
        return [line for block in blocks for line in [*block, Text("")]] or [
            text(tr("No matching entries", "没有匹配的条目"), MUTED_STYLE)]

    def on_key(self, key):
        name = getattr(key, "name", None) or key
        if not isinstance(name, str):
            return False
        if self.searching:
            if name == "KEY_ESCAPE":
                self.query = ""
                self.searching = False
            elif name == "KEY_ENTER":
                self.searching = False
            elif name in {"KEY_BACKSPACE", "KEY_DELETE", "\x7f", "\x08"}:
                self.query = self.query[:-1]
            elif len(name) == 1 and name.isprintable():
                self.query += name
            self.offset = 0
            return False
        if name == "KEY_ESCAPE" and self.query:
            self.query, self.offset = "", 0
            return False
        if name in {"q", "KEY_ESCAPE"}:
            return True
        if name == "/" and self.searchable:
            self.searching = True
            return False
        steps = {"KEY_UP": -1, "KEY_DOWN": 1, "MOUSE_SCROLL_UP": -3, "MOUSE_SCROLL_DOWN": 3,
                 "KEY_PGUP": -self.page_size, "KEY_PGDOWN": self.page_size,
                 "KEY_HOME": -self.total, "KEY_END": self.total}
        self.offset = max(0, min(self.offset + steps.get(name, 0), self.total - self.page_size))
        return False

    def render(self, width, height):
        lines = [part for line in self.lines()
                 for part in line.wrap(console, max(1, width), overflow="fold", no_wrap=False)]
        self.page_size = max(1, height - 3 - self.searchable)
        self.total = len(lines)
        self.offset = max(0, min(self.offset, self.total - self.page_size))
        heading = text(f"PiMux · {self.title}  {self.offset + 1}–{min(self.total, self.offset + self.page_size)}/{self.total}", TITLE_STYLE)
        heading.no_wrap = True
        heading.overflow = "ellipsis"
        search = [text(tr("Search: ", "搜索：") + self.query + ("▏" if self.searching else ""))] if self.searchable else []
        hints = [("Enter", tr("done", "完成")), ("Esc", tr("clear", "清除"))] if self.searching else [
            ("↑↓ PgUp/Dn", tr("scroll", "滚动")), ("r", tr("refresh", "刷新")), ("q", tr("back", "返回"))]
        if self.searchable and not self.searching:
            hints.insert(0, ("/", tr("search", "搜索")))
        if width < 65 and not self.searching:
            hints = ([("/", "")] if self.searchable else []) + [("↑↓ PgUp/Dn", ""), ("q", tr("back", "返回"))]
        footer = key_hints(hints)
        footer.no_wrap, footer.overflow = True, "ellipsis"
        return Group(heading, *search, Text(""), *lines[self.offset:self.offset + self.page_size], footer)

    def run(self, *, once=False):
        if once or not console.is_terminal or not sys.stdin.isatty():
            self.refresh()
            console.print(Group(text(f"PiMux · {self.title}", TITLE_STYLE), *self.lines()))
            return int(bool(self.error))
        return run_screen(self.render, self.on_key, self.refresh, interval=3)
