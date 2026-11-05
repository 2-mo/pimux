"""Native macOS GPU identity and optional driver-counter regression fixtures."""
import json
import plistlib
import subprocess

import pytest
from rich.console import Console

import gpu


PROFILE = json.dumps({"SPDisplaysDataType": [{
    "_name": "kHW_AppleM1Item", "sppci_model": "Apple M1",
    "sppci_cores": "8", "spdisplays_vendor": "sppci_vendor_Apple",
    "spdisplays_ndrvs": [{"_name": "Color LCD"}],
}]})


def registry(value=27):
    return plistlib.dumps([{"PerformanceStatistics": {"Device Utilization %": value}}]).decode()


@pytest.fixture(autouse=True)
def macos(monkeypatch):
    monkeypatch.setattr(gpu.sys, "platform", "darwin")
    monkeypatch.setattr(gpu, "_mac_identity_cache", None)
    monkeypatch.setenv("PIMUX_LANGUAGE", "en")


def test_identity_has_actual_model_and_no_inferred_vram():
    card, = gpu.parse_macos_gpus(PROFILE)
    assert card.name == "Apple M1" and card.cores == 8 and card.unified_memory
    assert card.backend == "macos"
    assert all(getattr(card, field) is None for field in
               ("utilization", "memory_used", "memory_total", "memory_percent",
                "temperature", "power_draw", "power_limit"))
    assert gpu.parse_macos_gpus('{"SPDisplaysDataType": []}') == []


@pytest.mark.parametrize("output", ["", "{}", "null", '{"SPDisplaysDataType": {}}',
                                    '{"SPDisplaysDataType": [null]}',
                                    '{"SPDisplaysDataType": [{"_name":"display"}]}'])
def test_bad_identity_is_error_not_no_device(output):
    with pytest.raises(gpu.GPUReadError):
        gpu.parse_macos_gpus(output)


@pytest.mark.parametrize("value,expected", [(0, 0), (42.5, 42.5), (100, 100),
                                          (-1, None), (101, None), (True, None),
                                          ("35", None), (float("nan"), None),
                                          (float("inf"), None)])
def test_only_numeric_finite_percentage_is_used(value, expected):
    assert gpu.parse_apple_utilization(registry(value)) == expected


@pytest.mark.parametrize("output", ["", "<bad>", "not plist", "[]",
    plistlib.dumps([]), plistlib.dumps([{}, {}]), plistlib.dumps([{}]),
    plistlib.dumps([{"PerformanceStatistics": {"Renderer Utilization %": 25}}])])
def test_absent_malformed_or_ambiguous_counters_are_unknown(output):
    assert gpu.parse_apple_utilization(output) is None


def test_query_caches_only_identity_and_never_stale_load(monkeypatch):
    calls = []
    loads = iter([registry(40), registry(0), "", registry(20)])
    now = [0]
    monkeypatch.setattr(gpu.time, "monotonic", lambda: now[0])

    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert kwargs["check"] is False and kwargs["capture_output"]
        if args[0] == "/usr/sbin/system_profiler":
            assert args[1:] == ["SPDisplaysDataType", "-json"]
            assert kwargs["timeout"] == 3
            return subprocess.CompletedProcess(args, 0, PROFILE, "")
        assert args == ["/usr/sbin/ioreg", "-a", "-r", "-c", "AGXAccelerator", "-d", "1"]
        assert kwargs["timeout"] == 1
        return subprocess.CompletedProcess(args, 0, next(loads), "")

    monkeypatch.setattr(gpu.subprocess, "run", run)
    assert [gpu.query_gpus()[0].utilization for _ in range(3)] == [40, 0, None]
    assert sum(args[0].endswith("system_profiler") for args, _ in calls) == 1
    now[0] = 61
    assert gpu.query_gpus()[0].utilization == 20
    assert sum(args[0].endswith("system_profiler") for args, _ in calls) == 2


@pytest.mark.parametrize("error", [FileNotFoundError(), PermissionError(),
                                    subprocess.TimeoutExpired("native", 1)])
def test_identity_failure_and_counter_failure_are_different(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(gpu.subprocess, "run", fail)
    with pytest.raises(gpu.GPUReadError):
        gpu.query_gpus()
    monkeypatch.setattr(gpu, "_mac_identity_cache", (gpu.time.monotonic(), tuple(gpu.parse_macos_gpus(PROFILE))))
    card, = gpu.query_gpus()
    assert card.name == "Apple M1" and card.utilization is None


@pytest.mark.parametrize("profile", ['{"SPDisplaysDataType": []}', json.dumps({"SPDisplaysDataType": [
    {"sppci_model": "Apple M1", "spdisplays_vendor": "sppci_vendor_Apple"},
    {"sppci_model": "Apple M2", "spdisplays_vendor": "sppci_vendor_Apple"}]}),
    '{"SPDisplaysDataType": [{"sppci_model": "Intel Iris"}]}'])
def test_no_ambiguous_mapping_or_empty_machine_sampling(monkeypatch, profile):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, profile, "")
    monkeypatch.setattr(gpu.subprocess, "run", run)
    assert all(card.utilization is None for card in gpu.query_gpus())
    assert len(calls) == 1


def test_nonzero_native_command_results(monkeypatch):
    monkeypatch.setattr(gpu.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "error"))
    with pytest.raises(gpu.GPUReadError):
        gpu.query_gpus()
    monkeypatch.setattr(gpu, "_mac_identity_cache", (gpu.time.monotonic(), tuple(gpu.parse_macos_gpus(PROFILE))))
    assert gpu.query_gpus()[0].utilization is None


def test_macos_details_never_query_nvidia_or_claim_no_processes(monkeypatch):
    monkeypatch.setattr(gpu, "query_gpus", lambda: gpu.parse_macos_gpus(PROFILE))
    def fail(*args, **kwargs):
        pytest.fail("macOS must not query NVIDIA processes")
    monkeypatch.setattr(gpu.subprocess, "run", fail)
    monitor = gpu.Monitor()
    monitor.details = True
    monitor.refresh()
    details = "\n".join(line.plain for line in monitor._detail_lines())
    assert "Apple M1" in details and "GPU cores: 8" in details
    assert "processes: unavailable" in details
    assert "none" not in details and "GiB" not in details
    with pytest.raises(gpu.GPUReadError, match="Per-process"):
        gpu.query_processes(0)


@pytest.mark.parametrize("width,height", [(20, 5), (40, 12), (80, 24)])
@pytest.mark.parametrize("details", [False, True])
def test_native_card_visible_and_fits(width, height, details):
    monitor = gpu.Monitor()
    monitor.gpus = gpu.parse_macos_gpus(PROFILE)
    monitor.details = details
    console = Console(width=width)
    lines = console.render_lines(monitor.render(width, height), console.options, pad=False)
    assert len(lines) <= height
    text = "\n".join("".join(part.text for part in line) for line in lines)
    assert "Apple M1" in text
    assert "NVIDIA" not in text
