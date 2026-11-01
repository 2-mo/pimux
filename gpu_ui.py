# pimux-managed: standalone screen primitives adapted from pi.terminal (Apache-2.0).
# Modified for PiMux language, mouse events and terminal cleanup. See LICENSE.
"""The small terminal surface needed by the bundled GPU dashboard."""

import os
import signal
import sys
import time

from blessed import Terminal
from rich.console import Console
from rich.live import Live
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


def run_screen(render, on_key, refresh, *, interval=1):
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
                    if name == "r":
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
