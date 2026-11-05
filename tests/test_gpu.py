"""Regressions for the standalone GPU monitor adapted from pi gpu."""

import subprocess

import pytest

import gpu

@pytest.fixture(autouse=True)
def nvidia_platform(monkeypatch):
    monkeypatch.setattr(gpu.sys, "platform", "linux")


CSV = '0, "GPU, A", 100, 900, 1000, 81, 123.5, 250\n2, GPU B, N/A, [N/A], 0, [Not Supported], N/A, N/A\n'


def test_mouse_selects_cards_and_keeps_navigation_in_bounds():
    from dataclasses import replace
    from types import SimpleNamespace

    monitor = gpu.Monitor()
    card = gpu.parse_gpus(CSV)[0]
    monitor.gpus = [replace(card, index=i) for i in range(20)]
    monitor.render(80, 12)
    monitor.on_key(SimpleNamespace(name='MOUSE_LEFT', mouse_xy=(17, 5)))
    assert monitor.selected == 5
    monitor.on_key(SimpleNamespace(name='MOUSE_LEFT', mouse_xy=(70, 5)))
    assert monitor.selected == 5  # Empty space outside the compact cards.
    monitor.on_key(SimpleNamespace(name='MOUSE_SCROLL_DOWN'))
    assert monitor.selected == 9
    monitor.render(80, 12)
    monitor.on_key(SimpleNamespace(name='MOUSE_LEFT', mouse_xy=(1, 1)))
    assert monitor.selected == monitor.page_start


def test_parse_gpu_csv_and_unavailable_metrics():
    cards = gpu.parse_gpus(CSV)
    assert cards[0].index == 0
    assert cards[0].name == "GPU, A"
    assert cards[0].utilization == 100
    assert cards[0].memory_percent == 90
    assert cards[0].power_draw == 123.5
    assert cards[1].utilization is None
    assert cards[1].temperature is None
    assert cards[1].memory_percent is None
    assert gpu.parse_gpus("\n") == []
    with pytest.raises(gpu.GPUReadError):
        gpu.parse_gpus("0, GPU, invalid\n")


def test_query_uses_one_bounded_structured_query(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, CSV, "")

    monkeypatch.setattr(gpu.subprocess, "run", run)
    assert len(gpu.query_gpus()) == 2
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "nvidia-smi"
    assert "--format=csv,noheader,nounits" in args
    assert kwargs["timeout"] == 3


@pytest.mark.parametrize("error", [FileNotFoundError(), OSError("denied"),
                                    subprocess.TimeoutExpired("nvidia-smi", 3)])
def test_query_process_errors(monkeypatch, error):
    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(gpu.subprocess, "run", run)
    with pytest.raises(gpu.GPUReadError):
        gpu.query_gpus()


@pytest.mark.parametrize("code,stdout,stderr,empty", [
    (1, "", "Driver failure", False),
    (6, "No devices were found\n", "", True),
    (0, "", "", True),
    (0, "malformed data", "", False),
])
def test_query_driver_and_empty_results(monkeypatch, code, stdout, stderr, empty):
    monkeypatch.setattr(gpu.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, code, stdout, stderr))
    if empty:
        assert gpu.query_gpus() == []
    else:
        with pytest.raises(gpu.GPUReadError):
            gpu.query_gpus()


def test_monitor_only_refresh_queries_and_recovers(monkeypatch):
    monkeypatch.setattr(gpu, "query_processes", lambda index: [])
    snapshots = iter([gpu.parse_gpus(CSV), gpu.GPUReadError("driver failure"), gpu.parse_gpus(CSV)])
    calls = []

    def query():
        calls.append(True)
        result = next(snapshots)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(gpu, "query_gpus", query)
    monitor = gpu.Monitor()
    monitor.refresh()
    monitor.render(120, 24)
    monitor.on_key("KEY_DOWN")
    monitor.render(40, 12)
    assert monitor.selected == 1
    assert len(calls) == 1
    assert monitor.on_key("KEY_ESCAPE")
    monitor.refresh()
    assert monitor.error == "driver failure"
    assert monitor.gpus == []
    monitor.refresh()
    assert monitor.error is None
    assert len(monitor.gpus) == 2


def test_monitor_history_is_bounded_and_cleared_on_gaps_or_missing_devices(monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(gpu, "query_processes", lambda index: [])
    now = [0.0]
    cards = gpu.parse_gpus(CSV)
    result = [cards]

    def query():
        if isinstance(result[0], Exception):
            raise result[0]
        return result[0]

    monkeypatch.setattr(gpu, "query_gpus", query)
    monkeypatch.setattr(gpu.time, "monotonic", lambda: now[0])
    monitor = gpu.Monitor()
    for second in range(35):
        now[0] = second
        monitor.refresh()
    assert list(monitor.history[0]) == [100] * 30
    assert list(monitor.history[2]) == [None] * 30
    result[0] = [replace(cards[0], utilization=None)]
    now[0] += 1
    monitor.refresh()
    assert set(monitor.history) == {0}
    assert list(monitor.history[0])[-2:] == [100, None]
    now[0] += 4
    monitor.refresh()
    assert list(monitor.history[0]) == [None]
    result[0] = gpu.GPUReadError("driver unavailable")
    monitor.refresh()
    assert monitor.history == {}
    result[0] = cards
    monitor.refresh()
    assert list(monitor.history[0]) == [100]
    result[0] = []
    monitor.refresh()
    assert monitor.history == {}


@pytest.mark.parametrize("width,columns", [(20, 1), (24, 1), (40, 2), (48, 3), (80, 4)])
def test_monitor_grid_navigation_and_height_pagination(width, columns):
    from dataclasses import replace

    monitor = gpu.Monitor()
    monitor.details = False
    card = gpu.parse_gpus(CSV)[0]
    monitor.gpus = [replace(card, index=i) for i in range(8)]
    monitor.render(width, 9)
    assert monitor.columns == columns
    assert monitor.page_size >= columns
    page_size = monitor.page_size
    monitor.on_key("KEY_DOWN")
    assert monitor.selected == columns
    monitor.on_key("KEY_RIGHT")
    assert monitor.selected == columns + 1
    monitor.on_key("KEY_UP")
    assert monitor.selected == 1
    monitor.on_key("KEY_LEFT")
    assert monitor.selected == 0
    monitor.on_key("KEY_PGDOWN")
    assert monitor.selected == min(7, page_size)
    monitor.on_key("KEY_PGUP")
    assert monitor.selected == 0
    monitor.on_key("d")
    monitor.render(width, 9)
    assert monitor.page_size == columns
    monitor.render(width, monitor.full_height(width))
    assert monitor.page_size >= 8
    monitor.compact = True
    monitor.render(width, monitor.full_height(width))
    assert monitor.columns == 1
    assert monitor.page_size >= 8


@pytest.mark.parametrize("output", ["", '123, /env/bin/python, 1024\n456, worker, N/A\n'])
def test_process_query_is_bounded_and_selected(monkeypatch, output):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(gpu.subprocess, "run", run)
    monkeypatch.setattr(gpu, "_process_details", lambda pid: (None, None))
    processes = gpu.query_processes(2)
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[1:3] == ["-i", "2"]
    assert kwargs["timeout"] == 3
    if output:
        assert processes == [gpu.GPUProcess(123, "/env/bin/python", 1024), gpu.GPUProcess(456, "worker", None)]
    else:
        assert processes == []


def test_process_details_preserve_command_arguments_and_tolerate_invisible_processes(tmp_path, monkeypatch):
    import shlex

    directory = tmp_path / "123"
    directory.mkdir()
    argv = ["/env/bin/python", "train.py", "--data", "/data/my dataset", ""]
    (directory / "cmdline").write_bytes(b"\0".join(arg.encode() for arg in argv) + b"\0")
    (directory / "cwd").symlink_to(tmp_path)
    monkeypatch.setattr(gpu, "Path", lambda path: tmp_path / path.removeprefix("/proc/"))
    command, cwd = gpu._process_details(123)
    assert shlex.split(command) == argv
    assert cwd == str(tmp_path)
    assert gpu._process_details(456) == (None, None)

    def denied(*args):
        raise PermissionError()

    monkeypatch.setattr(type(directory), "read_bytes", denied)
    assert gpu._process_details(123) == (None, str(tmp_path))


def test_selected_process_refresh_and_failure_are_independent(monkeypatch):
    monkeypatch.setattr(gpu, "query_gpus", lambda: gpu.parse_gpus(CSV))
    calls = []

    def query(index):
        calls.append(index)
        if index == 2:
            raise gpu.GPUReadError("process unavailable")
        return [gpu.GPUProcess(12345, "worker", 1024)]

    monkeypatch.setattr(gpu, "query_processes", query)
    monitor = gpu.Monitor()
    monitor.refresh()
    assert calls == []
    monitor.on_key("d")
    monitor.refresh()
    assert monitor.process_gpu == 0
    assert monitor.processes[0].pid == 12345
    monitor.render(20, 24)
    monitor.on_key("KEY_DOWN")
    assert monitor.selected == 1
    assert "worker" not in "\n".join(line.plain for line in monitor._detail_lines())
    assert calls == [0]
    monitor.refresh()
    assert calls == [0, 2]
    assert monitor.process_gpu == 2
    assert monitor.process_error
    assert monitor.error is None
    assert len(monitor.gpus) == 2
    monitor.on_key("d")
    monitor.refresh()
    assert calls == [0, 2]


@pytest.mark.parametrize("width,height", [(20, 5), (20, 9), (20, 14), (40, 12), (80, 24)])
def test_details_fit_height_and_keep_selected_card_visible(width, height):
    from dataclasses import replace
    from rich.console import Console

    monitor = gpu.Monitor()
    monitor.details = True
    card = gpu.parse_gpus(CSV)[0]
    monitor.gpus = [replace(card, index=i) for i in range(8)]
    monitor.selected = 7
    monitor.process_gpu = 7
    monitor.processes = [gpu.GPUProcess(i, "worker", 1024) for i in range(5)]
    rendered = monitor.render(width, height)
    console = Console(width=width)
    lines = console.render_lines(rendered, console.options, pad=False)
    assert len(lines) <= height
    text = "\n".join("".join(segment.text for segment in line) for line in lines)
    assert "›GPU 7" in text
    assert monitor.page_size >= monitor.columns


def test_long_process_details_wrap_and_scroll_without_losing_paths():
    from rich.console import Console
    from types import SimpleNamespace

    monitor = gpu.Monitor()
    monitor.gpus = gpu.parse_gpus(CSV)
    monitor.details = True
    monitor.process_gpu = 0
    monitor.processes = [
        gpu.GPUProcess(i, f"/long/environment/name-{i}/bin/python", 1024,
                       f"python /research/实验项目/experiment-{i}/train.py --batch-size 32",
                       f"/research/project-{i}/working-directory")
        for i in range(6)
    ]
    console = Console(width=40)
    seen = {}
    while True:
        lines = console.render_lines(monitor.render(40, 12), console.options, pad=False)
        assert len(lines) <= 12
        page = "".join("".join(segment.text for line in lines for segment in line).split())
        details = monitor._detail_lines(40)
        for index in range(monitor.detail_offset,
                           min(len(details), monitor.detail_offset + monitor.detail_page_size)):
            assert "".join(details[index].plain.split()) in page
            seen[index] = details[index].plain
        previous = monitor.detail_offset
        monitor.on_key("KEY_PGDOWN")
        if monitor.detail_offset == previous:
            break
    assert len(seen) == monitor.detail_total
    text = "".join("".join(seen[index] for index in sorted(seen)).split())
    for process in monitor.processes:
        for value in (process.name, process.command, process.cwd):
            assert "".join(value.split()) in text
    assert monitor.selected == 0
    monitor.on_key("KEY_HOME")
    assert monitor.detail_offset == 0
    monitor.on_key(SimpleNamespace(name="MOUSE_SCROLL_DOWN"))
    assert monitor.detail_offset == 3
    monitor.on_key(SimpleNamespace(name="MOUSE_SCROLL_UP"))
    assert monitor.detail_offset == 0
    monitor.on_key("KEY_END")
    monitor.on_key("KEY_RIGHT")
    assert monitor.selected == 1
    assert monitor.detail_offset == 0

