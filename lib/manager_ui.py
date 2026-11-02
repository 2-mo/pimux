# pimux-managed: shared Rich styling for the main workspace interface.
"""Render structured manager rows without mixing names, programs and paths."""

from dataclasses import dataclass, replace
import os
import sys

from rich.console import Group
from rich.cells import cell_len
from rich.table import Column, Table
from rich.text import Text

from gpu_ui import TITLE_STYLE, console, input_field, key_hints, screen, tr
from inspect_ui import text
from navigation import entries as navigation_entries, row as navigation_row

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


def render(entries, navigation, *, width, height, selected, count, query="", searching=False, error="",
           sidebar_width=0, nav_focused=False, nav_selected="manager", nav_offset=0):
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
    main_width = width - sidebar_width - 2 if sidebar_width else width
    menu_heading = text(" " + tr("Menu", "菜单"), "bold " + (CYAN if nav_focused else PURPLE))
    menu_heading.append(" · Tab", style=MUTED)
    sessions_heading = text(" " + tr("Sessions", "会话"), "bold " + (PURPLE if nav_focused else CYAN))
    if not sidebar_width:
        sessions_heading = text(" " + tr("Menu · Tab", "菜单 · Tab"), MUTED)
    model = {node.identity: node for node in navigation_entries("home")}
    tree = []
    budget = max(1, height - 8)
    if nav_offset:
        menu_heading.append(" ↑", style=CYAN)
    if nav_offset + budget < len(navigation):
        menu_heading.append(" ↓", style=CYAN)
    for index in range(nav_offset, min(len(navigation), nav_offset + budget)):
        identity, expanded = navigation[index]
        node = model[identity]
        last = index + 1 == len(navigation) or model[navigation[index + 1][0]].parent != node.parent
        tree.append(navigation_row(node, expanded=expanded, last=last,
                                   selected=identity == nav_selected, focused=nav_focused,
                                   width=sidebar_width or width))
    session_rows = [entry_row(replace(entry, selected=entry.selected and not nav_focused),
                              main_width, searching=bool(query)) for entry in entries]
    if not count:
        session_rows.extend([Text(""), text(tr(" No matching windows" if query else " No sessions yet",
                                               " 没有匹配的窗口" if query else " 暂无会话"), "bold " + TEXT),
                             key_hints([(" Esc", tr("clear search", "清除搜索"))] if query else
                                       [(" n", tr("new session", "新建会话")), ("Enter", tr("confirm", "确认"))])])
    body = [heading, search_bar]
    if sidebar_width:
        grid = Table.grid(Column(width=sidebar_width), Column(width=2), Column(width=main_width), padding=0)
        grid.add_row(menu_heading, text("│ ", MUTED), sessions_heading)
        for index in range(max(len(tree), len(session_rows))):
            grid.add_row(tree[index] if index < len(tree) else Text(""), text("│ ", "#424b5c"),
                         session_rows[index] if index < len(session_rows) else Text(""))
        body.append(grid)
    elif nav_focused:
        body.extend([menu_heading, *tree])
    else:
        body.extend([sessions_heading, *session_rows])
    if nav_focused:
        hints = [("↑↓", tr("select", "选择")), ("←→", tr("expand", "展开")),
                 ("Enter", tr("open", "进入")), ("Tab", tr("sessions", "会话")), ("q", tr("back", "返回"))]
    elif searching:
        hints = [("↑↓", tr("select", "选择")), ("Enter", tr("open", "进入")), ("Esc", tr("clear", "清除"))]
    else:
        hints = [("Tab", tr("menu", "菜单")), ("/", tr("search", "搜索")), ("Enter", tr("open", "进入"))]
        if width >= 90:
            hints.extend([("n", tr("new", "新建")), ("x", tr("close", "关闭"))])
        hints.append(("q", tr("back", "返回")))
    focused = next((entry for entry in entries if entry.selected), None)
    message = text(error, "red") if error else text(
        " " + focused.path if focused and focused.path and main_width < 64 and not nav_focused else
        tr(" Click an item to open · arrows to expand · Tab to switch focus",
           " 点击进入 · 方向键展开 · Tab 切换区域"), MUTED)
    message.no_wrap, message.overflow = True, "ellipsis"
    return screen(Group(*body), key_hints(hints), width, height, message=message)


def main():
    fields = iter(part.decode(errors="replace") for part in sys.stdin.buffer.read().split(b"\0")[:-1])
    try:
        width, height, selected, count, searching = (int(next(fields)) for _ in range(5))
        query, error = next(fields), next(fields)
        sidebar_width, nav_focused = int(next(fields)), next(fields) == "1"
        nav_selected, nav_offset = next(fields), int(next(fields))
        navigation = [(next(fields), next(fields) == "1") for _ in range(int(next(fields)))]
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
                             count=count, query=query, searching=bool(searching), error=error,
                             sidebar_width=sidebar_width, nav_focused=nav_focused,
                             nav_selected=nav_selected, nav_offset=nav_offset), end="")
    sys.stdout.write("\033[H\033[2J" + capture.get().rstrip("\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
