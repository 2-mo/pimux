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
import network


def network_sample():
    interfaces = network.parse_interfaces([
        {"ifname": "eth0", "flags": ["UP"], "link_type": "ether", "addr_info": [
            {"family": "inet", "local": "10.0.40.23", "prefixlen": 24},
            {"family": "inet", "local": "10.0.50.23", "prefixlen": 24},
            {"family": "inet6", "local": "fd12:40::23", "prefixlen": 64}]},
        {"ifname": "tailscale0", "flags": ["UP"], "operstate": "UNKNOWN", "addr_info": [
            {"family": "inet", "local": "100.93.12.8", "prefixlen": 32},
            {"family": "inet6", "local": "fd7a:115c:a1e0::8", "prefixlen": 128}]},
        {"ifname": "wan0", "flags": ["UP"], "addr_info": [
            {"family": "inet", "local": "100.65.2.3", "prefixlen": 24}]},
        {"ifname": "lo", "flags": ["UP"], "link_type": "loopback", "addr_info": [
            {"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]},
        {"ifname": "kube-ipvs0", "flags": ["UP"], "linkinfo": {"info_kind": "dummy"}, "addr_info": [
            {"family": "inet", "local": "10.96.0.1", "prefixlen": 32}]},
        {"ifname": "veth7", "flags": ["UP"], "linkinfo": {"info_kind": "veth"}, "addr_info": [
            {"family": "inet6", "local": "fe80::42", "prefixlen": 64}]},
    ])
    routes = network.parse_routes([
        {"dst": "default", "gateway": "10.0.40.1", "dev": "eth0"},
        {"dst": "10.0.40.0/24", "dev": "eth0"},
        {"dst": "10.0.50.0/24", "dev": "eth0"},
        {"dst": "172.22.0.0/16", "dev": "tailscale0", "table": 52},
        {"dst": "172.22.0.0/16", "dev": "eth0", "gateway": "10.0.40.2"},
        {"dst": "100.93.12.99", "dev": "tailscale0", "table": 52},
        {"dst": "10.0.40.23", "type": "local", "dev": "eth0", "table": "local"},
    ], 4)
    routes += network.parse_routes([
        {"dst": "default", "gateway": "fd12:40::1", "dev": "eth0", "metric": 100},
        {"dst": "fd12:40::/64", "dev": "eth0"},
        {"dst": "fe80::/64", "dev": "veth7"},
    ], 6)
    return interfaces, routes, []


def test_network_keeps_multiple_subnets_and_tailscale_routes_distinct(monkeypatch):
    snapshot = network_sample()
    monkeypatch.setattr(network, "read_local", lambda: snapshot)
    monkeypatch.setattr(network, "read_tailscale", lambda: {
        "name": "research.tail-demo.ts.net", "state": "Running",
        "addresses": [network.ipaddress.ip_address("100.93.12.8"), network.ipaddress.ip_address("fd7a:115c:a1e0::8")],
    })
    monkeypatch.setattr(network.ProxyPanel, "refresh", lambda self: None)
    view = network.NetworkView()
    view.refresh()
    content = "\n".join(line.plain for line in view.lines())
    for value in ("10.0.40.23/24", "10.0.50.23/24", "10.0.40.0/24", "10.0.50.0/24",
                  "fd12:40::/64", "100.93.12.8/32", "fd7a:115c:a1e0::8/128", "research.tail-demo.ts.net"):
        assert value in content
    assert content.count("100.93.12.8") == 1
    assert "100.93.12.99" not in content
    assert "10.96.0.1" not in content
    assert "fe80::42" not in content
    routes = [route for route in snapshot[1] if str(route.subnet) == "172.22.0.0/16"]
    assert {(route.device, route.table) for route in routes} == {("tailscale0", "52"), ("eth0", "main")}
    assert "Tailscale" not in next(block[0].plain for block in view.blocks if block[0].plain.startswith("wan0"))
    view.query = "172.22"
    content = "\n".join(line.plain for line in view.lines())
    assert "172.22.0.0/16" in content and "10.0.50.0/24" not in content
    view.query = ""
    view.on_key("a")
    content = "\n".join(line.plain for line in view.lines())
    assert "10.96.0.1/32" in content and "127.0.0.1/8" in content
    assert "fe80::42%veth7/64" in content
    monkeypatch.setattr(network, "read_local", lambda: ([interface for interface in snapshot[0] if interface.name != "tailscale0"], snapshot[1], []))
    view.refresh()
    assert "100.93.12.8" in "\n".join(line.plain for line in view.lines())


def test_network_public_lookup_is_manual_and_does_not_run_during_search(monkeypatch):
    monkeypatch.setattr(network, "read_local", network_sample)
    monkeypatch.setattr(network, "read_tailscale", lambda: None)
    monkeypatch.setattr(network.ProxyPanel, "refresh", lambda self: None)
    calls = []
    def public_ip():
        calls.append(True)
        return "8.8.8.8"
    monkeypatch.setattr(network, "query_public_ip", public_ip)
    view = network.NetworkView()
    view.refresh()
    view.on_key("/")
    view.on_key("p")
    assert view.query == "p" and calls == []
    view.on_key("KEY_ESCAPE")
    view.on_key("p")
    assert view.public == "8.8.8.8" and len(calls) == 1
    view.refresh()
    assert len(calls) == 1


@pytest.mark.parametrize("code,value,valid", [(0, "8.8.8.8", True), (0, "2001:4860:4860::8888", True),
                                              (0, "100.93.12.8", False), (0, "<html>error</html>", False), (28, "", False)])
def test_network_public_lookup_bypasses_proxies_and_validates_address(monkeypatch, code, value, valid):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, code, value, "")
    monkeypatch.setattr(network.subprocess, "run", run)
    if valid:
        assert network.query_public_ip() == value
    else:
        with pytest.raises(RuntimeError):
            network.query_public_ip()
    command, options = calls[0]
    assert command[command.index("--noproxy") + 1] == "*"
    assert command[command.index("--max-time") + 1] == "3" and options["timeout"] == 4


def test_network_optional_tailscale_uses_only_this_devices_addresses(monkeypatch):
    monkeypatch.setattr(network.shutil, "which", lambda name: "/usr/bin/tailscale")
    monkeypatch.setattr(network, "read_json", lambda command: {
        "BackendState": "Running", "Self": {"DNSName": "research.tail-demo.ts.net.", "TailscaleIPs": ["100.93.12.8"]},
        "Peer": {"other": {"TailscaleIPs": ["100.93.12.99"]}},
    })
    status = network.read_tailscale()
    assert status["name"] == "research.tail-demo.ts.net"
    assert [str(address) for address in status["addresses"]] == ["100.93.12.8"]
    def unavailable(command):
        raise RuntimeError("daemon unavailable")
    monkeypatch.setattr(network, "read_json", unavailable)
    assert network.read_tailscale() is None
    monkeypatch.setattr(network.shutil, "which", lambda name: None)
    assert network.read_tailscale() is None


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
    monkeypatch.setenv("PIMUX_LAUNCHER", str(Path(__file__).resolve().parents[1] / "bin/pimux"))
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
        return subprocess.CompletedProcess(args, 0, "off\t12345\n", "")
    monkeypatch.setattr(proxy_ui.subprocess, "run", run)
    view = proxy_ui.ProxyPanel(("/usr/bin/tmux", "/tmp/specific-socket", "%12"))
    view.refresh()
    assert view.mode == "on" and view.observed == "off"
    assert calls[0][1:3] == ["-S", "/tmp/specific-socket"]
    assert calls[0][-2:] == ["%12", "#{@pimux_proxy_status}\t#{pane_pid}"]
    assert not view.inferred
    console = Console(width=width)
    for editing in (False, True):
        if editing:
            view.edit()
        lines = console.render_lines(view.render(width, height), console.options, pad=False)
        assert len(lines) <= height


@pytest.mark.parametrize("environment,session,tty,state,expected", [
    (b"https_proxy=http://example:7890\0", 10, 123, "S", "on"),
    (b"HTTPS_PROXY=http://example:7890\0", 10, 123, "S", "on"),
    (b"no_proxy=localhost\0http_proxy=\0", 10, 123, "S", "off"),
    (b"", 10, 123, "S", "off"),
    (b"https_proxy=http://example:7890\0", 20, 123, "S", ""),
    (b"https_proxy=http://example:7890\0", 10, 456, "S", ""),
    (b"https_proxy=http://example:7890\0", 10, 123, "Z", ""),
])
def test_legacy_proxy_uses_foreground_environment_only(tmp_path, monkeypatch, environment, session, tty, state, expected):
    import proxy_status

    shell = tmp_path / "10"
    foreground = tmp_path / "11"
    shell.mkdir()
    foreground.mkdir()
    (shell / "stat").write_text("10 (bash) S 1 10 10 123 11")
    (shell / "environ").write_bytes(b"HTTP_PROXY=http://shell-only:7890\0")
    (foreground / "stat").write_text(f"11 (foreground task) {state} 10 11 {session} {tty} 11")
    (foreground / "environ").write_bytes(environment)
    monkeypatch.setattr(proxy_status, "Path", lambda path: tmp_path / path.removeprefix("/proc/"))
    assert proxy_status.process_proxy_state(10) == expected
    assert proxy_status.process_proxy_state(0) == ""
    assert proxy_status.process_proxy_state(99) == ""


def test_proxy_panel_falls_back_only_without_a_shell_report(monkeypatch):
    monkeypatch.setattr(proxy_ui, "backend", lambda *args: "on\nhttp://saved-only:7890\n")
    response = ["\t12345\n"]
    monkeypatch.setattr(proxy_ui.subprocess, "run", lambda args, **kwargs:
                        subprocess.CompletedProcess(args, 0, response[0], ""))
    inspected = []
    monkeypatch.setattr(proxy_ui, "process_proxy_state", lambda pid: inspected.append(pid) or "on")
    view = proxy_ui.ProxyPanel(("tmux", "/tmp/specific", "%12"))
    view.refresh()
    assert view.observed == "on" and view.inferred and inspected == ["12345"]
    response[0] = "off\t12345\n"
    view.refresh()
    assert view.observed == "off" and not view.inferred and inspected == ["12345"]
