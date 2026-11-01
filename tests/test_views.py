"""Focused checks for the standalone inspection and proxy views."""

import os
from pathlib import Path
import shutil
import socket
import subprocess
from types import SimpleNamespace

import pytest
from rich.console import Console

from inspect_ui import Document, text
import ports
import proxy_ui


def test_listener_parser_handles_ipv6_multiple_owners_and_hidden_pids():
    rows = ports.parse_listeners('''LISTEN 0 128 [::1]:8888 [::]:* users:(("python",pid=13,fd=3),("worker",pid=14,fd=4))
LISTEN 0 128 0.0.0.0:22 0.0.0.0:*
LISTEN 0 128 127.0.0.1:6006 0.0.0.0:* users:(("tensorboard",pid=12,fd=5))
''')
    assert [row.port for row in rows] == [22, 6006, 8888]
    assert rows[0].owners == ()
    assert rows[2].address == "[::1]:8888"
    assert rows[2].owners == ((13, "python"), (14, "worker"))


def test_port_inspection_finds_a_real_listener_without_affecting_it():
    if not shutil.which("ss"):
        pytest.skip("requires iproute2")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        rows = [row for row in ports.list_listeners() if row.port == port]
        assert any(pid == os.getpid() for row in rows for pid, _ in row.owners)
        content = "\n".join(line.plain for block in ports.port_blocks(port) for line in block)
        assert str(port) in content and str(os.getpid()) in content and str(Path.cwd()) in content
        assert listener.getsockname()[1] == port


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("ss", 3)])
def test_port_query_errors_are_visible(monkeypatch, error):
    def run(*args, **kwargs):
        raise error
    monkeypatch.setattr(ports.subprocess, "run", run)
    view = Document("ports", ports.port_blocks)
    view.refresh()
    assert view.error
    assert view.lines()[0].style == "red"


def test_document_filters_and_scrolls_full_paths_and_handles_literal_controls():
    path = "/research/very-long-project-path/" * 5
    view = Document("ports", lambda: [[text("8888 python"), text(path)], [text("6006 tensorboard")]], searchable=True)
    view.refresh()
    view.on_key("/")
    for char in "8888":
        view.on_key(char)
    view.on_key("KEY_ENTER")
    assert "tensorboard" not in "\n".join(line.plain for line in view.lines())
    console = Console(width=30)
    assert len(console.render_lines(view.render(30, 9), console.options)) <= 9
    view.on_key("KEY_END")
    assert view.offset > 0
    view.on_key(SimpleNamespace(name="MOUSE_SCROLL_UP"))
    assert view.offset < view.total - view.page_size
    assert not view.on_key("KEY_ESCAPE")
    assert view.query == "" and view.offset == 0
    assert view.on_key("KEY_ESCAPE")
    assert "\x1b" not in text("\x1b[2Jhello").plain


@pytest.mark.parametrize("url", ["", "host:99999", "ftp://host:1234", "http://host:0", "http://host/path", "http://host?x=y", "http://bad host:80"])
def test_proxy_editor_rejects_invalid_addresses(url):
    with pytest.raises(ValueError):
        proxy_ui.normalize_url(url)


def test_proxy_editor_accepts_short_addresses_and_ipv6():
    assert proxy_ui.normalize_url("127.0.0.1:7890") == "http://127.0.0.1:7890"
    assert proxy_ui.normalize_url("socks5h://[::1]:1080") == "socks5h://[::1]:1080"


def test_proxy_edit_cancel_validation_and_mouse_use_same_persistence(tmp_path, monkeypatch):
    file = tmp_path / "proxy"
    monkeypatch.setenv("PIMUX_PROXY_FILE", str(file))
    monkeypatch.setenv("PIMUX_LAUNCHER", str(Path(__file__).resolve().parents[1] / "pimux"))
    view = proxy_ui.ProxyPanel()
    view.refresh()
    assert view.mode == "inherit" and not view.url and not view.observed
    view.on_key("KEY_ENTER")
    assert view.editing
    for char in "invalid address":
        view.on_key(char)
    view.on_key("KEY_ENTER")
    assert view.error and view.editing and not file.exists()
    view.on_key("KEY_ESCAPE")
    assert not file.exists()
    view.on_key("e")
    for char in "http://user:private-pass@127.0.0.1:7890":
        view.on_key(char)
    console = Console(width=80)
    lines = console.render_lines(view.render(80, 24), console.options, pad=False)
    rendered = "".join(segment.text for line in lines for segment in line)
    assert "private-pass" not in rendered and "user:" not in rendered
    view.on_key("KEY_ENTER")
    assert view.mode == "on" and file.stat().st_mode & 0o777 == 0o600
    saved = file.read_text()
    view.on_key("e")
    view.on_key("\x15")
    view.on_key("KEY_ESCAPE")
    assert file.read_text() == saved
    view.render(80, 24)
    row = next(y for y, action in view.action_rows.items() if action == 0)
    view.on_key(SimpleNamespace(name="MOUSE_LEFT", mouse_xy=(5, row)))
    assert file.read_text().startswith("off\n")
    view.activate(2)
    assert file.read_text().startswith("inherit\n")


@pytest.mark.parametrize("width,height", [(40, 16), (80, 20), (110, 26)])
def test_proxy_layout_fits_and_reports_the_exact_pane(monkeypatch, width, height):
    calls = []
    monkeypatch.setattr(proxy_ui, "backend", lambda *args: "on\nhttp://127.0.0.1:7890\n")
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "off\n", "")
    monkeypatch.setattr(proxy_ui.subprocess, "run", run)
    view = proxy_ui.ProxyPanel(("/usr/bin/tmux", "/tmp/specific-socket", "%12"))
    view.refresh()
    assert view.mode == "on" and view.observed == "off"
    assert calls[0][1:3] == ["-S", "/tmp/specific-socket"]
    assert calls[0][-2:] == ["%12", "@pimux_proxy_status"]
    console = Console(width=width)
    for editing in (False, True):
        if editing:
            view.edit()
        lines = console.render_lines(view.render(width, height), console.options, pad=False)
        assert len(lines) <= height
