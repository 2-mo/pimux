"""Native inspector foundation; this is not a macOS terminal support claim."""

import importlib
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

import gpu
import network
import ports

SOURCE = Path(__file__).resolve().parents[1]


def adapter():
    return importlib.import_module("macos")


def test_macos_lsof_records_keep_ipv6_multiple_owners_and_file_boundaries():
    output = ("p13\0cpython worker\0\nf3\0tIPv6\0n[::1]:8888\0\n"
              "f4\0tIPv4\0n127.0.0.1:6006\0\n"
              "p14\0cworker\0\nf5\0tIPv6\0n[::1]:8888\0\n"
              "p15\0chidden\0\nf6\0tIPv4\0n*:22\0\n"
              "f7\0tIPv4\0ninvalid\0\n")
    rows = adapter().parse_listeners(output)
    assert rows == [("*:22", 22, ((15, "hidden"),)),
                    ("127.0.0.1:6006", 6006, ((13, "python worker"),)),
                    ("[::1]:8888", 8888, ((13, "python worker"), (14, "worker")))]


def test_macos_interfaces_preserve_masks_scopes_aliases_and_state():
    output = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 192.0.2.7 netmask 0xffffff00 broadcast 192.0.2.255
\tinet 198.51.100.7 netmask 0xffffff80
\tinet6 fe80::abcd%en0 prefixlen 64 scopeid 0x4
\tinet6 2001:db8::7 prefixlen 64 autoconf secured
en1: flags=8822<BROADCAST,SIMPLEX,MULTICAST> mtu 1500
\tinet 203.0.113.2 netmask 255.255.255.0
"""
    rows = network.parse_interfaces(adapter().parse_interfaces(output))
    assert rows[0].kind == "loopback"
    assert {str(ip) for ip in rows[1].addresses} == {
        "192.0.2.7/24", "198.51.100.7/25", "fe80::abcd/64", "2001:db8::7/64"}
    assert rows[1].up and not rows[2].up


def test_macos_routes_keep_distinct_defaults_and_subnets_without_fabricated_metrics():
    output = """Routing tables
Internet:
Destination Gateway Flags Netif Expire
default 192.0.2.1 UGScg en0
default link#20 UCSIg utun4
10.20/16 link#20 UCS utun4
192.0.2 link#4 UCS en0 !
192.0.2.8 aa:bb:cc:dd:ee:ff UHLWI en0 1199
198.51.100/24 192.0.2.1 UGSc en0
203.0.113/24 127.0.0.1 UGSR lo0
"""
    rows = network.parse_routes(adapter().parse_routes(output, 4), 4)
    assert {(str(row.subnet), row.device) for row in rows} == {
        ("0.0.0.0/0", "en0"), ("0.0.0.0/0", "utun4"), ("10.20.0.0/16", "utun4"),
        ("192.0.2.0/24", "en0"), ("198.51.100.0/24", "en0")}
    assert all(row.table == "system" for row in rows)
    rows = network.parse_routes(adapter().parse_routes(
        "Destination Gateway Flags Netif Expire\ndefault fe80::1%en0 UGcg en0\n"
        "2001:db8:2::/64 link#20 UCS utun4\nfe80::%en0/64 link#4 UCI en0\n", 6), 6)
    assert [str(row.subnet) for row in rows] == ["::/0", "2001:db8:2::/64"]
    assert rows[0].gateway == "fe80::1%en0"


@pytest.mark.parametrize("code,stdout,stderr,valid", [
    (1, "", "", True), (1, "", "permission denied", False),
    (2, "", "failed", False), (0, "p1\0cx\0\nf2\0n*:22\0\n", "", True),
    (0, "p1\0cx\0\nf2\0n*:22\0\n", "warning: incomplete", False),
])
def test_macos_lsof_distinguishes_empty_from_failed_query(monkeypatch, code, stdout, stderr, valid):
    module = adapter()
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, code, stdout, stderr))
    if valid:
        assert bool(module.read_listeners()) == bool(stdout)
    else:
        with pytest.raises(RuntimeError):
            module.read_listeners()


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("lsof", 3), PermissionError()])
def test_macos_query_errors_are_bounded_and_visible(monkeypatch, error):
    module = adapter()
    def run(*args, **kwargs):
        assert kwargs["timeout"] == 3
        raise error
    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(RuntimeError):
        module.read_listeners()
    assert module.process_info(os.getpid()) == ("", "")


def test_macos_process_display_preserves_cwd_whitespace(monkeypatch):
    module = adapter()
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        output = " /usr/bin/python3 script with spaces.py\n" if args[0] == "/bin/ps" else "p123\0\nfcwd\0n/tmp/space \n directory\0\n"
        return subprocess.CompletedProcess(args, 0, output, "")
    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.process_info(123) == ("/usr/bin/python3 script with spaces.py", "/tmp/space \n directory")
    assert all("123" in args for args in calls)
    assert module.process_info("-1; touch anything") == ("", "")
    assert len(calls) == 2


def test_macos_lsof_decodes_utf8_and_escaped_backslashes_once():
    assert adapter()._lsof_text(r"/tmp/\xe6\xb5\x8b\xe8\xaf\x95/line\nnext\\n") == "/tmp/测试/line\nnext\\n"
    assert adapter()._lsof_text(r"literal\\xe6") == r"literal\xe6"


def test_macos_partial_network_failure_is_visible(monkeypatch):
    module = adapter()
    monkeypatch.setattr(network.sys, "platform", "darwin")
    monkeypatch.setattr(module, "read_interfaces", lambda: [])
    def routes(version):
        if version == 6:
            raise RuntimeError("unavailable")
        return [{"dst": "default", "dev": "en0", "gateway": "192.0.2.1"}]
    monkeypatch.setattr(module, "read_routes", routes)
    interfaces, routes, errors = network.read_local()
    assert not interfaces and len(routes) == 1 and len(errors) == 1


def test_missing_nvidia_on_macos_does_not_claim_no_gpu(monkeypatch):
    monkeypatch.setattr(gpu.sys, "platform", "darwin")
    monkeypatch.setenv("PIMUX_LANGUAGE", "en")
    monkeypatch.setattr(gpu.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    monitor = gpu.Monitor()
    monitor.refresh()
    assert monitor.gpus == [] and monitor.error
    assert "Apple GPU" in monitor.error


@pytest.mark.parametrize("script", ["install.sh", "scripts/setup-tmux.sh"])
def test_installer_rejects_macos_before_dependencies_or_home_writes(tmp_path, script):
    tools = tmp_path / "tools"
    tools.mkdir()
    uname = tools / "uname"
    uname.write_text("#!/bin/sh\nprintf 'Darwin\\n'\n")
    uname.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(["/bin/bash", str(SOURCE / script)],
                            env={**os.environ, "HOME": str(home), "PATH": f"{tools}:/usr/bin:/bin"},
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "Linux" in result.stderr and "macOS" in result.stderr
    assert "syntax error" not in result.stderr
    assert not list(home.iterdir())


@pytest.mark.skipif(sys.platform != "darwin", reason="requires real macOS, not emulated command output")
def test_native_macos_listener_process_and_network_are_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        rows = [row for row in ports.list_listeners() if row.port == port]
        assert any(pid == os.getpid() for row in rows for pid, _ in row.owners)
        command, cwd = ports.process_info(os.getpid())
        assert command and Path(cwd).resolve() == Path.cwd().resolve()
        result = subprocess.run([sys.executable, str(SOURCE / "lib/ports.py"), str(port), "--once"],
                                env={**os.environ, "PIMUX_LANGUAGE": "en", "COLUMNS": "240"},
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert str(os.getpid()) in result.stdout and str(port) in result.stdout
        assert "Only listeners visible to this user" in result.stdout
        interfaces, routes, errors = network.read_local()
        assert any(ip.ip.is_loopback for row in interfaces for ip in row.addresses)
        assert not errors
        with socket.create_connection(listener.getsockname(), timeout=2):
            accepted, _ = listener.accept()
            accepted.close()
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(sys.platform != "darwin", reason="requires real macOS process visibility")
def test_native_macos_child_cwd_and_exit(tmp_path):
    directory = tmp_path / '工作 "task" $directory \\n\nline'
    directory.mkdir()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=directory)
    try:
        command, cwd = ports.process_info(child.pid)
        assert "time.sleep(30)" in command
        assert Path(cwd).resolve() == directory.resolve()
    finally:
        child.terminate()
        child.wait(timeout=5)
    assert ports.process_info(child.pid) == ("", "")


@pytest.mark.skipif(sys.platform != "darwin", reason="requires the actual Apple Bash 3.2 runtime")
def test_apple_bash_reports_runtime_requirement_before_loading_libraries(tmp_path):
    result = subprocess.run(["/bin/bash", str(SOURCE / "bin/pimux"), "--version"],
                            env={**os.environ, "HOME": str(tmp_path)}, text=True, capture_output=True)
    assert result.returncode != 0 and "Bash >= 4.2" in result.stderr
    assert "syntax error" not in result.stderr
    assert not list(tmp_path.iterdir())
