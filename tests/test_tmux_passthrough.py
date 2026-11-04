"""Check the CLI transport contract without requiring a live tmux server."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1]


@pytest.fixture
def native_command(tmp_path):
    bindir = tmp_path / "native tools 'literal'"
    bindir.mkdir()
    binary = bindir / "tmux"
    binary.write_text(f"#!{sys.executable}\n" + r'''
import json
import os
import signal
import sys
from pathlib import Path

if os.environ.get("PIMUX_TEST_WAIT") == "1":
    def stop(signum, frame):
        Path(os.environ["PIMUX_TEST_SIGNAL"]).write_text(str(signum))
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    Path(os.environ["PIMUX_TEST_PID"]).write_text(str(os.getpid()))
    while True:
        signal.pause()
else:
    Path(os.environ["PIMUX_TEST_ARGS"]).write_text(json.dumps(sys.argv[1:]))
    sys.stdout.buffer.write(b"\x00\xffpane\toutput\n" + sys.stdin.buffer.read())
    sys.stderr.buffer.write(b"\xfe native error\n")
    raise SystemExit(37)
''')
    binary.chmod(0o755)
    runtime = tmp_path / "runtime.conf"
    runtime.write_text(f"{binary}\npimux-test\n{binary}\n")
    env = {key: value for key, value in os.environ.items() if key not in ("TMUX", "TMUX_PANE")}
    env.update(PIMUX_RUNTIME_FILE=str(runtime),
               PIMUX_LANGUAGE_FILE=str(tmp_path / "language"),
               PIMUX_TEST_WAIT="0",
               PIMUX_TEST_ARGS=str(tmp_path / "args.json"),
               PIMUX_TEST_PID=str(tmp_path / "pid"),
               PIMUX_TEST_SIGNAL=str(tmp_path / "signal"))
    return env


@pytest.mark.parametrize("system", [False, True])
def test_tmux_passthrough_preserves_literal_arguments_and_byte_streams(native_command, system):
    env = native_command
    arguments = ["list-panes", "-a", "-F", "#{pane_id}\t#{pane_current_path}\n", "", "'中文'; $literal"]
    command = [str(SOURCE / "bin/pimux"), *(["--system"] if system else []), "tmux", *arguments]
    incoming = b"stdin\x00\xff\n"
    result = subprocess.run(command, env=env, input=incoming, capture_output=True)
    prefix = ["-L", "default"] if system else ["-L", "pimux-test", "-f", str(SOURCE / "config/tmux.conf")]
    assert json.loads(Path(env["PIMUX_TEST_ARGS"]).read_text()) == prefix + arguments
    assert result.stdout == b"\x00\xffpane\toutput\n" + incoming
    assert result.stderr == b"\xfe native error\n"
    assert result.returncode == 37


def test_cancelling_tmux_passthrough_reaches_the_native_process(native_command):
    env = {**native_command, "PIMUX_TEST_WAIT": "1"}
    pid_file = Path(env["PIMUX_TEST_PID"])
    signal_file = Path(env["PIMUX_TEST_SIGNAL"])
    process = subprocess.Popen([str(SOURCE / "bin/pimux"), "tmux", "wait-for", "ready"],
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    native_pid = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if pid_file.exists():
                pid_text = pid_file.read_text()
                if pid_text:
                    native_pid = int(pid_text)
                    break
            assert process.poll() is None
            time.sleep(.01)
        assert native_pid is not None, "native command never became ready"
        process.terminate()
        assert process.wait(timeout=5) == 0
        assert signal_file.read_text() == str(signal.SIGTERM)
    finally:
        # Also clean up an orphaned child when testing the old wrapper behavior.
        if native_pid is not None and native_pid != process.pid:
            try:
                os.kill(native_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        process.communicate(timeout=5)
