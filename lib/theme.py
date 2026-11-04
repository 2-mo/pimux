# pimux-managed: shared terminal contrast and persistent theme preference.
"""Theme selection without terminal queries or consuming keyboard input.

COLORFGBG is a conventional palette hint, not a measurement. Inside tmux it
may belong to the server's first client, so use terminal defaults instead.
"""

import argparse
import os
from pathlib import Path
import tempfile

from rich.console import Console
from rich.segment import Segment
from rich.style import Style

MODES = ("auto", "light", "dark")
LIGHT = {
    "#d8dce4": "#242936", "#8993a7": "#505b6e", "#9ca3af": "#505b6e",
    "#b0bacb": "#505b6e", "#687388": "#505b6e", "#424b5c": "#606b7d",
    "#454957": "#606b7d", "#63c5f8": "#006482", "#b7a1e8": "#63349a",
    "#9ccf9e": "#276435", "#e5a35b": "#885000", "#ffaf5f": "#885000",
    "color(215)": "#885000", "green": "#276435", "red": "#a32229",
    "yellow": "#885000",
}


def preference_path():
    return Path(os.environ.get("PIMUX_THEME_FILE", "~/.config/pimux/theme")).expanduser()


def preference_info():
    override = os.environ.get("PIMUX_THEME")
    if override in MODES:
        return override, "PIMUX_THEME"
    try:
        saved = preference_path().read_text().strip()
    except (OSError, UnicodeError):
        saved = ""
    return (saved, str(preference_path())) if saved in MODES else ("auto", "default")


def preference():
    return preference_info()[0]


def resolve_theme(mode=None):
    mode = preference() if mode is None else mode
    if mode in ("light", "dark"):
        return mode
    # A tmux server's environment is not a per-client background signal.
    if not os.environ.get("TMUX"):
        parts = os.environ.get("COLORFGBG", "").split(";")
        if len(parts) in (2, 3) and all(len(part) <= 3 and part.isdecimal() for part in parts):
            background = int(parts[-1])
            if background in (7, 15):
                return "light"
            if background in (0, 8):
                return "dark"
    return "default"


def contrast_style(style, mode, *, no_color=False):
    """Adapt at the render boundary, including nested tables, spans and panels.

    Keep metadata (mouse/copy targets), links and emphasis intact. Unknown
    backgrounds use the user's normal foreground, never a guessed pastel.
    Selections always have a paired foreground and background.
    """
    style = style or Style()
    if no_color:
        if style.bgcolor and style.bgcolor.name != "default":
            return style + Style(dim=False, reverse=True)
        return style + Style(dim=False)
    if mode == "dark":
        return style
    foreground = style.color.name if style.color else None
    background = style.bgcolor.name if style.bgcolor else None
    if mode == "light":
        foreground = LIGHT.get(foreground, foreground) or "#242936"
        if background in ("#272b34", "#303b4e"):
            background = "#dbe5f2"
    else:
        foreground = "#ffffff" if background and background != "default" else "default"
        background = "#272b34" if background and background != "default" else "default"
    return style + Style(color=foreground, bgcolor=background, dim=False)


class ThemeConsole(Console):
    """Use one palette for every PiMux view without changing its render model."""

    def __init__(self, *args, theme=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.theme = theme
        self._theme_depth = 0

    def render(self, renderable, options=None):
        outer = self._theme_depth == 0
        mode = resolve_theme(self.theme) if outer else None
        self._theme_depth += 1
        try:
            for segment in super().render(renderable, options):
                if outer and not segment.control:
                    adapted = contrast_style(segment.style, mode, no_color=self.no_color)
                    yield Segment(segment.text, adapted, segment.control)
                else:
                    yield segment
        finally:
            self._theme_depth -= 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="PiMux terminal contrast preference")
    parser.add_argument("mode", nargs="?", choices=MODES)
    args = parser.parse_args(argv)
    if args.mode:
        path = preference_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
                temporary = Path(file.name)
                file.write(args.mode + "\n")
            try:
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError as error:
            parser.exit(1, f"Could not save theme: {error}\n")
        print(f"Saved theme: {args.mode}. Reopen a view to apply; running tasks are unchanged.")
        if os.environ.get("PIMUX_THEME") in MODES:
            print(f"PIMUX_THEME={os.environ['PIMUX_THEME']} overrides the saved preference in this shell.")
    else:
        mode, source = preference_info()
        effective = resolve_theme(mode)
        resolution = "explicit preference" if mode != "auto" else (
            "COLORFGBG palette hint" if effective != "default" else "terminal-default foreground")
        print(f"Mode: {mode}\nResolved: {effective}\nSource: {source}; {resolution}")
        print("Set contrast: pimux theme light | pimux theme dark | pimux theme auto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
