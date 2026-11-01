"""Exercise personal config writes and real tmux session lifecycle in isolation."""

import os
import fcntl
import select
import shutil
import signal
import struct
import subprocess
import termios
import time
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1]


def install(home, function="install_files"):
    return subprocess.run(
        ["bash", "-c", 'source "$1"; "$2" "$3" "$4"', "test",
         str(SOURCE / "setup-tmux.sh"), function, str(home), str(SOURCE)],
        text=True, capture_output=True,
    )


def test_install_exposes_short_command_and_preserves_user_settings(tmp_path):
    home = tmp_path / 'personal "terminal" $dir'
    home.mkdir()
    dotfiles = {'.tmux.conf': '# personal tmux\n', '.bashrc': '# personal shell\n'}
    for name, value in dotfiles.items():
        (home / name).write_text(value)
    profile = home / 'personal-profile'
    profile.write_text('# personal login shell\n')
    (home / '.bash_profile').symlink_to(profile)
    (home / '.zshrc').write_text('# personal zsh\n')
    for _ in range(2):
        result = install(home)
        assert result.returncode == 0, result.stderr
        assert (home / '.tmux.conf').read_text() == dotfiles['.tmux.conf']
        assert (home / '.bashrc').read_text().startswith(dotfiles['.bashrc'])
        assert (home / '.bash_profile').is_symlink()
        assert profile.read_text().startswith('# personal login shell\n')
        # Simulate a new user's shell with no ~/.local/bin in its inherited PATH.
        for file in ('.bashrc', '.bash_profile', '.zshrc', '.zprofile'):
            result = subprocess.run(
                ['bash', '-c', 'source "$1"; source "$1"; command -v pimux; printf "%s" "$PATH"',
                 'test', str(home / file)],
                env={**os.environ, 'HOME': str(home), 'PATH': '/usr/bin:/bin'},
                text=True, capture_output=True, check=True,
            )
            command, path = result.stdout.split('\n')
            assert command == str(home / '.local/bin/pimux')
            assert path.split(':').count(str(home / '.local/bin')) == 1
    assert not (home / '.profile').exists()  # Bash already uses .bash_profile.
    assert len(list(home.glob('.bashrc.pimux-backup.*'))) == 1
    assert os.access(home / '.local/bin/pimux', os.X_OK)
    config = home / '.config/pimux'
    for file in ('tmux.conf', 'bashrc', 'shell.bash', 'starship.toml', 'gpu.bash', 'gpu.py', 'gpu_ui.py', 'proxy.bash'):
        assert (config / file).is_file()
    theme = config / 'tmux.conf'
    theme.write_text('# pimux-managed: previous theme\n')
    result = install(home)
    assert result.returncode == 0, result.stderr
    backups = list(config.glob('tmux.conf.pimux-backup.*'))
    assert len(backups) == 1
    assert backups[0].read_text() == '# pimux-managed: previous theme\n'


def test_install_refuses_unrelated_launcher_and_keeps_symlink(tmp_path):
    config = tmp_path / 'personal.conf'
    config.write_text('# existing dotfiles\n')
    main = tmp_path / '.tmux.conf'
    main.symlink_to(config)
    bindir = tmp_path / '.local/bin'
    bindir.mkdir(parents=True)
    launcher = bindir / 'pimux'
    launcher.write_text('# unrelated user tool\n')
    result = install(tmp_path)
    assert result.returncode != 0
    assert launcher.read_text() == '# unrelated user tool\n'
    assert main.is_symlink()
    assert config.read_text() == '# existing dotfiles\n'


def test_installed_gpu_dashboard_uses_its_own_runtime(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    unrelated = tmp_path / 'research-environment'
    unrelated.mkdir()
    marker = unrelated / 'keep.txt'
    marker.write_text('existing research environment')
    monkeypatch.setenv('VIRTUAL_ENV', str(unrelated))
    assert install(home).returncode == 0
    result = install(home, 'install_gpu_runtime')
    assert result.returncode == 0, result.stderr
    assert marker.read_text() == 'existing research environment'
    assert list(unrelated.iterdir()) == [marker]
    runtime = home / '.local/share/pimux/venv/bin/python'
    assert runtime.is_file()
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    smi = bindir / 'nvidia-smi'
    smi.write_text('#!/bin/sh\necho "0, Installed GPU, 50, 1024, 8192, 50, 100, 250"\n')
    smi.chmod(0o755)
    env = dict(os.environ, HOME=str(home), PATH=f'{bindir}:{os.environ["PATH"]}')
    result = subprocess.run([str(home / '.local/bin/pimux'), '__gpu'], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'GPU 0' in result.stdout and '50.0%' in result.stdout
    result = subprocess.run([str(runtime), '-c',
                             'import importlib.util; import rich, blessed; '
                             'assert importlib.util.find_spec("pytest") is None'],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_shell_initializes_starship_when_only_environment_was_inherited(tmp_path):
    if not shutil.which('starship'):
        pytest.skip('requires starship')
    env = dict(os.environ, STARSHIP_SHELL='bash')
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    env['PIMUX_PROXY_FILE'] = str(tmp_path / 'proxy')
    script = '''set -e
source "$1"
declare -F starship_precmd >/dev/null
before=$PROMPT_COMMAND
source "$1"
[[ $PROMPT_COMMAND == "$before" ]]
[[ $STARSHIP_CONFIG == "$HOME/.config/pimux/starship.toml" ]]
'''
    result = subprocess.run(['bash', '--noprofile', '--norc', '-ic', script,
                             'test', str(SOURCE / 'bashrc')], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def server(tmp_path):
    if not shutil.which("tmux"):
        pytest.skip("requires tmux")
    socket_dir = tmp_path / "sockets"
    socket_dir.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in {"TMUX", "TMUX_PANE"}}
    env["TMUX_TMPDIR"] = str(socket_dir)
    env["TERM"] = "xterm-256color"
    env["PIMUX_RUNTIME_FILE"] = str(tmp_path / "runtime.conf")
    Path(env["PIMUX_RUNTIME_FILE"]).write_text(f"{shutil.which('tmux')}\ndefault\n{shutil.which('tmux')}\n")
    env["PIMUX_LANGUAGE_FILE"] = str(tmp_path / "language")
    env['PIMUX_PINS_FILE'] = str(tmp_path / 'pinned-sessions')
    env['PIMUX_PROXY_FILE'] = str(tmp_path / 'proxy')
    Path(env["PIMUX_LANGUAGE_FILE"]).write_text("zh\n")

    def tmux(*args):
        return subprocess.run(["tmux", *args], env=env, capture_output=True,
                              text=True, check=True).stdout.strip()

    tmux("-f", "/dev/null", "new-session", "-d", "-s", "seed", "-c", str(tmp_path))
    try:
        yield env, tmux
    finally:
        # Only this fixture's socket is addressed; never touch the user's server.
        subprocess.run(["tmux", "kill-server"], env=env, capture_output=True)


def test_installed_config_loads_and_reload_does_not_duplicate_features(tmp_path, server):
    _, tmux = server
    home = tmp_path / 'home "$literal"'
    home.mkdir()
    result = install(home)
    assert result.returncode == 0, result.stderr
    conf = str(home / ".config/pimux/tmux.conf")
    tmux("source-file", conf)
    first = tmux("show-options", "-s", "terminal-features")
    tmux("source-file", conf)
    assert tmux("show-options", "-s", "terminal-features") == first
    # tmux accepts syntactically invalid nested formats; also evaluate the footer.
    footer = tmux("show-options", "-gqv", "status-format[1]")
    assert tmux("display-message", "-p", "-t", "=seed:", footer)
    # Loading a personal theme must preserve existing sessions and panes.
    assert tmux("list-sessions", "-F", "#{session_name}") == "seed"
    assert tmux("list-panes", "-t", "=seed", "-F", "#{pane_dead}") == "0"


def test_concurrent_create_exact_name_and_preserve_existing_window(tmp_path, server):
    env, tmux = server
    cwd = tmp_path / "project 'quoted'; literal"
    cwd.mkdir()
    # Leave attachment out of this lifecycle regression, retaining real tmux calls.
    call = '''source "$1"
require_terminal() { :; }
tmux() {
    if [[ $1 == attach-session ]]; then return; fi
    command tmux "$@"
}
ensure_session "$2"
'''
    args = ["bash", "-c", call, "test", str(SOURCE / "pimux"), "agents"]
    calls = [subprocess.Popen(args, cwd=cwd, env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for _ in range(4)]
    for process in calls:
        output, error = process.communicate(timeout=10)
        assert process.returncode == 0, output + error
    assert tmux("list-sessions", "-F", "#{session_name}").splitlines().count("agents") == 1
    assert tmux("display-message", "-p", "-t", "=agents:", "#{pane_current_path}") == str(cwd)
    tmux("new-window", "-t", "=agents:", "-n", "review", "-c", str(cwd))
    window = tmux("display-message", "-p", "-t", "=agents:", "#{window_id}")
    subprocess.run(args, env=env, cwd=tmp_path, check=True)
    assert tmux("display-message", "-p", "-t", "=agents:", "#{window_id}") == window
    # Prefix matches must not cause attachment to a different session.
    subprocess.run([*args[:-1], "agent"], env=env, cwd=tmp_path, check=True)
    assert tmux("display-message", "-p", "-t", "=agent:", "#{session_name}") == "agent"


def test_noninteractive_entry_is_read_only(server):
    env, tmux = server
    result = subprocess.run([str(SOURCE / "pimux"), "-n", "new-project"], env=env,
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert tmux("list-sessions", "-F", "#{session_name}") == "seed"


@pytest.mark.parametrize("close_original", [False, True])
def test_independent_view_shares_programs_and_preserves_last_reference(tmp_path, server, close_original):
    env, tmux = server
    tmux("source-file", str(SOURCE / "pimux.conf"))
    tmux("set-option", "-g", "@pimux_launcher", str(SOURCE / "pimux"))
    original = tmux("display-message", "-p", "-t", "=seed:", "#{window_id}")
    original_pane = tmux("list-panes", "-t", "=seed:", "-F", "#{pane_id} #{pane_pid}")
    # The path fits beside the compact actions on a wide terminal.
    cwd = tmp_path / ("project-" + "a" * max(1, 91 - len(str(tmp_path)))) / "leaf"
    cwd.mkdir(parents=True)
    second = tmux("new-window", "-d", "-t", "=seed:", "-n", "review", "-c", str(cwd), "-P", "-F", "#{window_id}")
    clients = []
    output = bytearray()

    def start(*args):
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 160, 0, 0))
        process = subprocess.Popen([str(SOURCE / "pimux"), *args], env=env,
                                   stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        clients.append((process, master, slave))
        return process, master

    def wait_for(condition):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            for fd in select.select([item[1] for item in clients], [], [], 0.05)[0]:
                output.extend(os.read(fd, 65536))
        pytest.fail(output.decode(errors="replace")[-1500:])

    try:
        first_client, first_tty = start("-n", "seed")
        wait_for(lambda: bool(tmux("list-clients", "-F", "#{session_id}")))
        first_view = tmux("list-clients", "-F", "#{session_id}")
        view_client, view_tty = start("-n", "seed")
        wait_for(lambda: len(tmux("list-clients", "-F", "#{session_id}").splitlines()) == 2)
        view = next(line.split()[0] for line in tmux(
            "list-sessions", "-F", "#{session_id} #{@pimux_view}"
        ).splitlines() if line.endswith(" seed") and line.split()[0] != first_view)
        tmux("select-window", "-t", f"{view}:{second}")
        assert tmux("display-message", "-p", "-t", "=seed:", "#{window_id}") == original
        assert tmux("display-message", "-p", "-t", f"{view}:", "#{window_id}") == second
        assert "review" in tmux("list-clients", "-t", view, "-F", "#{E:status-format[0]}")
        rendered = tmux("list-clients", "-t", view, "-F", "#{E:status-format[1]}")
        assert str(cwd) in rendered
        fcntl.ioctl(clients[-1][2], termios.TIOCSWINSZ, struct.pack("HHHH", 30, 80, 0, 0))
        os.killpg(view_client.pid, signal.SIGWINCH)
        wait_for(lambda: tmux("list-clients", "-t", view, "-F", "#{client_width}") == "80")
        narrow = tmux("list-clients", "-t", view, "-F", "#{E:status-format[1]}")
        assert "…" in narrow and "/leaf" in narrow
        os.write(view_tty, b'\x01')
        wait_for(lambda: tmux('list-clients', '-t', view, '-F', '#{client_prefix}') == '1')
        assert tmux('list-clients', '-t', view, '-F', '#{E:status-format[1]}') != narrow
        assert tmux('list-clients', '-t', first_view, '-F', '#{client_prefix}') == '0'
        os.write(view_tty, b'\x1b')
        wait_for(lambda: tmux('list-clients', '-t', view, '-F', '#{client_prefix}') == '0')
        assert tmux('list-clients', '-t', view, '-F', '#{E:status-format[1]}') == narrow
        listing = subprocess.check_output([str(SOURCE / "pimux"), "ls"], env=env, text=True)
        assert len(listing.splitlines()) == 2 and "~view-" not in listing
        caller_env = {**env, "TMUX_PANE": original_pane.split()[0]}
        caller = subprocess.run(["bash", "-c", 'source "$1"; current_client', "test", str(SOURCE / "pimux")],
                                env=caller_env, capture_output=True, text=True)
        assert caller.returncode == 0
        assert caller.stdout.strip() == tmux("list-clients", "-t", first_view, "-F", "#{client_name}")
        tmux("select-window", "-t", f"{view}:{original}")
        ambiguous = subprocess.run(["bash", "-c", 'source "$1"; current_client', "test", str(SOURCE / "pimux")],
                                   env=caller_env, capture_output=True, text=True)
        assert ambiguous.returncode != 0
        tmux("select-window", "-t", f"{view}:{second}")

        # Entering another session through the menu must keep this client's view
        # independent; opening the manager must not put a shared pane into a mode.
        tmux("new-session", "-d", "-s", "target")
        client_name = tmux("list-clients", "-t", view, "-F", "#{client_name}")
        output.clear()
        os.write(view_tty, b"\x01h")
        wait_for(lambda: "pimux · 工作终端".encode() in output)
        os.write(view_tty, b"s")
        wait_for(lambda: "pimux · 会话管理".encode() in output)
        assert not tmux("display-message", "-p", "-t", f"{first_view}:", "#{pane_mode}")
        os.write(view_tty, b"\x1b[B\r")
        wait_for(lambda: "target" in tmux("list-clients", "-F", "#{@pimux_view}"))
        assert tmux("display-message", "-p", "-t", f"{first_view}:", "#{window_id}") == original
        wait_for(lambda: "__manager" not in tmux("show-messages", "-J"))
        os.write(view_tty, b"\x01L")
        wait_for(lambda: tmux("list-clients", "-F", "#{@pimux_view}").splitlines() == ["seed", "seed"])
        view = next(line.split()[1] for line in tmux(
            "list-clients", "-F", "#{client_name} #{session_id}"
        ).splitlines() if line.split()[0] == client_name)
        tmux("kill-session", "-t", "=target")
        tmux("rename-window", "-t", f"{view}:{second}", "shared")
        assert tmux("display-message", "-p", "-t", f"=seed:{second}", "#{window_name}") == "shared"
        tmux("kill-window", "-t", f"{view}:{second}")
        assert tmux("list-windows", "-t", "=seed", "-F", "#{window_id}") == original
        assert tmux("list-windows", "-t", view, "-F", "#{window_id}") == original

        os.write(first_tty, b"\x01d")
        wait_for(lambda: first_client.poll() is not None)
        if close_original:
            tmux("kill-session", "-t", "=seed")
        os.write(view_tty, b"\x01d")
        wait_for(lambda: view_client.poll() is not None)
        assert first_client.returncode == view_client.returncode == 0
        # With the original gone, leaving the final view must still keep its shell.
        remaining = view if close_original else "=seed"
        assert tmux("list-panes", "-t", remaining, "-F", "#{pane_id} #{pane_pid}") == original_pane
        assert len(tmux("list-sessions", "-F", "#{session_id}").splitlines()) == 1
    finally:
        for process, master, slave in clients:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            os.close(master)
            os.close(slave)


def test_runtime_routes_new_and_system_servers_separately(server):
    env, tmux = server
    runtime = Path(env["PIMUX_RUNTIME_FILE"])
    runtime.write_text(f"{shutil.which('tmux')}\npimux-3.8\n{shutil.which('tmux')}\n")
    tmux("-L", "pimux-3.8", "-f", "/dev/null", "new-session", "-d", "-s", "fresh")
    try:
        # A read-only command from an old pane must still address the selected server.
        env["TMUX"] = tmux("display-message", "-p", "#{socket_path},#{pid},0")
        env["TMUX_PANE"] = "%9999"
        fresh = subprocess.run([str(SOURCE / "pimux"), "ls"], env=env,
                               text=True, capture_output=True, check=True)
        old = subprocess.run([str(SOURCE / "pimux"), "--system", "ls"], env=env,
                             text=True, capture_output=True, check=True)
        assert "fresh" in fresh.stdout and "seed" not in fresh.stdout
        assert "seed" in old.stdout and "fresh" not in old.stdout
        diagnostics = subprocess.run([str(SOURCE / "pimux"), "doctor"], env=env,
                                     text=True, capture_output=True, check=True)
        pid = tmux("-L", "pimux-3.8", "display-message", "-p", "#{pid}")
        assert f"PID {pid}" in diagnostics.stdout
        # Theme updates must reach pimux on both servers, leaving other sessions alone.
        tmux("new-session", "-d", "-s", "personal")
        tmux("set-option", "-t", "personal", "status-right", "personal status")
        for options, session in (([], "seed"), (["-L", "pimux-3.8"], "fresh")):
            tmux(*options, "set-option", "-t", session, "@pimux_launcher", str(SOURCE / "pimux"))
            tmux(*options, "set-option", "-t", session, "status-right", "")
        before = tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}")
        subprocess.run(
            ["bash", "-c", 'source "$1"; configure_runtime; refresh_session_themes',
             "test", str(SOURCE / "pimux")], env=env, check=True, capture_output=True,
        )
        for options, session in (([], "seed"), (["-L", "pimux-3.8"], "fresh")):
            assert "__gpu-status" in tmux(*options, "show-options", "-qv", "-t", session, "status-right")
        assert tmux("show-options", "-qv", "-t", "personal", "status-right") == "personal status"
        assert tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}") == before
    finally:
        tmux("-L", "pimux-3.8", "kill-server")


def test_shared_server_reload_and_short_command_preserve_other_sessions(server):
    env, tmux = server
    Path(env['PIMUX_RUNTIME_FILE']).write_text(
        f"{shutil.which('tmux')}\npimux\n{shutil.which('tmux')}\n"
    )
    tmux('new-session', '-d', '-s', 'personal')
    tmux('set-option', '-t', 'seed', '@pimux_launcher', str(SOURCE / 'pimux'))
    tmux('bind-key', '-r', 'g', 'set-option', '@original_gpu_key', 'used')
    tmux('unbind-key', 'h')
    global_before = tmux('show-options', '-g')
    personal_before = tmux('show-options', '-t', 'personal')
    panes_before = tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}')
    env['TMUX'] = tmux('display-message', '-p', '-t', 'seed', '#{socket_path},#{pid},0')
    env['TMUX_PANE'] = tmux('display-message', '-p', '-t', 'seed', '#{pane_id}')
    # No --system is needed inside a managed workspace on the older server.
    listing = subprocess.run([str(SOURCE / 'pimux'), 'ls'], env=env,
                             capture_output=True, text=True, check=True)
    assert 'seed' in listing.stdout and 'personal' in listing.stdout
    for _ in range(2):
        subprocess.run([str(SOURCE / 'pimux'), 'reload'], env=env,
                       capture_output=True, text=True, check=True)
        assert tmux('show-options', '-gqv', '@pimux_fallback_gpu') == 'set-option @original_gpu_key used'
        assert tmux('show-options', '-gqv', '@pimux_fallback_menu') == ''
    globals_after = '\n'.join(line for line in tmux('show-options', '-g').splitlines()
                              if not line.startswith('@pimux_fallback_'))
    assert globals_after == global_before
    assert tmux('show-options', '-t', 'personal') == personal_before
    assert tmux('show-options', '-qv', '-t', 'seed', 'prefix') == 'C-a'
    assert tmux('show-options', '-qv', '-t', 'seed', 'mouse') == 'on'
    assert tmux('show-options', '-Aqv', '-t', 'personal', 'mouse') == 'off'
    assert tmux('show-options', '-qv', '-t', 'seed', 'status-interval') == '5'
    assert tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}') == panes_before

    # The same physical keys retain their original behavior in an ordinary session.
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 140, 0, 0))
    client_env = {key: value for key, value in env.items() if key not in ('TMUX', 'TMUX_PANE')}
    client = subprocess.Popen(['tmux', 'attach-session', '-t', 'personal'], env=client_env,
                              stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    try:
        output = bytearray()

        def drain():
            if select.select([master], [], [], .05)[0]:
                output.extend(os.read(master, 65536))

        deadline = time.monotonic() + 5
        while b'personal' not in output and time.monotonic() < deadline:
            drain()
        assert b'personal' in output, output
        os.write(master, b'\x02')
        deadline = time.monotonic() + 5
        while tmux('list-clients', '-F', '#{client_prefix}') != '1' and time.monotonic() < deadline:
            drain()
        assert tmux('list-clients', '-F', '#{client_prefix}') == '1'
        os.write(master, b'g')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if tmux('show-options', '-qv', '-t', 'personal', '@original_gpu_key') == 'used':
                break
            drain()
        assert tmux('show-options', '-qv', '-t', 'personal', '@original_gpu_key') == 'used', (
            tmux('show-options', '-Aqv', '-t', 'personal', 'prefix'),
            tmux('list-clients', '-F', '#{session_name} #{client_key_table} #{client_prefix}'),
            tmux('list-keys', '-T', 'prefix', 'g'),
            tmux('list-sessions', '-F', '#{session_name}:#{@original_gpu_key}'),
        )
    finally:
        client.terminate()
        client.wait(timeout=5)
        os.close(master)
        os.close(slave)


def test_cross_server_entry_refuses_before_creating_session(server):
    env, tmux = server
    Path(env["PIMUX_RUNTIME_FILE"]).write_text(
        f"{shutil.which('tmux')}\npimux-3.8\n{shutil.which('tmux')}\n"
    )
    env["TMUX"] = tmux("display-message", "-p", "#{socket_path},#{pid},0")
    env["TMUX_PANE"] = "%0"
    master, slave = os.openpty()
    try:
        result = subprocess.run([str(SOURCE / "pimux"), "-n", "agents"], env=env,
                                stdin=slave, stdout=slave, stderr=subprocess.PIPE,
                                text=True, timeout=5)
        assert result.returncode != 0
        assert "Ctrl-a d" in result.stderr
        assert tmux("list-sessions", "-F", "#{session_name}") == "seed"
        untouched = subprocess.run(["tmux", "-L", "pimux-3.8", "list-sessions"],
                                   env=env, capture_output=True)
        assert untouched.returncode != 0
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize("has_other_session", [True, False])
def test_manager_can_close_its_own_session(server, has_other_session):
    env, tmux = server
    tmux("source-file", str(SOURCE / "pimux.conf"))
    tmux("set-option", "-g", "@pimux_launcher", str(SOURCE / "pimux"))
    kept_pane = tmux("list-panes", "-t", "=seed:", "-F", "#{pane_id} #{pane_pid}")
    tmux("new-session", "-d", "-s", "self")
    if not has_other_session:
        tmux("kill-session", "-t", "=seed")
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    client = subprocess.Popen([str(SOURCE / "pimux"), "-n", "self"], env=env, stdin=slave,
                              stdout=slave, stderr=slave, start_new_session=True)
    peer_master, peer_slave = os.openpty()
    fcntl.ioctl(peer_slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    peer = subprocess.Popen([str(SOURCE / "pimux"), "-n", "self"], env=env, stdin=peer_slave,
                            stdout=peer_slave, stderr=peer_slave, start_new_session=True)
    output = bytearray()

    def wait_for(condition):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            for fd in select.select([master, peer_master], [], [], 0.05)[0]:
                data = os.read(fd, 65536)
                if fd == master:
                    output.extend(data)
        pytest.fail(output.decode(errors="replace")[-2000:])

    try:
        wait_for(lambda: len(tmux("list-clients", "-F", "#{session_name}").splitlines()) == 2)
        os.write(master, b"\x01s")
        wait_for(lambda: "pimux · 会话管理".encode() in output)
        os.write(master, b"x")
        prompt = "关闭会话 self".encode()
        wait_for(lambda: prompt in output)
        os.write(master, b"n")
        tmux("has-session", "-t", "=self")
        output.clear()
        os.write(master, b"x")
        wait_for(lambda: prompt in output)
        os.write(master, b"y")
        wait_for(lambda: client.poll() is not None)
        assert client.returncode == 0, output.decode(errors="replace")[-1000:]
        wait_for(lambda: peer.poll() is not None)
        assert peer.returncode == 0
        if has_other_session:
            assert tmux("list-sessions", "-F", "#{session_name}") == "seed"
            assert tmux("list-panes", "-t", "=seed:", "-F", "#{pane_id} #{pane_pid}") == kept_pane
    finally:
        if client.poll() is None:
            client.terminate()
            client.wait(timeout=5)
        os.close(master)
        os.close(slave)
        if peer.poll() is None:
            peer.terminate()
            peer.wait(timeout=5)
        os.close(peer_master)
        os.close(peer_slave)


@pytest.mark.parametrize('use_suggested_name', [False, True])
def test_empty_manager_creates_only_on_request_and_help_is_read_only(tmp_path, server, use_suggested_name):
    env, tmux = server
    project = tmp_path / 'experiment.v2'
    project.mkdir()
    expected = 'experiment-v2' if use_suggested_name else 'ls'
    tmux("kill-server")
    for args in (["-h"], ["ls"]):
        result = subprocess.run([str(SOURCE / "pimux"), *args], env=env, text=True, capture_output=True)
        assert result.returncode == 0
    unknown = subprocess.run([str(SOURCE / "pimux"), "arbitrary-name"], env=env, capture_output=True)
    assert unknown.returncode == 2
    assert subprocess.run(["tmux", "list-sessions"], env=env, capture_output=True).returncode != 0
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    client = subprocess.Popen([str(SOURCE / "pimux")], env=env, stdin=slave,
                              stdout=slave, stderr=slave, start_new_session=True, cwd=project)
    output = bytearray()

    def wait_for(text):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if text.encode() in output:
                return
            if select.select([master], [], [], 0.05)[0]:
                output.extend(os.read(master, 65536))
        pytest.fail(output.decode(errors="replace")[-1500:])

    try:
        wait_for("暂无会话")
        assert subprocess.run(["tmux", "list-sessions"], env=env, capture_output=True).returncode != 0
        os.write(master, b"n")
        wait_for("会话名称")
        output.clear()
        os.write(master, b"\x15\r")
        wait_for("暂无会话")
        assert subprocess.run(["tmux", "list-sessions"], env=env, capture_output=True).returncode != 0
        os.write(master, b"n")
        wait_for("会话名称")
        os.write(master, b"\x15bad.name\r")
        wait_for("不能")
        assert subprocess.run(["tmux", "list-sessions"], env=env, capture_output=True).returncode != 0
        output.clear()
        os.write(master, b"n")
        wait_for("会话名称")
        os.write(master, b"\r" if use_suggested_name else b"\x15ls\r")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = subprocess.run(["tmux", "list-clients", "-F", "#{@pimux_view}"],
                                    env=env, capture_output=True, text=True)
            if result.stdout.strip() == expected:
                break
            time.sleep(0.05)
        else:
            pytest.fail(output.decode(errors="replace")[-1500:])
        os.write(master, b"\x01d")
        assert client.wait(timeout=8) == 0
        assert tmux("list-sessions", "-F", "#{session_name}") == expected
        assert tmux('display-message', '-p', '-t', f'={expected}:', '#{pane_current_path}') == str(project)
        listing = subprocess.check_output([str(SOURCE / "pimux"), "ls"], env=env, text=True)
        assert f"{expected}  " in listing and "~view-" not in listing
    finally:
        if client.poll() is None:
            client.terminate()
            client.wait(timeout=5)
        os.close(master)
        os.close(slave)


def test_language_menu_persists_and_syncs_only_pimux_across_servers(server):
    env, tmux = server
    preference = Path(env["PIMUX_LANGUAGE_FILE"])
    preference.unlink()
    Path(env["PIMUX_RUNTIME_FILE"]).write_text(f"{shutil.which('tmux')}\nparallel\n{shutil.which('tmux')}\n")
    tmux("source-file", str(SOURCE / "pimux.conf"))
    tmux("new-session", "-d", "-s", "untouched")
    untouched = tmux("display-message", "-p", "-t", "=untouched:", "#{session_id}")
    tmux("set-option", "-t", untouched, "@pimux_launcher", "")
    original_options = tmux("show-options", "-t", untouched)
    tmux("-L", "parallel", "-f", "/dev/null", "new-session", "-d", "-s", "fresh")
    tmux("-L", "parallel", "source-file", str(SOURCE / "pimux.conf"))
    before = {socket: tmux("-L", socket, "list-panes", "-a", "-F", "#{pane_id} #{pane_pid}")
              for socket in ["default", "parallel"]}
    clients = []
    outputs = {}

    def start(*args):
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        process = subprocess.Popen([str(SOURCE / "pimux"), *args], env=env, stdin=slave,
                                   stdout=slave, stderr=slave, start_new_session=True)
        clients.append((process, master, slave))
        outputs[master] = bytearray()
        return process, master

    def wait_for(condition):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            for fd in select.select(list(outputs), [], [], 0.05)[0]:
                outputs[fd].extend(os.read(fd, 65536))
        pytest.fail("\n".join(data.decode(errors="replace")[-1200:] for data in outputs.values()))

    def change_language(tty, key, title):
        outputs[tty].clear()
        os.write(tty, b"\x01h")
        wait_for(lambda: title.encode() in outputs[tty])
        outputs[tty].clear()
        os.write(tty, b"l")
        wait_for(lambda: b"English" in outputs[tty] and "简体中文".encode() in outputs[tty])
        outputs[tty].clear()
        os.write(tty, key)

    try:
        help_text = subprocess.check_output([str(SOURCE / "pimux"), "-h"], env=env, text=True)
        assert "Personal terminal" in help_text and not preference.exists()
        first, first_tty = start("--system", "-n", "seed")
        second, second_tty = start("-n", "fresh")
        wait_for(lambda: bool(tmux("list-clients", "-F", "#{session_id}")) and
                        bool(tmux("-L", "parallel", "list-clients", "-F", "#{session_id}")))
        assert "detach" in tmux("list-clients", "-F", "#{E:status-format[1]}")
        change_language(first_tty, b"z", "Work terminal")
        wait_for(lambda: preference.exists() and preference.read_text() == "zh\n" and
                        tmux("-L", "parallel", "list-clients", "-F", "#{@pimux_language}") == "zh")
        wait_for(lambda: "工作终端".encode() in outputs[first_tty])
        assert "离开" in tmux("list-clients", "-F", "#{E:status-format[1]}")
        assert tmux("show-options", "-t", untouched) == original_options
        for socket in ["default", "parallel"]:
            # Extra views link the same panes; all original programs must remain.
            assert set(before[socket].splitlines()) == set(tmux(
                "-L", socket, "list-panes", "-a", "-F", "#{pane_id} #{pane_pid}"
            ).splitlines())
        assert "个人工作终端" in subprocess.check_output([str(SOURCE / "pimux"), "-h"], env=env, text=True)
        os.write(first_tty, b"\x1b")
        wait_for(lambda: "__client" not in tmux("show-messages", "-J"))
        os.write(first_tty, b"\x01/")
        wait_for(lambda: "新建 shell".encode() in outputs[first_tty])
        os.write(first_tty, b"q")
        wait_for(lambda: not tmux("list-clients", "-F", "#{pane_mode}"))
        for process, tty in [(first, first_tty), (second, second_tty)]:
            os.write(tty, b"\x01d")
            wait_for(lambda: process.poll() is not None)
            assert process.returncode == 0
        # A restarted server must use the saved language on the next connection.
        server_pid = tmux("-L", "parallel", "display-message", "-p", "#{pid}")
        tmux("-L", "parallel", "kill-server")
        def server_stopped():
            state = subprocess.run(["ps", "-p", server_pid, "-o", "stat="],
                                   text=True, capture_output=True).stdout.strip()
            return not state or state.startswith("Z")
        wait_for(server_stopped)
        tmux("-L", "parallel", "-f", "/dev/null", "new-session", "-d", "-s", "fresh")
        tmux("-L", "parallel", "source-file", str(SOURCE / "pimux.conf"))
        third, third_tty = start("-n", "fresh")
        wait_for(lambda: bool(tmux("-L", "parallel", "list-clients", "-F", "#{session_id}")))
        assert tmux("-L", "parallel", "list-clients", "-F", "#{@pimux_language}") == "zh"
        change_language(third_tty, b"e", "工作终端")
        wait_for(lambda: preference.read_text() == "en\n" and
                        tmux("show-options", "-Aqv", "-t", "=seed:", "@pimux_language") == "en")
        wait_for(lambda: b"Work terminal" in outputs[third_tty])
        os.write(third_tty, b"\x1b")
        wait_for(lambda: "__client" not in tmux("-L", "parallel", "show-messages", "-J"))
        outputs[third_tty].clear()
        os.write(third_tty, b"\x01/")
        wait_for(lambda: b"New shell window" in outputs[third_tty])
        os.write(third_tty, b"q")
        wait_for(lambda: not tmux("-L", "parallel", "list-clients", "-F", "#{pane_mode}"))
        outputs[third_tty].clear()
        os.write(third_tty, b"\x01h")
        wait_for(lambda: b"Work terminal" in outputs[third_tty])
        os.write(third_tty, b"s")
        wait_for(lambda: b"Session manager" in outputs[third_tty])
        os.write(third_tty, b"x")
        wait_for(lambda: b"Close session fresh and ALL its windows" in outputs[third_tty])
        os.write(third_tty, b"nq")
        wait_for(lambda: "__manager" not in tmux("-L", "parallel", "show-messages", "-J"))
        tmux("-L", "parallel", "has-session", "-t", "=fresh")
        assert tmux("show-options", "-t", untouched) == original_options
    finally:
        for process, master, slave in clients:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            os.close(master)
            os.close(slave)
        subprocess.run(["tmux", "-L", "parallel", "kill-server"], env=env, capture_output=True)


def test_default_runtime_isolates_system_server(tmp_path, server):
    env, tmux = server
    env = {**env, 'PIMUX_RUNTIME_FILE': str(tmp_path / 'absent-runtime')}
    before = tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}')
    before_theme = tmux('show-options', '-gqv', 'status-right')
    try:
        subprocess.run(
            ['bash', '-c', 'source "$1"; configure_runtime; tmux new-session -d -s isolated',
             'test', str(SOURCE / 'pimux')], env=env, check=True, capture_output=True,
        )
        assert tmux('-L', 'pimux', 'list-sessions', '-F', '#{session_name}') == 'isolated'
        assert tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}') == before
        assert tmux('show-options', '-gqv', 'status-right') == before_theme
    finally:
        subprocess.run(['tmux', '-L', 'pimux', 'kill-server'], env=env, capture_output=True)


def test_search_gpu_popup_and_reload_preserve_running_panes(tmp_path, server):
    env, tmux = server
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    smi = bindir / 'nvidia-smi'
    smi.write_text('#!/bin/sh\ncase "$1" in --query-gpu=index,name,*) echo "0, GPU-MOCK, 50, 4096, 8192, 50, 100, 250";; -i) echo "1234, demo-process, 4096";; *) echo "0, 50, 4096";; esac\n')
    smi.chmod(0o755)
    env['PATH'] = f'{bindir}:{env["PATH"]}'
    tmux('set-environment', '-g', 'PATH', env['PATH'])
    tmux('set-environment', '-g', 'PIMUX_RUNTIME_FILE', env['PIMUX_RUNTIME_FILE'])
    tmux('set-environment', '-g', 'PIMUX_LANGUAGE_FILE', env['PIMUX_LANGUAGE_FILE'])
    tmux('source-file', str(SOURCE / 'pimux.conf'))
    tmux('set-option', '-g', '@pimux_launcher', str(SOURCE / 'pimux'))
    # Literal brackets must not become a pattern; hidden windows are searchable.
    wanted = tmux('new-window', '-d', '-t', 'seed', '-n', 'Train[Fast]', '-P', '-F', '#{window_id}', 'sleep 60')
    before = tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}')
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 140, 0, 0))
    client = subprocess.Popen([str(SOURCE / 'pimux'), '-n', 'seed'], env=env,
                              stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()

    def wait_for(condition):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            if select.select([master], [], [], .05)[0]:
                output.extend(os.read(master, 65536))
        pytest.fail(output.decode(errors='replace')[-2000:])

    try:
        wait_for(lambda: bool(tmux('list-clients', '-F', '#{session_id}')))
        view = tmux('list-clients', '-F', '#{session_id}')
        os.write(master, b'\x01s')
        wait_for(lambda: '会话管理'.encode() in output)
        os.write(master, b'/missing-query')
        wait_for(lambda: '没有匹配'.encode() in output)
        os.write(master, b'\x1b')
        wait_for(lambda: ' / 搜索'.encode() in output)
        output.clear()
        os.write(master, b'/train[')
        wait_for(lambda: b'Train[Fast]' in output)
        os.write(master, b'\x1b')
        wait_for(lambda: ' / 搜索'.encode() in output)
        output.clear()
        os.write(master, b'/sleep')
        wait_for(lambda: b'Train[Fast]' in output and b'[sleep]' in output)
        os.write(master, b'\r')
        wait_for(lambda: tmux('display-message', '-p', '-t', f'{view}:', '#{window_id}') == wanted)
        wait_for(lambda: '__manager' not in tmux('show-messages', '-J'))
        output.clear()
        os.write(master, b'\x01g')
        wait_for(lambda: b'GPU 0' in output)
        os.write(master, b'd')
        wait_for(lambda: b'GPU-MOCK' in output and b'demo-process' in output)
        assert tmux('display-message', '-p', '-t', f'{view}:', '#{window_id}') == wanted
        assert not tmux('display-message', '-p', '-t', f'{view}:', '#{pane_mode}')
        os.write(master, b'q')
        wait_for(lambda: '__gpu' not in tmux('show-messages', '-J'))
        tmux('set-option', '-t', view, 'status-interval', '17')
        os.write(master, b'\x01r')
        wait_for(lambda: tmux('show-options', '-qv', '-t', view, 'status-interval') == '5')
        after = set(tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}').splitlines())
        assert after == set(before.splitlines())
        os.write(master, b'\x01d')
        assert client.wait(timeout=5) == 0
    finally:
        if client.poll() is None:
            client.terminate()
            client.wait(timeout=5)
        os.close(master)
        os.close(slave)


def test_uninstall_preserves_settings_and_refuses_unrelated_files(tmp_path):
    assert install(tmp_path).returncode == 0
    launcher = tmp_path / '.local/bin/pimux'
    theme = tmp_path / '.config/pimux/tmux.conf'
    before = theme.read_bytes()
    command = ['bash', '-c', 'source "$1"; uninstall_launcher "$2"', 'test',
               str(SOURCE / 'uninstall.sh'), str(tmp_path)]
    subprocess.run(command, check=True, capture_output=True)
    assert not launcher.exists()
    assert theme.read_bytes() == before
    launcher.write_text('# personal tool\n')
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert launcher.read_text() == '# personal tool\n'


def test_manager_mouse_expands_scrolls_and_opens_search_result(server):
    env, tmux = server
    wanted = ''
    for index in range(1, 16):
        window = tmux('new-window', '-d', '-t', 'seed', '-n', f'mouse-{index:02}', '-P', '-F', '#{window_id}')
        if index == 12:
            wanted = window
    before = tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}')
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 14, 110, 0, 0))
    script = '''source "$1"
configure_runtime
load_manager
connect_session() { printf '\\nOPEN:%s:%s\\n' "$1" "$2"; }
manager
'''
    process = subprocess.Popen(['bash', '-c', script, 'test', str(SOURCE / 'pimux')],
                               env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()

    def wait_for(value):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if value in output:
                return
            if select.select([master], [], [], .05)[0]:
                output.extend(os.read(master, 65536))
        pytest.fail(output.decode(errors='replace')[-2000:])

    try:
        wait_for(b'> seed')
        os.write(master, b'\x1b[<0;2;4M\x1b[<0;2;4m')
        wait_for(b'mouse-04')
        output.clear()
        os.write(master, b'\x1b[<65;10;5M')
        wait_for(b'mouse-07')
        os.write(master, b'/mouse-12')
        wait_for(b'mouse-12')
        output.clear()
        # Release and out-of-list clicks must not enter or corrupt the filter.
        os.write(master, b'\x1b[<0;10;4m\x1b[<0;10;1M')
        wait_for(b'mouse-12')
        assert b'OPEN:' not in output
        os.write(master, b'\x1b[<0;10;4M')
        wait_for(f'OPEN:$0:{wanted}'.encode())
        assert process.wait(timeout=5) == 0
        assert b'\x1b[?1000l\x1b[?1006l' in output
        assert tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}') == before
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize('exit_with', ['q', 'signal'])
def test_gpu_mouse_wheel_scrolls_and_restores_terminal(tmp_path, server, exit_with):
    import re

    env, _ = server
    env['NO_COLOR'] = '1'  # Disabling colors must not disable mouse input.
    bindir = tmp_path / 'gpu-bin'
    bindir.mkdir()
    smi = bindir / 'nvidia-smi'
    smi.write_text('#!/bin/sh\nseq -f "%g, GPU-MOCK, 50, 1024, 8192, 50, 100, 250" 0 39\n')
    smi.chmod(0o755)
    env['PATH'] = f'{bindir}:{env["PATH"]}'
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 20, 110, 0, 0))
    original_terminal = termios.tcgetattr(slave)
    process = subprocess.Popen([str(SOURCE / 'pimux'), '__gpu'], env=env,
                               stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()

    def wait_for(value):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if value in output:
                return
            if select.select([master], [], [], .05)[0]:
                data = os.read(master, 65536)
                output.extend(data)
                # Respond as a terminal with mouse reporting initially disabled.
                for mode in (1000, 1006):
                    if f'\x1b[?{mode}$p'.encode() in data:
                        os.write(master, f'\x1b[?{mode};2$y'.encode())
        pytest.fail(output.decode(errors='replace')[-2000:])

    try:
        wait_for(b'GPU15')
        assert b'GPU16' not in output
        # Each wheel step selects the next row; crossing the page reveals more cards.
        output.clear()
        os.write(master, b'\x1b[<65;10;5M' * 4)
        wait_for(b'GPU16')
        output.clear()
        os.write(master, b'\x1b[<64;10;5M')
        wait_for(b'GPU 0')
        if exit_with == 'q':
            os.write(master, b'q')
        else:
            process.send_signal(signal.SIGTERM)
        wait_for(b'\x1b[?1049l')
        assert process.wait(timeout=5) == 0
        while select.select([master], [], [], 0)[0]:
            output.extend(os.read(master, 65536))
        reset_modes = {mode for modes in re.findall(rb'\x1b\[\?([0-9;]+)l', output)
                       for mode in modes.split(b';')}
        assert {b'1000', b'1006'} <= reset_modes
        assert termios.tcgetattr(slave) == original_terminal
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize('download_status', [0, 22])
def test_update_runs_only_successfully_downloaded_installer(tmp_path, download_status):
    curl = tmp_path / 'curl'
    curl.write_text('''#!/usr/bin/env bash
while (( $# )); do
    if [[ $1 == -o ]]; then destination=$2; break; fi
    shift
done
printf '%s' "$destination" > "$UPDATE_DOWNLOAD_LOG"
printf 'printf "UPDATE_EXECUTED\\\\n"\\n' > "$destination"
exit "$UPDATE_DOWNLOAD_STATUS"
''')
    curl.chmod(0o755)
    log = tmp_path / 'download-path'
    env = dict(os.environ, PATH=f'{tmp_path}:{os.environ["PATH"]}',
               UPDATE_DOWNLOAD_LOG=str(log), UPDATE_DOWNLOAD_STATUS=str(download_status))
    result = subprocess.run([str(SOURCE / 'pimux'), 'update'], env=env,
                            capture_output=True, text=True)
    assert result.returncode == download_status
    assert ('UPDATE_EXECUTED' in result.stdout) == (download_status == 0)
    assert not Path(log.read_text()).exists()


def test_mouse_click_passes_through_tmux_popup_to_manager(server):
    env, tmux = server
    tmux('source-file', str(SOURCE / 'pimux.conf'))
    tmux('set-option', '-g', '@pimux_launcher', str(SOURCE / 'pimux'))
    tmux('set-environment', '-g', 'PIMUX_RUNTIME_FILE', env['PIMUX_RUNTIME_FILE'])
    tmux('set-environment', '-g', 'PIMUX_LANGUAGE_FILE', env['PIMUX_LANGUAGE_FILE'])
    original = tmux('display-message', '-p', '-t', 'seed', '#{window_id}')
    wanted = tmux('new-window', '-d', '-t', 'seed', '-n', 'mouse-target', '-P', '-F', '#{window_id}')
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 120, 0, 0))
    client = subprocess.Popen(['tmux', 'attach-session', '-t', 'seed'], env=env,
                              stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()
    popup = None

    def wait_for(condition):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            if select.select([master], [], [], .05)[0]:
                output.extend(os.read(master, 65536))
        pytest.fail(output.decode(errors='replace')[-2000:])

    try:
        tty = os.ttyname(slave)
        wait_for(lambda: tty in tmux('list-clients', '-F', '#{client_name}'))
        socket = tmux('display-message', '-p', '#{socket_path}')
        # Fix the popup position so the terminal click has known screen coordinates.
        import shlex
        command = shlex.join([str(SOURCE / 'pimux'), '__manager', socket, tty, 'windows'])
        popup = subprocess.Popen(['tmux', 'display-popup', '-E', '-c', tty,
                                  '-x', '0', '-y', '0', '-w', '100', '-h', '20', command], env=env)
        wait_for(lambda: '点击进入'.encode() in output)
        os.write(master, b'\x1b[<0;20;7M\x1b[<0;20;7m')
        wait_for(lambda: tmux('list-clients', '-F', '#{window_id}') == wanted)
        assert popup.wait(timeout=5) == 0
        assert tmux('display-message', '-p', '-t', '=seed:', '#{window_id}') == original
        os.write(master, b'\x01d')
        assert client.wait(timeout=5) == 0
    finally:
        if client.poll() is None:
            client.terminate()
            client.wait(timeout=5)
        if popup is not None and popup.poll() is None:
            popup.terminate()
            popup.wait(timeout=5)
        os.close(master)
        os.close(slave)


def test_proxy_shell_apply_disable_restore_and_validation(tmp_path):
    proxy_file = tmp_path / 'proxy'
    env = {key: value for key, value in os.environ.items()
           if key.lower() not in ('http_proxy', 'https_proxy', 'all_proxy') and key not in ('TMUX', 'TMUX_PANE')}
    env.update(PATH=f'{SOURCE}:{env["PATH"]}', PIMUX_PROXY_FILE=str(proxy_file),
               HTTP_PROXY='http://inherited.example:8080', no_proxy='localhost,127.0.0.1')
    script = r'''set -e
source "$1/ui.bash"
source "$1/proxy.bash"
existing_hook() { :; }
PROMPT_COMMAND=(existing_hook)
pimux_proxy_shell_init
pimux_proxy_shell_init
[[ ${#PROMPT_COMMAND[@]} == 2 ]]
[[ $HTTP_PROXY == http://inherited.example:8080 && ! -v http_proxy ]]
export http_proxy=http://manual.example:8080
pimux_proxy_prompt
[[ $http_proxy == http://manual.example:8080 ]]
pimux proxy set 'http://user:private-password@127.0.0.1:7890'
[[ $http_proxy == "$HTTP_PROXY" && $https_proxy == "$http_proxy" && $ALL_PROXY == "$http_proxy" ]]
pimux proxy
pimux proxy off
[[ ! -v http_proxy && ! -v HTTP_PROXY && ! -v https_proxy && ! -v HTTPS_PROXY && ! -v ALL_PROXY && ! -v all_proxy ]]
[[ $no_proxy == localhost,127.0.0.1 ]]
pimux proxy on
[[ $https_proxy == http://user:private-password@127.0.0.1:7890 ]]
export http_proxy=http://manual.example:9999
pimux_proxy_prompt
[[ $http_proxy == http://manual.example:9999 ]]
pimux proxy on
[[ $http_proxy == http://user:private-password@127.0.0.1:7890 ]]
pimux proxy reset
[[ $HTTP_PROXY == http://inherited.example:8080 && ! -v http_proxy ]]
# A change from another terminal is applied at this shell's next prompt.
command pimux proxy set socks5h://127.0.0.1:7890
[[ ! -v http_proxy ]]
set +e
false
pimux_proxy_prompt
status=$?
set -e
[[ $status == 1 && $all_proxy == socks5h://127.0.0.1:7890 ]]
if pimux proxy set $'http://bad\naddress'; then exit 9; fi
[[ $all_proxy == socks5h://127.0.0.1:7890 ]]
# A fresh shell gets the preference without manual configuration.
bash -c 'source "$1"; pimux_proxy_shell_init; [[ $https_proxy == socks5h://127.0.0.1:7890 ]]' test "$1/proxy.bash"
# Settings remain editable even if an interrupted/manual edit left invalid data.
printf 'broken\n' > "$PIMUX_PROXY_FILE"
pimux proxy set http://127.0.0.1:8888
[[ $https_proxy == http://127.0.0.1:8888 ]]
'''
    result = subprocess.run(['bash', '-c', script, 'test', str(SOURCE)],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'private-password' not in result.stdout + result.stderr
    assert '***@127.0.0.1:7890' in result.stdout
    assert proxy_file.read_text() == 'on\nhttp://127.0.0.1:8888\n'
    assert proxy_file.stat().st_mode & 0o777 == 0o600


def test_pins_persist_share_views_isolate_servers_and_keep_selection(tmp_path, server):
    env, tmux = server
    alpha = tmux('new-session', '-d', '-s', 'alpha project', '-P', '-F', '#{session_id}')
    zeta = tmux('new-session', '-d', '-s', 'zeta', '-P', '-F', '#{session_id}')
    view = tmux('new-session', '-d', '-t', zeta, '-s', 'zeta-view', '-P', '-F', '#{session_id}')
    tmux('set-option', '-t', view, '@pimux_origin', zeta)
    prefix = ['bash', '-c', 'source "$1"; configure_runtime; load_manager; "$2" "${@:3}"',
              'test', str(SOURCE / 'pimux')]
    processes = [subprocess.Popen([*prefix, 'toggle_session_pin', sid], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for sid in (alpha, view)]
    for process in processes:
        _, error = process.communicate(timeout=5)
        assert process.returncode == 0, error
    pins = subprocess.check_output([*prefix, 'session_pin_names'], env=env, text=True)
    assert set(pins.splitlines()) == {'alpha project', 'zeta'}
    subprocess.run([*prefix, 'toggle_session_pin', alpha], env=env, check=True)
    # Preferences use names, so recreating the session preserves its pin.
    tmux('kill-session', '-t', view)
    tmux('kill-session', '-t', zeta)
    zeta = tmux('new-session', '-d', '-s', 'zeta', '-P', '-F', '#{session_id}')
    other_runtime = tmp_path / 'other-runtime'
    other_runtime.write_text(f"{shutil.which('tmux')}\nother-server\n{shutil.which('tmux')}\n")
    other_env = dict(env, PIMUX_RUNTIME_FILE=str(other_runtime))
    assert subprocess.check_output([*prefix, 'session_pin_names'], env=other_env, text=True) == ''

    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 20, 110, 0, 0))
    script = '''source "$1"
configure_runtime
load_manager
connect_session() { printf '\\nOPEN:%s\\n' "$1"; }
manager
'''
    process = subprocess.Popen(['bash', '-c', script, 'test', str(SOURCE / 'pimux')],
                               env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()

    def wait_for(condition):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            if select.select([master], [], [], .05)[0]:
                output.extend(os.read(master, 65536))
        pytest.fail(output.decode(errors='replace')[-1500:])

    try:
        wait_for(lambda: b'alpha project' in output and b'zeta' in output)
        assert output.index(b'zeta') < output.index(b'alpha project')
        # Unpinning moves the row, but Enter must still open the same session.
        os.write(master, b'p')
        wait_for(lambda: subprocess.check_output([*prefix, 'session_pin_names'], env=env) == b'')
        os.write(master, b'\r')
        wait_for(lambda: f'OPEN:{zeta}'.encode() in output)
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)


def test_copy_path_targets_only_requesting_client(tmp_path, server):
    import base64
    env, tmux = server
    directory = tmp_path / 'project "quoted" $literal'
    directory.mkdir()
    tmux('source-file', str(SOURCE / 'pimux.conf'))
    tmux('set-option', '-g', '@pimux_launcher', str(SOURCE / 'pimux'))
    tmux('set-environment', '-g', 'PIMUX_RUNTIME_FILE', env['PIMUX_RUNTIME_FILE'])
    tmux('set-environment', '-g', 'PIMUX_PINS_FILE', env['PIMUX_PINS_FILE'])
    tmux('new-window', '-t', 'seed', '-c', str(directory))
    tmux('new-session', '-d', '-s', 'peer', '-c', str(tmp_path))
    panes = tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}')
    clients = []
    outputs = [bytearray(), bytearray()]
    try:
        for session in ('seed', 'peer'):
            master, slave = os.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 140, 0, 0))
            process = subprocess.Popen(['tmux', 'attach-session', '-t', session], env=env,
                                       stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
            clients.append((process, master, slave))

        def drain():
            readable = select.select([item[1] for item in clients], [], [], .05)[0]
            for index, (_, master, _) in enumerate(clients):
                if master in readable:
                    outputs[index].extend(os.read(master, 65536))

        deadline = time.monotonic() + 8
        # Registration can precede terminal setup; wait for both rendered UIs.
        while not all(b'menu' in output for output in outputs) and time.monotonic() < deadline:
            drain()
        assert all(b'menu' in output for output in outputs), outputs
        os.write(clients[0][1], b'\x01y')
        encoded = base64.b64encode(str(directory).encode())
        deadline = time.monotonic() + 8
        while encoded not in outputs[0] and time.monotonic() < deadline:
            drain()
        assert tmux('show-buffer') == str(directory)
        assert encoded in outputs[0] and b']52;' in outputs[0], outputs[0].decode(errors='replace')
        drain()
        assert encoded not in outputs[1]
        assert tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}') == panes
    finally:
        for process, master, slave in clients:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            os.close(master)
            os.close(slave)


def test_proxy_panel_sets_disables_and_restores_preferences(tmp_path):
    file = tmp_path / 'proxy'
    env = dict(os.environ, PIMUX_PROXY_FILE=str(file), TERM='xterm-256color')
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 26, 120, 0, 0))
    process = subprocess.Popen([str(SOURCE / 'pimux'), '__proxy'], env=env,
                               stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()

    def wait_for(condition):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            if select.select([master], [], [], .05)[0]:
                output.extend(os.read(master, 65536))
        pytest.fail(output.decode(errors='replace')[-1500:])

    try:
        wait_for(lambda: b'e set address' in output)
        os.write(master, b'e')
        wait_for(lambda: b'Proxy URL' in output)
        os.write(master, b'\x15http://127.0.0.1:8088\r')
        wait_for(lambda: file.exists() and file.read_text() == 'on\nhttp://127.0.0.1:8088\n')
        os.write(master, b'd')
        wait_for(lambda: file.read_text() == 'off\nhttp://127.0.0.1:8088\n')
        os.write(master, b'o')
        wait_for(lambda: file.read_text() == 'on\nhttp://127.0.0.1:8088\n')
        os.write(master, b'i')
        wait_for(lambda: file.read_text() == 'inherit\nhttp://127.0.0.1:8088\n')
        os.write(master, b'q')
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)


def test_installed_shell_applies_proxy_without_extra_setup(tmp_path):
    result = install(tmp_path)
    assert result.returncode == 0, result.stderr
    env = dict(os.environ, HOME=str(tmp_path), PIMUX_PROXY_FILE=str(tmp_path / '.config/pimux/proxy'))
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    launcher = tmp_path / '.local/bin/pimux'
    subprocess.run([str(launcher), 'proxy', 'set', 'http://127.0.0.1:8089'], env=env,
                   check=True, capture_output=True)
    script = '''set -e
[[ $(type -t pimux) == function ]]
[[ $http_proxy == http://127.0.0.1:8089 && $https_proxy == "$http_proxy" ]]
pimux proxy off
[[ ! -v http_proxy && ! -v HTTP_PROXY ]]
pimux proxy on
[[ $http_proxy == http://127.0.0.1:8089 ]]
'''
    result = subprocess.run(['bash', '--rcfile', str(tmp_path / '.config/pimux/shell.bash'),
                             '-ic', script], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_proxy_indicator_tracks_the_pane_and_manual_exports(server):
    env, tmux = server
    tmux('source-file', str(SOURCE / 'pimux.conf'))
    pane = tmux('display-message', '-p', '-t', 'seed', '#{pane_id}')
    other = tmux('split-window', '-d', '-t', pane, '-P', '-F', '#{pane_id}')
    shell_env = {key: value for key, value in env.items()
                 if key.lower() not in ('http_proxy', 'https_proxy', 'all_proxy')}
    shell_env.update(TMUX=tmux('display-message', '-p', '#{socket_path},#{pid},0'), TMUX_PANE=pane)
    script = '''set -e
source "$1/proxy.bash"
pimux_proxy_shell_init
[[ $(command tmux show-options -pqv -t "$TMUX_PANE" @pimux_proxy_status) == off ]]
export https_proxy=http://127.0.0.1:7890
pimux_proxy_prompt
[[ $(command tmux show-options -pqv -t "$TMUX_PANE" @pimux_proxy_status) == on ]]
unset https_proxy
pimux_proxy_prompt
[[ $(command tmux show-options -pqv -t "$TMUX_PANE" @pimux_proxy_status) == off ]]
'''
    result = subprocess.run(['bash', '-c', script, 'test', str(SOURCE)], env=shell_env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert tmux('show-options', '-pqv', '-t', other, '@pimux_proxy_status') == ''
    # Exclude the asynchronous GPU command so its loading text cannot mask spacing.
    right = tmux('show-options', '-gqv', 'status-right').split('#(', 1)[0]
    unknown_render = tmux('display-message', '-p', '-t', other, right)
    tmux('set-option', '-p', '-t', other, '@pimux_proxy_status', 'on')
    off_render = tmux('display-message', '-p', '-t', pane, right)
    on_render = tmux('display-message', '-p', '-t', other, right)
    assert off_render != on_render
    assert '⛓︎' in on_render
    assert off_render == unknown_render == ''
    assert '#{?' not in on_render
