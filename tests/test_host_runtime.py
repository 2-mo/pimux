"""Platform primitives are tested through real files, locks and processes."""

import fcntl
import os
from pathlib import Path
import select
import signal
import shutil
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[1]
HELPER = SOURCE / "lib/host_runtime.py"


def helper(*args):
    return subprocess.run([sys.executable, str(HELPER), *map(str, args)],
                          capture_output=True, text=True, timeout=5)


def test_paths_resolve_missing_components_and_symlinks_without_gnu_tools(tmp_path):
    target = tmp_path / '项目 "quoted" $literal'
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    result = helper("realpath", link / "missing" / ".." / "new")
    assert result.returncode == 0, result.stderr
    assert result.stdout.rstrip("\n") == str(target / "new")
    file = target / "settings"
    file.write_text("one")
    before = helper("signature", file)
    file.write_text("two")
    after = helper("signature", file)
    assert before.returncode == after.returncode == 0
    assert before.stdout != after.stdout


def test_lock_remains_owned_by_parent_after_helper_exits(tmp_path):
    file = tmp_path / "lock"
    script = 'exec 9>"$3"; "$1" "$2" lock 9 || exit; printf "locked\\n"; IFS= read -r release'
    owner = subprocess.Popen(["/bin/bash", "-c", script, "test", sys.executable, str(HELPER), str(file)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([owner.stdout], [], [], 4)[0]
        assert owner.stdout.readline() == "locked\n", owner.stderr.read()
        with file.open("a") as contender:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            owner.communicate("release\n", timeout=3)
            assert owner.returncode == 0
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=3)


def test_timeout_preserves_result_and_kills_a_term_resistant_process():
    result = helper("timeout", "2", sys.executable, "-c", "print('literal output'); raise SystemExit(7)")
    assert result.returncode == 7 and result.stdout == "literal output\n"
    result = helper("timeout", "0.2", sys.executable, "-u", "-c",
                    "import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print(os.getpid()); time.sleep(30)")
    assert result.returncode == 124, result.stderr
    pid = int(result.stdout.strip())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_process_cwd_is_literal_and_reports_exit(tmp_path):
    directory = tmp_path / '目录 "quotes" $literal \\n\n\a^G'
    directory.mkdir()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=directory)
    try:
        result = helper("cwd", child.pid)
        assert result.returncode == 0, result.stderr
        assert result.stdout == str(directory.resolve()) + "\n"
    finally:
        child.terminate()
        child.wait(timeout=3)
    assert helper("cwd", child.pid).returncode != 0


@pytest.mark.parametrize('signum', [signal.SIGINT, signal.SIGTERM])
def test_timeout_cancellation_reaps_its_command(signum):
    wrapper = subprocess.Popen([sys.executable, str(HELPER), 'timeout', '30',
                                sys.executable, '-u', '-c',
                                'import os,time; print(os.getpid()); time.sleep(30)'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([wrapper.stdout], [], [], 4)[0]
        pid = int(wrapper.stdout.readline())
        wrapper.send_signal(signum)
        _, error = wrapper.communicate(timeout=4)
        assert wrapper.returncode == 128 + signum, error
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait(timeout=3)


def test_python_views_use_the_selected_launcher_with_no_ambient_bash(tmp_path, monkeypatch):
    import proxy_ui
    launcher = tmp_path / "launcher with spaces"
    launcher.write_text("#!/bin/sh\ncase \"$1\" in __proxy-read) printf 'inherit\\n\\n';; __proxy-save) cat > \"$PIMUX_TEST_INPUT\";; *) exit 9;; esac\n")
    launcher.chmod(0o755)
    monkeypatch.setenv("PIMUX_LAUNCHER", str(launcher))
    monkeypatch.setenv("PIMUX_TEST_INPUT", str(tmp_path / "input"))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert proxy_ui.backend("read") == "inherit\n\n"
    proxy_ui.backend("write", "on", "http://127.0.0.1:7890")
    assert (tmp_path / "input").read_text() == "http://127.0.0.1:7890\n"


@pytest.mark.parametrize('contents', [
    '# pimux-managed: Bash runtime\n\n',
    '# unrelated configuration\n/bin/bash\n',
    '# pimux-managed: Bash runtime\n/missing/bash\n',
    '# pimux-managed: Bash runtime\n/bin/bash\n\n',
])
def test_invalid_shell_pin_fails_before_startup_without_writes(tmp_path, contents):
    config = tmp_path / '.config/pimux'
    config.mkdir(parents=True)
    pin = config / 'shell.conf'
    pin.write_text(contents)
    env = {key: value for key, value in os.environ.items() if key not in ('PIMUX_BASH', 'PIMUX_SHELL_FILE')}
    env['HOME'] = str(tmp_path)
    result = subprocess.run([str(SOURCE / 'bin/pimux'), '--version'], env=env, capture_output=True, text=True)
    assert result.returncode == 1 and result.stderr
    assert list(config.iterdir()) == [pin] and pin.read_text() == contents


def test_bootstrap_preserves_existing_tool_precedence(tmp_path):
    tool = tmp_path / 'ss'
    tool.write_text('#!/bin/sh\nexit 7\n')
    tool.chmod(0o755)
    bash = shutil.which('bash')
    env = {**os.environ, 'PIMUX_BASH': bash, 'PATH': str(tmp_path) + ':' + os.environ['PATH']}
    result = subprocess.run([bash, '-c', 'source "$1"; type -P ss', 'test', str(SOURCE / 'bin/pimux')],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(tool) + '\n'


def test_launcher_resolves_relative_symlink_chain_and_rejects_a_loop(tmp_path):
    first = tmp_path / 'link with spaces'
    first.symlink_to(SOURCE / 'bin/pimux')
    second = tmp_path / 'second'
    second.symlink_to(first.name)
    result = subprocess.run([str(second), '--version'], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0 and result.stdout.startswith('pimux '), result.stderr
    first.unlink()
    first.symlink_to(second.name)
    # A symlink loop must fail promptly, including an explicit Bash invocation.
    result = subprocess.run(['bash', str(second), '--version'], capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
