# pimux-managed: standalone screen primitives adapted from pi.terminal (Apache-2.0).
# Modified for PiMux language, mouse events and terminal cleanup. See LICENSE.
"""The small terminal surface needed by the bundled GPU dashboard."""

import os
import signal
import sys
import time

from blessed import Terminal
from rich.console import Console
from rich.console import Group
from rich.cells import cell_len
from rich.live import Live
from rich.segment import Segment, Segments
from rich.text import Text

TITLE_STYLE = "bold #b7a1e8"
SELECTED_STYLE = "on #272b34"
MUTED_STYLE = "dim #9ca3af"
console = Console()


def tr(english, chinese):
    return chinese if os.environ.get("PIMUX_LANGUAGE") == "zh" else english


def status_text(label, *, tone="muted"):
    styles = {"info": "#63c5f8", "success": "green", "warning": "#e5a35b",
              "error": "red", "muted": MUTED_STYLE}
    return Text(str(label), style=styles[tone])


def key_hints(pairs):
    hints = Text()
    for key, label in pairs:
        if hints:
            hints.append("  ")
        hints.append(str(key), style="color(215)")
        hints.append(f" {label}", style="dim")
    return hints


def screen(body, footer, width, height, *, message=None):
    """Keep actions and feedback at the bottom of every full-screen view."""
    options = console.options.update(width=max(1, width))
    height = max(1, height)
    feedback = console.render_lines(message, options, pad=False)[:min(2, height - 1)] if message else []
    budget = height - len(feedback) - 1
    lines = console.render_lines(body, options, pad=False)[:budget]
    lines += [[] for _ in range(budget - len(lines))]
    footer = footer.copy()
    footer.no_wrap, footer.overflow = True, "ellipsis"
    return Group(Segments([segment for line in [*lines, *feedback]
                           for segment in [*line, Segment.line()]]), footer)


def edit_line(value, cursor, key):
    if key in {"KEY_LEFT", "KEY_RIGHT"}:
        cursor = max(0, min(len(value), cursor + (-1 if key == "KEY_LEFT" else 1)))
    elif key in {"KEY_HOME", "\x01"}:
        cursor = 0
    elif key in {"KEY_END", "\x05"}:
        cursor = len(value)
    elif key == "\x15":
        value, cursor = "", 0
    elif key in {"KEY_BACKSPACE", "\x7f", "\x08"} and cursor:
        value, cursor = value[:cursor - 1] + value[cursor:], cursor - 1
    elif key == "KEY_DELETE":
        value = value[:cursor] + value[cursor + 1:]
    elif key.isprintable() and not key.startswith(("KEY_", "MOUSE_")):
        value, cursor = value[:cursor] + key + value[cursor:], cursor + len(key)
    return value, cursor


def input_field(value, cursor, width, *, hidden=False):
    value = value.replace("\n", "↵").replace("\t", "⇥")
    shown = ("•" * len(value) if hidden else "".join(char if char.isprintable() else "?" for char in value)) + " "
    width = max(1, width)
    start = cursor
    while start > 0 and cell_len(shown[start - 1:cursor + 1]) < width:
        start -= 1
    field = Text(shown[start:], style="on #272b34")
    field.stylize("reverse bold", cursor - start, cursor - start + 1)
    field.truncate(width, overflow="crop")
    return field


def run_screen(render, on_key, refresh, *, interval=1, can_refresh=None):
    refresh()
    if not console.is_terminal or not sys.stdin.isatty():
        console.print(render(console.width, console.height))
        return 0
    # Rich honors NO_COLOR; Blessed still needs capabilities for input protocols.
    no_color = os.environ.pop("NO_COLOR", None)
    try:
        term = Terminal(stream=console.file)
    finally:
        if no_color is not None:
            os.environ["NO_COLOR"] = no_color
    aliases = {"\r": "KEY_ENTER", "\n": "KEY_ENTER", "\x1b": "KEY_ESCAPE",
               "KEY_EXIT": "KEY_ESCAPE"}

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        with term.cbreak(), term.mouse_enabled(timeout=0.5), Live(
            console=console, screen=True, auto_refresh=False,
            redirect_stdout=False, redirect_stderr=False,
        ) as live:
            size = (console.width, console.height)
            live.update(render(*size), refresh=True)
            due = time.monotonic() + interval
            while True:
                key = term.inkey(timeout=min(0.2, max(0, due - time.monotonic())), esc_delay=0.05)
                changed = False
                if key:
                    name = key.name if key.is_sequence else str(key)
                    name = aliases.get(name, name)
                    event = key if name and name.startswith("MOUSE_") else name
                    if name == "\x03" or on_key(event):
                        return 0
                    if name == "r" and (can_refresh is None or can_refresh()):
                        refresh()
                        due = time.monotonic() + interval
                    changed = True
                if time.monotonic() >= due:
                    refresh()
                    due = time.monotonic() + interval
                    changed = True
                new_size = (console.width, console.height)
                if changed or new_size != size:
                    size = new_size
                    live.update(render(*size), refresh=True)
    except KeyboardInterrupt:
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
