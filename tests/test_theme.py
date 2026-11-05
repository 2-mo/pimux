"""Pure rendering/preferences checks; never query a terminal or start tmux."""
import io

import pytest
from rich.console import Group
from rich.style import Style
from rich.table import Table
from rich.text import Text

import gpu_ui
from theme import ThemeConsole, contrast_style, main, preference, resolve_theme


@pytest.fixture(autouse=True)
def clean_theme(monkeypatch):
    for name in ("PIMUX_THEME", "PIMUX_THEME_FILE", "COLORFGBG", "NO_COLOR"):
        monkeypatch.delenv(name, raising=False)


def test_theme_preference_and_diagnostics(monkeypatch, capsys):
    assert preference() == "auto"
    assert resolve_theme() == "default"
    assert main(["light"]) == 0
    assert preference() == "light"
    main([])
    output = capsys.readouterr().out
    assert "Mode: light" in output and "Resolved: light" in output
    assert "Source:" in output and "pimux theme dark" in output
    monkeypatch.setenv("PIMUX_THEME", "dark")
    assert resolve_theme() == "dark"
    main(["auto"])
    assert "overrides the saved preference" in capsys.readouterr().out
    monkeypatch.setenv("PIMUX_THEME", "invalid")
    assert preference() == "auto"
    with pytest.raises(SystemExit):
        main(["invalid"])
    assert preference() == "auto"


@pytest.mark.parametrize("hint,expected", [("0;15", "light"), ("0;7", "light"),
    ("15;0", "dark"), ("15;8", "dark"), ("15;0;0", "dark"),
    ("15;2", "default"), ("garbage", "default"), ("0;9999", "default")])
def test_auto_hint_is_conservative_and_not_shared_between_clients(monkeypatch, hint, expected):
    monkeypatch.setenv("COLORFGBG", hint)
    assert resolve_theme("auto") == expected
    monkeypatch.setenv("TMUX", "/tmp/server,1,0")
    assert resolve_theme("auto") == "default"
    assert resolve_theme("light") == "light"


def test_styles_preserve_metadata_and_are_idempotent():
    original = Style(color="#63c5f8", bgcolor="#303b4e", dim=True,
                     link="https://example.org", meta={"copy_id": "ip"})
    for mode in ("light", "dark", "default"):
        adapted = contrast_style(original, mode)
        assert adapted.meta == original.meta and adapted.link == original.link
        assert contrast_style(adapted, mode) == adapted
    assert contrast_style(original, "dark") == original
    light = contrast_style(original, "light")
    assert light.color.name == "#006482" and light.bgcolor.name == "#dbe5f2"
    assert light.dim is False
    unknown = contrast_style(original, "default")
    assert unknown.color.name == "#ffffff" and unknown.bgcolor.name == "#272b34"
    assert contrast_style(Style(color="#d8dce4"), "default").color.name == "default"


@pytest.mark.parametrize("mode", ["light", "dark", "default"])
def test_nested_selection_and_input_are_readable(mode):
    console = ThemeConsole(theme=mode, width=60, force_terminal=True, color_system="truecolor")
    table = Table.grid()
    table.add_row(Text("selected", style="#63c5f8"), style="on #303b4e")
    segments = list(console.render(Group(table, gpu_ui.input_field("value", 2, 20))))
    chosen = next(s.style for s in segments if "selected" in s.text)
    assert chosen.bgcolor is not None and chosen.color is not None
    assert chosen.color != chosen.bgcolor
    assert any(s.style and s.style.reverse and s.style.bold for s in segments)
    assert console._theme_depth == 0


@pytest.mark.parametrize("mode", ["light", "dark", "default"])
def test_no_color_retains_selection_and_keyboard_labels(mode):
    output = io.StringIO()
    console = ThemeConsole(theme=mode, file=output, no_color=True,
                           force_terminal=True, color_system="truecolor")
    console.print(Text("selected", style="#63c5f8 on #303b4e"))
    console.print(gpu_ui.key_hints([("Enter", "open"), ("q", "back")]))
    rendered = output.getvalue()
    assert "\x1b[7m" in rendered
    assert "38;" not in rendered and "48;" not in rendered
    assert "Enter" in rendered and "back" in rendered


def test_shared_console_covers_manager_menu_and_gpu(monkeypatch, tmp_path):
    from manager_ui import render
    from menu_ui import Menu
    from gpu import Monitor
    monkeypatch.setenv("PIMUX_THEME", "light")
    assert isinstance(gpu_ui.console, ThemeConsole)
    monkeypatch.setattr(gpu_ui.console, "no_color", False)
    views = [render([], [], width=80, height=24, selected=0, count=0),
             Menu(tmp_path / "choice").render(80, 24), Monitor().render(80, 24)]
    pastel = {"#d8dce4", "#63c5f8", "#b7a1e8", "#9ca3af", "#8993a7", "color(215)"}
    for view in views:
        segments = list(gpu_ui.console.render(view))
        assert all(not s.style or not s.style.color or s.style.color.name not in pastel for s in segments)


def test_light_text_contrast_on_white_beige_and_selection():
    from theme import LIGHT

    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                  for value in channels]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))

    for foreground in {"#242936", "#505b6e", "#006482", "#63349a", "#276435", "#885000", "#a32229"}:
        assert foreground in LIGHT.values()
        for background in ("#ffffff", "#e0ddc4", "#dbe5f2"):
            assert (luminance(background) + .05) / (luminance(foreground) + .05) >= 4.5


def test_preference_refresh_never_reads_terminal_input(monkeypatch):
    import sys

    class UnreadableInput:
        def read(self, *args, **kwargs):
            raise AssertionError("theme detection must not consume terminal input")

    monkeypatch.setattr(sys, "stdin", UnreadableInput())
    console = ThemeConsole(no_color=False)
    sample = Text("heading", style="#b7a1e8")
    assert next(console.render(sample)).style.color.name == "default"
    main(["light"])
    assert next(console.render(sample)).style.color.name == "#63349a"
    main(["dark"])
    assert next(console.render(sample)).style.color.name == "#b7a1e8"
    main(["auto"])
    assert next(console.render(sample)).style.color.name == "default"
