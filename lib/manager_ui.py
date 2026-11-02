# pimux-managed: shared Rich styling for the main workspace interface.
"""Render structured manager rows without mixing names, programs and paths."""

from dataclasses import dataclass
import os
import sys

from rich.console import Group
from rich.cells import cell_len
from rich.table import Column, Table
from rich.text import Text

from gpu_ui import TITLE_STYLE, console, input_field, key_hints, screen, tr
from inspect_ui import text

TEXT = "#d8dce4"
MUTED = "#8993a7"
CYAN = "#63c5f8"
PURPLE = "#b7a1e8"
GREEN = "#9ccf9e"
SELECTED = "on #303b4e"


@dataclass
class Entry:
    session: str
    name: str
    program: str
    path: str
    count: str
    expanded: bool
    pinned: bool
    selected: bool


def path_label(value, width):
    home = os.path.expanduser("~")
    if value == home or value.startswith(home + "/"):
        value = "~" + value[len(home):]
    value = text(value).plain
    if cell_len(value) <= width:
        return value
    tail, used = [], 1
    for char in reversed(value):
        size = cell_len(char)
        if used + size > width:
            break
        tail.append(char)
        used += size
    return "…" + "".join(reversed(tail))


def entry_row(entry, width, *, searching=False):
    row = text("▌" if entry.selected else " ", CYAN)
    if not entry.name:
        row.append("v " if entry.expanded else "> ", style=CYAN if entry.selected else MUTED)
        row.append_text(text(entry.session, "bold " + (CYAN if entry.selected else PURPLE)))
        row.append("  " + entry.count + " " + tr("window" if entry.count == "1" else "windows", "窗口"), style=MUTED)
        if entry.pinned:
            row.append("  *", style="bold color(215)")
        row.no_wrap, row.overflow = True, "ellipsis"
        if entry.selected:
            row.pad_right(max(0, width - row.cell_len))
            row.stylize(SELECTED)
        return row
    row.append("    ")
    if searching:
        row.append_text(text(entry.session + " / ", MUTED))
    index, _, name = entry.name.partition(":")
    row.append_text(text(index + ":", MUTED))
    row.append_text(text(name, "bold " + (CYAN if entry.selected else TEXT)))
    row.no_wrap, row.overflow = True, "ellipsis"
    program_width = 16 if width >= 64 else min(12, max(7, width // 4))
    name_width = max(1, min(44, width * 2 // 5)) if width >= 64 else max(1, width - program_width - 2)
    columns = [Column(width=name_width, no_wrap=True, overflow="ellipsis"),
               Column(width=program_width, no_wrap=True, overflow="ellipsis")]
    cells = [row, text(entry.program, GREEN if entry.program not in {"[]", "[bash]", "[zsh]", "[sh]"} else MUTED)]
    if width >= 64:
        columns.append(Column(ratio=1, no_wrap=True, overflow="ellipsis"))
        cells.append(text(path_label(entry.path, max(1, width - name_width - program_width - 4)),
                          "#b0bacb" if entry.selected else MUTED))
    table = Table.grid(*columns, padding=(0, 2), expand=True)
    table.add_row(*cells, style=SELECTED if entry.selected else "")
    return table


def render(entries, navigation, *, width, height, selected, count, query="", searching=False, error=""):
    heading = text(" PiMux", TITLE_STYLE)
    heading.append(" · ", style=MUTED)
    heading.append(tr("Session manager", "会话管理"), style=TEXT)
    heading.no_wrap, heading.overflow = True, "ellipsis"
    position = text(f"[{selected + 1 if count else 0}/{count}] ", MUTED)
    search_width = max(1, width - position.cell_len)
    search = text(" / ", "color(215)")
    if searching:
        search.append_text(input_field(query, len(query), max(1, search_width - 3)))
    else:
        search.append(tr("Search sessions, programs or paths", "搜索会话、程序或目录"), style=MUTED)
    search.no_wrap, search.overflow = True, "ellipsis"
    search_bar = Table.grid(Column(width=search_width), Column(width=position.cell_len, justify="right"), expand=True)
    search_bar.add_row(search, position)
    actions = Text(" ")
    for key, label in navigation:
        button = text(key, "bold color(215) on #272d39")
        button.append(" " + label, style=TEXT + " on #272d39")
        actions.append_text(button)
        actions.append(" ")
    actions.no_wrap, actions.overflow = True, "crop"
    body = [heading, search_bar, actions]
    body.extend(entry_row(entry, width, searching=bool(query)) for entry in entries)
    if not count:
        body.extend([Text(""), text(tr(" No matching windows" if query else " No sessions yet",
                                      " 没有匹配的窗口" if query else " 暂无会话"), "bold " + TEXT),
                     key_hints([(" Esc", tr("clear search", "清除搜索"))] if query else
                               [(" n", tr("create a session", "新建会话")), ("Enter", tr("confirm name", "确认名称"))])])
    if searching:
        hints = [("Enter", tr("open", "进入")), ("Esc", tr("clear", "清除"))]
        if width >= 80:
            hints.insert(0, ("↑↓", tr("select", "选择")))
    else:
        hints = [("/", tr("search", "搜索")), ("Enter", tr("open", "进入")),
                 ("d", tr("preview", "预览")), ("q", tr("back", "返回"))]
        if width >= 80:
            hints = [("/", tr("search", "搜索")), ("↑↓", tr("select", "选择")),
                     ("←→", tr("expand", "展开")), ("Enter", tr("open", "进入")),
                     ("d", tr("preview", "预览")), ("p", tr("pin", "置顶")),
                     ("n", tr("new", "新建")), ("x", tr("close", "关闭")), ("q", tr("back", "返回"))]
    focused = next((entry for entry in entries if entry.selected), None)
    message = text(error, "red") if error else text(
        " " + focused.path if focused and focused.path and width < 64 else
        tr(" Click to open · click arrow to expand/collapse · wheel to scroll",
           " 点击进入 · 点箭头展开／收起 · 滚轮翻动"), MUTED)
    return screen(Group(*body), key_hints(hints), width, height, message=message)


def main():
    fields = iter(part.decode(errors="replace") for part in sys.stdin.buffer.read().split(b"\0")[:-1])
    try:
        width, height, selected, count, searching = (int(next(fields)) for _ in range(5))
        query, error = next(fields), next(fields)
        navigation = [(next(fields), next(fields)) for _ in range(int(next(fields)))]
        entries = []
        for _ in range(int(next(fields))):
            session, name, program, path, windows = (
                next(fields).replace("\n", "?").replace("\t", "?") for _ in range(5))
            expanded, pinned, chosen = (next(fields) == "1" for _ in range(3))
            entries.append(Entry(session, name, program, path, windows, expanded, pinned, chosen))
    except (ValueError, StopIteration):
        return 2
    with console.capture() as capture:
        console.print(render(entries, navigation, width=width, height=height, selected=selected,
                             count=count, query=query, searching=bool(searching), error=error), end="")
    sys.stdout.write("\033[H\033[2J" + capture.get().rstrip("\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
