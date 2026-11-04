"""Exercise personal config writes and real tmux session lifecycle in isolation."""

import os
import fcntl
import re
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
         str(SOURCE / "scripts/setup-tmux.sh"), function, str(home), str(SOURCE)],
        text=True, capture_output=True,
    )


@pytest.mark.parametrize("tmux_present", [False, True])
def test_installer_checks_external_tmux_before_installing_dependencies(tmp_path, tmux_present):
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("dirname", "readlink"):
        (tools / name).symlink_to(shutil.which(name))
    present = tools / "present"
    present.write_text("#!/bin/sh\nexit 0\n")
    present.chmod(0o755)
    dependencies = ["infocmp", "flock", "timeout", "curl", "ss", "ip"]
    if tmux_present:
        dependencies.append("tmux")
    for name in dependencies:
        (tools / name).symlink_to(present)
    apt = tools / "apt-get"
    apt.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PIMUX_DEPENDENCY_LOG"\n')
    apt.chmod(0o755)
    sudo = tools / "sudo"
    sudo.write_text('#!/bin/sh\nexec "$@"\n')
    sudo.chmod(0o755)
    log = tmp_path / "packages.log"
    env = dict(os.environ, PATH=str(tools), HOME=str(tmp_path), PIMUX_DEPENDENCY_LOG=str(log))
    result = subprocess.run(
        [shutil.which("bash"), "-c", 'source "$1" && install_dependencies',
         "test", str(SOURCE / "scripts/setup-tmux.sh")],
        env=env, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if tmux_present:
        assert not log.exists()
    else:
        update, install = log.read_text().splitlines()
        assert update == "update"
        assert install.split()[:2] == ["install", "-y"]
        assert "tmux" in install.split()[2:]


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
    env['PIMUX_ENV_FILE'] = str(home / '.config/pimux/environment.json')
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    result = subprocess.run([str(home / '.local/bin/pimux'), '__gpu'], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'GPU 0' in result.stdout and '50.0%' in result.stdout
    ss = bindir / 'ss'
    ss.write_text('#!/bin/sh\necho \'LISTEN 0 128 127.0.0.1:8888 0.0.0.0:* users:(("demo",pid=2147483647,fd=3))\'\n')
    ss.chmod(0o755)
    result = subprocess.run([str(home / '.local/bin/pimux'), 'ports', '8888'], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '8888' in result.stdout and 'demo' in result.stdout
    ip = bindir / 'ip'
    ip.write_text('''#!/bin/sh
case "$*" in
    *address*) printf '%s' '[{"ifname":"eth0","flags":["UP"],"addr_info":[{"family":"inet","local":"192.0.2.23","prefixlen":24}]}]' ;;
    *) printf '[]' ;;
esac
''')
    ip.chmod(0o755)
    result = subprocess.run([str(home / '.local/bin/pimux'), 'ip', '--once'], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '192.0.2.23/24' in result.stdout
    result = subprocess.run([str(home / '.local/bin/pimux'), '__proxy'], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'PiMux' in result.stdout
    result = subprocess.run([str(home / '.local/bin/pimux'), 'env', 'set', 'HF_HOME', '/data/my models/$literal'],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run(['bash', '--rcfile', str(home / '.config/pimux/shell.bash'),
                             '-ic', '[[ $HF_HOME == "/data/my models/"\'$literal\' ]]'],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    for command in ('__env', 'help'):
        result = subprocess.run([str(home / '.local/bin/pimux'), command], env=env,
                                capture_output=True, text=True)
        assert result.returncode == 0 and 'PiMux' in result.stdout, result.stderr
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
    env['PIMUX_ENV_FILE'] = str(tmp_path / 'environment.json')
    script = '''set -e
source "$1"
declare -F starship_precmd >/dev/null
before=$PROMPT_COMMAND
source "$1"
[[ $PROMPT_COMMAND == "$before" ]]
[[ $STARSHIP_CONFIG == "$HOME/.config/pimux/starship.toml" ]]
'''
    result = subprocess.run(['bash', '--noprofile', '--norc', '-ic', script,
                             'test', str(SOURCE / 'lib/bashrc')], env=env,
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
    env['PIMUX_ENV_FILE'] = str(tmp_path / 'environment.json')
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


@pytest.mark.parametrize("width", [40, 80, 160])
@pytest.mark.parametrize("language,detach", [("en", "detach"), ("zh", "离开")])
def test_status_footer_reveals_shortcuts_only_after_prefix(tmp_path, server, width, language, detach):
    env, tmux = server
    directory = tmp_path / ("project-" * 30 if language == "en" else "项目目录" * 20)
    directory.mkdir()
    # A long ASCII/CJK path exercises the footer's displayed-width reservation.
    tmux("respawn-pane", "-k", "-t", "=seed:", "-c", str(directory), "sleep", "60")
    tmux("source-file", str(SOURCE / "config/tmux.conf"))
    tmux("set-option", "-g", "@pimux_language", language)
    tmux("set-option", "-g", "status-right", "")
    pane = tmux("display-message", "-p", "-t", "=seed:", "#{pane_id}")
    pid = tmux("display-message", "-p", "-t", pane, "#{pane_pid}")
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, width, 0, 0))
    client = subprocess.Popen(["tmux", "attach-session", "-t", "=seed"], env=env,
                              stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()

    def wait_for(condition):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if condition():
                return
            if select.select([master], [], [], .05)[0]:
                output.extend(os.read(master, 65536))
        pytest.fail(output.decode(errors="replace")[-1500:])

    def rendered(option):
        return re.sub(r"#\[[^]]*\]", "", tmux("list-clients", "-F", f"#{{E:{option}}}"))

    def footer_width():
        return int(tmux("list-clients", "-F", "#{w:#{E:status-format[1]}}"))

    try:
        wait_for(lambda: tmux("list-clients", "-F", "#{session_name}") == "seed")
        assert tmux("list-clients", "-F", "#{client_width}") == str(width)
        normal = f"Ctrl-a → d {detach}"
        assert rendered("@pimux_hint_normal") == normal
        footer = rendered("status-format[1]")
        assert footer.endswith(f" {normal}")
        assert str(directory) not in footer
        assert directory.name[-5:] in footer
        assert 0 < footer_width() <= width
        for _ in range(2):
            os.write(master, b"\x01")
            wait_for(lambda: tmux("list-clients", "-F", "#{client_prefix}") == "1")
            prefix = rendered("status-format[1]")
            assert prefix != footer and "Ctrl-a" in prefix
            for key in ("c ", ", ", "x ", "Esc"):
                assert key in prefix
            assert 0 < footer_width() <= width
            os.write(master, b"\x1b")
            wait_for(lambda: tmux("list-clients", "-F", "#{client_prefix}") == "0")
            assert rendered("status-format[1]") == footer

        # Contextual mode hints still take precedence over the quiet footer.
        tmux("copy-mode", "-t", pane)
        assert "[COPY]" in rendered("status-format[1]")
        tmux("send-keys", "-t", pane, "-X", "cancel")
        assert rendered("status-format[1]") == footer
        os.write(master, b"\x01d")
        wait_for(lambda: client.poll() is not None)
        assert client.returncode == 0
        assert tmux("display-message", "-p", "-t", pane, "#{pane_pid} #{pane_dead}") == f"{pid} 0"
    finally:
        if client.poll() is None:
            client.terminate()
            client.wait(timeout=5)
        os.close(master)
        os.close(slave)


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
    args = ["bash", "-c", call, "test", str(SOURCE / "bin/pimux"), "agents"]
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
    result = subprocess.run([str(SOURCE / "bin/pimux"), "-n", "new-project"], env=env,
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert tmux("list-sessions", "-F", "#{session_name}") == "seed"


def test_background_tmux_manages_exact_windows_without_a_terminal(tmp_path, server):
    env, tmux = server
    before = tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}")
    focus_format = "#{window_id} #{pane_id} #{pane_mode}"
    focus_before = tmux("display-message", "-p", "-t", "=seed:", focus_format)
    directory = tmp_path / "experiment 'quoted'; $literal"
    directory.mkdir()

    def call(*args):
        return subprocess.run([str(SOURCE / "bin/pimux"), "tmux", *args], env=env,
                              text=True, capture_output=True)

    assert call().returncode == 2
    created = call("new-window", "-d", "-t", "=seed:", "-n", "experiment 'one'; $literal",
                   "-c", str(directory), "-P", "-F", "#{window_id} #{pane_id}",
                   "sh", "-c", "printf '%s\\n' 'background output'; exec sleep 60")
    assert created.returncode == 0, created.stderr
    window, pane = created.stdout.strip().split()
    assert window.startswith("@") and pane.startswith("%")
    pid = tmux("display-message", "-p", "-t", pane, "#{pane_pid}")
    assert Path(f"/proc/{pid}/cwd").readlink() == directory
    renamed = call("rename-window", "-t", window, "evaluation 'two'")
    assert renamed.returncode == 0, renamed.stderr
    metadata = call("display-message", "-p", "-t", pane, "#{window_id}\t#{window_name}")
    assert metadata.stdout == f"{window}\tevaluation 'two'\n"
    assert not metadata.stderr
    # Inspecting a background terminal must not attach, select it or enter copy mode.
    # Compare the native capture result rather than assuming tmux's whitespace.
    capture_args = ("capture-pane", "-p", "-t", pane, "-S", "-100")
    deadline = time.monotonic() + 5
    while "background output" not in tmux(*capture_args) and time.monotonic() < deadline:
        time.sleep(.05)
    native_capture = subprocess.run(["tmux", *capture_args], env=env,
                                    text=True, capture_output=True)
    capture = call(*capture_args)
    assert "background output" in capture.stdout
    assert (capture.returncode, capture.stdout, capture.stderr) == (
        native_capture.returncode, native_capture.stdout, native_capture.stderr)
    assert tmux("display-message", "-p", "-t", "=seed:", focus_format) == focus_before
    assert not tmux("display-message", "-p", "-t", pane, "#{pane_mode}")
    assert tmux("display-message", "-p", "-t", pane, "#{pane_pid}") == pid
    native_error = subprocess.run(["tmux", "list-panes", "-t", "@999999999"], env=env,
                                  text=True, capture_output=True)
    error = call("list-panes", "-t", "@999999999")
    assert error.returncode == native_error.returncode != 0
    assert (error.stdout, error.stderr) == (native_error.stdout, native_error.stderr)
    closed = call("kill-window", "-t", window)
    assert closed.returncode == 0, closed.stderr
    assert tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}") == before


@pytest.mark.parametrize("close_original", [False, True])
def test_independent_view_shares_programs_and_preserves_last_reference(tmp_path, server, close_original):
    env, tmux = server
    tmux("source-file", str(SOURCE / "config/tmux.conf"))
    tmux("set-option", "-g", "@pimux_launcher", str(SOURCE / "bin/pimux"))
    original = tmux("display-message", "-p", "-t", "=seed:", "#{window_id}")
    original_pane = tmux("list-panes", "-t", "=seed:", "-F", "#{pane_id} #{pane_pid}")
    cwd = tmp_path / "project" / "leaf"
    cwd.mkdir(parents=True)
    second = tmux("new-window", "-d", "-t", "=seed:", "-n", "review", "-c", str(cwd), "-P", "-F", "#{window_id}")
    clients = []
    output = bytearray()

    def start(*args):
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 160, 0, 0))
        process = subprocess.Popen([str(SOURCE / "bin/pimux"), *args], env=env,
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
        listing = subprocess.check_output([str(SOURCE / "bin/pimux"), "ls"], env=env, text=True)
        assert len(listing.splitlines()) == 2 and "~view-" not in listing
        caller_env = {**env, "TMUX_PANE": original_pane.split()[0]}
        caller = subprocess.run(["bash", "-c", 'source "$1"; current_client', "test", str(SOURCE / "bin/pimux")],
                                env=caller_env, capture_output=True, text=True)
        assert caller.returncode == 0
        assert caller.stdout.strip() == tmux("list-clients", "-t", first_view, "-F", "#{client_name}")
        tmux("select-window", "-t", f"{view}:{original}")
        ambiguous = subprocess.run(["bash", "-c", 'source "$1"; current_client', "test", str(SOURCE / "bin/pimux")],
                                   env=caller_env, capture_output=True, text=True)
        assert ambiguous.returncode != 0
        tmux("select-window", "-t", f"{view}:{second}")

        # Entering another session through the menu must keep this client's view
        # independent; opening the manager must not put a shared pane into a mode.
        tmux("new-session", "-d", "-s", "target")
        client_name = tmux("list-clients", "-t", view, "-F", "#{client_name}")
        output.clear()
        os.write(view_tty, b"\x01h")
        wait_for(lambda: "工作终端".encode() in output)
        os.write(view_tty, b"s")
        wait_for(lambda: "会话管理".encode() in output)
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
        fresh = subprocess.run([str(SOURCE / "bin/pimux"), "ls"], env=env,
                               text=True, capture_output=True, check=True)
        old = subprocess.run([str(SOURCE / "bin/pimux"), "--system", "ls"], env=env,
                             text=True, capture_output=True, check=True)
        assert "fresh" in fresh.stdout and "seed" not in fresh.stdout
        assert "seed" in old.stdout and "fresh" not in old.stdout
        for flags, expected in (([], "fresh"), (["--system"], "seed")):
            background = subprocess.run(
                [str(SOURCE / "bin/pimux"), *flags, "tmux", "list-sessions", "-F", "#{session_name}"],
                env=env, text=True, capture_output=True, check=True,
            )
            assert background.stdout.strip() == expected
        diagnostics = subprocess.run([str(SOURCE / "bin/pimux"), "doctor"], env=env,
                                     text=True, capture_output=True, check=True)
        pid = tmux("-L", "pimux-3.8", "display-message", "-p", "#{pid}")
        assert f"PID {pid}" in diagnostics.stdout
        # Theme updates must reach pimux on both servers, leaving other sessions alone.
        tmux("new-session", "-d", "-s", "personal")
        tmux("set-option", "-t", "personal", "status-right", "personal status")
        personal_options = tmux("show-options", "-t", "personal")
        for options, session in (([], "seed"), (["-L", "pimux-3.8"], "fresh")):
            tmux(*options, "set-option", "-t", session, "@pimux_launcher", str(SOURCE / "bin/pimux"))
            tmux(*options, "set-option", "-t", session, "status-right", "")
        managed_env = dict(env, TMUX_PANE=tmux("display-message", "-p", "-t", "=seed:", "#{pane_id}"))
        background = subprocess.run(
            [str(SOURCE / "bin/pimux"), "tmux", "display-message", "-p", "#{socket_path}"],
            env=managed_env, text=True, capture_output=True, check=True,
        )
        assert background.stdout.strip() == env["TMUX"].split(",", 1)[0]
        before = tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}")
        subprocess.run(
            ["bash", "-c", 'source "$1"; configure_runtime true; reload_config',
             "test", str(SOURCE / "bin/pimux")], env=env, check=True, capture_output=True,
        )
        for options, session in (([], "seed"), (["-L", "pimux-3.8"], "fresh")):
            assert "__gpu-status" in tmux(*options, "show-options", "-qv", "-t", session, "status-right")
            assert "split-window -h" in tmux(*options, "list-keys", "-T", "prefix", "v")
            pane = tmux(*options, "display-message", "-p", "-t", session, "#{pane_id}")
            tmux(*options, "set-option", "-p", "-t", pane, "@pimux_command_status", "7")
            assert "#[reverse]" in tmux(*options, "display-message", "-p", "-t", session, "#{E:status-format[0]}")
        assert tmux("show-options", "-qv", "-t", "personal", "status-right") == "personal status"
        assert tmux("show-options", "-t", "personal") == personal_options
        assert tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}") == before
    finally:
        tmux("-L", "pimux-3.8", "kill-server")


def test_shared_server_reload_and_short_command_preserve_other_sessions(server):
    env, tmux = server
    Path(env['PIMUX_RUNTIME_FILE']).write_text(
        f"{shutil.which('tmux')}\npimux\n{shutil.which('tmux')}\n"
    )
    tmux('new-session', '-d', '-s', 'personal')
    tmux('set-option', '-t', 'seed', '@pimux_launcher', str(SOURCE / 'bin/pimux'))
    tmux('bind-key', '-r', 'g', 'set-option', '@original_gpu_key', 'used')
    tmux('bind-key', 'v', 'set-option', '@original_split_key', 'used')
    tmux('bind-key', '｜', 'set-option', '@original_fullwidth_split_key', 'used')
    tmux('unbind-key', 'h')
    global_before = tmux('show-options', '-g')
    personal_before = tmux('show-options', '-t', 'personal')
    panes_before = tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}')
    env['TMUX'] = tmux('display-message', '-p', '-t', 'seed', '#{socket_path},#{pid},0')
    env['TMUX_PANE'] = tmux('display-message', '-p', '-t', 'seed', '#{pane_id}')
    # No --system is needed inside a managed workspace on the older server.
    listing = subprocess.run([str(SOURCE / 'bin/pimux'), 'ls'], env=env,
                             capture_output=True, text=True, check=True)
    assert 'seed' in listing.stdout and 'personal' in listing.stdout
    for _ in range(2):
        subprocess.run([str(SOURCE / 'bin/pimux'), 'reload'], env=env,
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
        for key, option in ((b'v', '@original_split_key'), ('｜'.encode(), '@original_fullwidth_split_key')):
            os.write(master, b'\x02')
            deadline = time.monotonic() + 5
            while tmux('list-clients', '-F', '#{client_prefix}') != '1' and time.monotonic() < deadline:
                drain()
            assert tmux('list-clients', '-F', '#{client_prefix}') == '1'
            os.write(master, key)
            deadline = time.monotonic() + 5
            while tmux('show-options', '-qv', '-t', 'personal', option) != 'used' and time.monotonic() < deadline:
                drain()
            assert tmux('show-options', '-qv', '-t', 'personal', option) == 'used', (
                tmux('list-keys', '-T', 'prefix', key.decode()),
                tmux('list-sessions', '-F', '#{session_name}:#{@pimux_launcher}'),
            )
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


@pytest.mark.parametrize('pipe_key', ['|', '｜'], ids=['ascii', 'fullwidth'])
def test_nested_splits_work_with_letter_pipe_and_menu_shortcuts(server, pipe_key):
    env, tmux = server
    tmux('set-environment', '-g', 'PIMUX_RUNTIME_FILE', env['PIMUX_RUNTIME_FILE'])
    tmux('set-environment', '-g', 'PIMUX_LANGUAGE_FILE', env['PIMUX_LANGUAGE_FILE'])
    before = set(tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}').splitlines())
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 120, 0, 0))
    client = subprocess.Popen([str(SOURCE / 'bin/pimux'), '-n', 'seed'], env=env,
                              stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()

    def wait_for(condition):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            if select.select([master], [], [], .04)[0]:
                output.extend(os.read(master, 65536))
        pytest.fail(output.decode(errors='replace')[-1500:])

    def panes():
        return tmux('list-panes', '-t', 'seed', '-F', '#{pane_id}').splitlines()

    try:
        wait_for(lambda: '离开'.encode() in output)
        os.write(master, b'\x01-')
        wait_for(lambda: len(panes()) == 2)
        parent = tmux('list-clients', '-F', '#{pane_id}')
        parent_width, parent_height, parent_top = map(int, tmux(
            'display-message', '-p', '-t', parent, '#{pane_width} #{pane_height} #{pane_top}').split())
        os.write(master, b'\x01v')
        wait_for(lambda: len(panes()) == 3)
        pieces = [list(map(int, row.split())) for row in tmux(
            'list-panes', '-t', 'seed', '-F', '#{pane_width} #{pane_height} #{pane_top}').splitlines()]
        nested = [row for row in pieces if row[2] == parent_top]
        assert len(nested) == 2 and all(row[1] == parent_height for row in nested)
        assert sum(row[0] for row in nested) + 1 == parent_width
        os.write(master, b'\x01-')
        wait_for(lambda: len(panes()) == 4)
        os.write(master, b'\x01' + pipe_key.encode())
        wait_for(lambda: len(panes()) == 5)
        output.clear()
        os.write(master, b'\x01h')
        wait_for(lambda: '工作终端'.encode() in output)
        os.write(master, pipe_key.encode())
        wait_for(lambda: len(panes()) == 6)
        assert before <= set(tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}').splitlines())
    finally:
        subprocess.run(['tmux', 'detach-client', '-t', os.ttyname(slave)], env=env, capture_output=True)
        if client.poll() is None:
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
        result = subprocess.run([str(SOURCE / "bin/pimux"), "-n", "agents"], env=env,
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
    tmux("source-file", str(SOURCE / "config/tmux.conf"))
    tmux("set-option", "-g", "@pimux_launcher", str(SOURCE / "bin/pimux"))
    kept_pane = tmux("list-panes", "-t", "=seed:", "-F", "#{pane_id} #{pane_pid}")
    tmux("new-session", "-d", "-s", "self")
    if not has_other_session:
        tmux("kill-session", "-t", "=seed")
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    client = subprocess.Popen([str(SOURCE / "bin/pimux"), "-n", "self"], env=env, stdin=slave,
                              stdout=slave, stderr=slave, start_new_session=True)
    peer_master, peer_slave = os.openpty()
    fcntl.ioctl(peer_slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    peer = subprocess.Popen([str(SOURCE / "bin/pimux"), "-n", "self"], env=env, stdin=peer_slave,
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
        wait_for(lambda: "会话管理".encode() in output)
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
        result = subprocess.run([str(SOURCE / "bin/pimux"), *args], env=env, text=True, capture_output=True)
        assert result.returncode == 0
    unknown = subprocess.run([str(SOURCE / "bin/pimux"), "arbitrary-name"], env=env, capture_output=True)
    assert unknown.returncode == 2
    assert subprocess.run(["tmux", "list-sessions"], env=env, capture_output=True).returncode != 0
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    client = subprocess.Popen([str(SOURCE / "bin/pimux")], env=env, stdin=slave,
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
        listing = subprocess.check_output([str(SOURCE / "bin/pimux"), "ls"], env=env, text=True)
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
    tmux("source-file", str(SOURCE / "config/tmux.conf"))
    tmux("new-session", "-d", "-s", "untouched")
    untouched = tmux("display-message", "-p", "-t", "=untouched:", "#{session_id}")
    tmux("set-option", "-t", untouched, "@pimux_launcher", "")
    original_options = tmux("show-options", "-t", untouched)
    tmux("-L", "parallel", "-f", "/dev/null", "new-session", "-d", "-s", "fresh")
    tmux("-L", "parallel", "source-file", str(SOURCE / "config/tmux.conf"))
    before = {socket: tmux("-L", socket, "list-panes", "-a", "-F", "#{pane_id} #{pane_pid}")
              for socket in ["default", "parallel"]}
    clients = []
    outputs = {}

    def start(*args):
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        process = subprocess.Popen([str(SOURCE / "bin/pimux"), *args], env=env, stdin=slave,
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
        help_text = subprocess.check_output([str(SOURCE / "bin/pimux"), "-h"], env=env, text=True)
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
        assert "个人工作终端" in subprocess.check_output([str(SOURCE / "bin/pimux"), "-h"], env=env, text=True)
        os.write(first_tty, b"\x1b")
        wait_for(lambda: "__client" not in tmux("show-messages", "-J"))
        os.write(first_tty, b"\x01/")
        # The header identifies the help screen; binding rows may be below the fold.
        wait_for(lambda: "PiMux · 使用帮助".encode() in outputs[first_tty])
        assert not tmux("list-clients", "-F", "#{pane_mode}")
        os.write(first_tty, b"q")
        wait_for(lambda: "__help" not in tmux("show-messages", "-J"))
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
        tmux("-L", "parallel", "source-file", str(SOURCE / "config/tmux.conf"))
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
        wait_for(lambda: "PiMux · Help".encode() in outputs[third_tty])
        os.write(third_tty, b"q")
        wait_for(lambda: "__help" not in tmux("-L", "parallel", "show-messages", "-J"))
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
             'test', str(SOURCE / 'bin/pimux')], env=env, check=True, capture_output=True,
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
    ss = bindir / 'ss'
    ss.write_text('#!/bin/sh\necho \'LISTEN 0 128 127.0.0.1:8888 0.0.0.0:* users:(("demo",pid=2147483647,fd=3))\'\n')
    ss.chmod(0o755)
    env['PATH'] = f'{bindir}:{env["PATH"]}'
    tmux('set-environment', '-g', 'PATH', env['PATH'])
    tmux('set-environment', '-g', 'PIMUX_RUNTIME_FILE', env['PIMUX_RUNTIME_FILE'])
    tmux('set-environment', '-g', 'PIMUX_LANGUAGE_FILE', env['PIMUX_LANGUAGE_FILE'])
    tmux('source-file', str(SOURCE / 'config/tmux.conf'))
    tmux('set-option', '-g', '@pimux_launcher', str(SOURCE / 'bin/pimux'))
    # Literal brackets must not become a pattern; hidden windows are searchable.
    wanted = tmux('new-window', '-d', '-t', 'seed', '-n', 'Train[Fast]', '-P', '-F', '#{window_id}', 'sleep 60')
    before = tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}')
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 140, 0, 0))
    client = subprocess.Popen([str(SOURCE / 'bin/pimux'), '-n', 'seed'], env=env,
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
        # Reach IP through the tree; keep the other direct tool shortcuts covered.
        for key, marker in [(b'e', '默认设置'.encode()), (b'o', 'PiMux 设置'.encode()), (b'g', b'GPU 0'),
                            (b't', 'TCP 端口'.encode()), (b'\t' + b'\x1b[B' * 7 + b'\r', 'IP 与网络'.encode()), (b'?', '快捷键'.encode())]:
            output.clear()
            os.write(master, key)
            wait_for(lambda: marker in output)
            assert not tmux('display-message', '-p', '-t', f'{view}:', '#{pane_mode}')
            output.clear()
            os.write(master, b'q')
            wait_for(lambda: '会话管理'.encode() in output)
        os.write(master, b'/missing-query')
        wait_for(lambda: '没有匹配'.encode() in output)
        os.write(master, b'\x1b')
        output.clear()
        os.write(master, b'/train[')
        wait_for(lambda: b'Train[Fast]' in output)
        os.write(master, b'\x1b')
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
        output.clear()
        os.write(master, b'\x01w')
        wait_for(lambda: '会话管理'.encode() in output)
        output.clear()
        os.write(master, b'd')
        wait_for(lambda: '窗口预览'.encode() in output and b'sleep' in output)
        assert tmux('display-message', '-p', '-t', f'{view}:', '#{window_id}') == wanted
        assert not tmux('display-message', '-p', '-t', f'{view}:', '#{pane_mode}')
        output.clear()
        os.write(master, b'q')
        wait_for(lambda: '会话管理'.encode() in output)
        os.write(master, b'q')
        wait_for(lambda: '__manager' not in tmux('show-messages', '-J'))
        output.clear()
        os.write(master, b'\x01P')
        wait_for(lambda: '完整目录路径'.encode() in output)
        os.write(master, b'q')
        wait_for(lambda: '__path' not in tmux('show-messages', '-J'))
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
               str(SOURCE / 'scripts/uninstall.sh'), str(tmp_path)]
    subprocess.run(command, check=True, capture_output=True)
    assert not launcher.exists()
    assert theme.read_bytes() == before
    launcher.write_text('# personal tool\n')
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert launcher.read_text() == '# personal tool\n'


@pytest.mark.parametrize("columns", [70, 110])
def test_manager_mouse_expands_scrolls_and_opens_search_result(server, columns):
    env, tmux = server
    wanted = ''
    for index in range(1, 16):
        window = tmux('new-window', '-d', '-t', 'seed', '-n', f'mouse-{index:02}', '-P', '-F', '#{window_id}')
        if index == 12:
            wanted = window
    before = tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}')
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 14, columns, 0, 0))
    original_terminal = termios.tcgetattr(slave)
    script = '''source "$1"
configure_runtime
load_manager
connect_session() { printf '\\nOPEN:%s:%s\\n' "$1" "$2"; }
manager
'''
    process = subprocess.Popen(['bash', '-c', script, 'test', str(SOURCE / 'bin/pimux')],
                               env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()
    pane_x = 28 if columns >= 80 else 2
    item_x = pane_x + 8

    def wait_for(value):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if value in output:
                return
            if select.select([master], [], [], .05)[0]:
                output.extend(os.read(master, 65536))
        pytest.fail(output.decode(errors='replace')[-2000:])

    try:
        wait_for(b'seed')
        os.write(master, f'\x1b[<0;{pane_x};4M\x1b[<0;{pane_x};4m'.encode())
        wait_for(b'mouse-04')
        output.clear()
        os.write(master, f'\x1b[<65;{item_x};5M'.encode())
        wait_for(b'mouse-07')
        os.write(master, b'/mouse-92')
        wait_for('没有匹配'.encode())
        output.clear()
        # Home/End, Delete and insertion edit the middle of the search.
        os.write(master, b'\x1b[H\x1b[3~m\x1b[F\x1b[D\x1b[D\x1b[3~1')
        wait_for(b'mouse-12')
        output.clear()
        # Ctrl-U clears the whole query, even with the cursor before its end.
        os.write(master, b'\x15mouse-12\x1b[D\x7f1')
        wait_for(b'mouse-12')
        output.clear()
        # Release and out-of-list clicks must not enter or corrupt the filter.
        os.write(master, f'\x1b[<0;{item_x};4m\x1b[<0;{item_x};1M'.encode())
        wait_for(b'mouse-12')
        assert b'OPEN:' not in output
        os.write(master, f'\x1b[<0;{item_x};4M'.encode())
        wait_for(f'OPEN:$0:{wanted}'.encode())
        assert process.wait(timeout=5) == 0
        assert termios.tcgetattr(slave) == original_terminal
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
    env.pop('TERM_PROGRAM', None)
    env.pop('TERM_PROGRAM_VERSION', None)
    bindir = tmp_path / 'gpu-bin'
    bindir.mkdir()
    smi = bindir / 'nvidia-smi'
    smi.write_text('#!/bin/sh\nseq -f "%g, GPU-MOCK, 50, 1024, 8192, 50, 100, 250" 0 39\n')
    smi.chmod(0o755)
    env['PATH'] = f'{bindir}:{env["PATH"]}'
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 20, 110, 0, 0))
    original_terminal = termios.tcgetattr(slave)
    process = subprocess.Popen([str(SOURCE / 'bin/pimux'), '__gpu'], env=env,
                               stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()
    queries = bytearray()

    def wait_for(value):
        nonlocal queries
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if value in output:
                return
            if select.select([master], [], [], .05)[0]:
                data = os.read(master, 65536)
                output.extend(data)
                # Support terminal discovery, including requests split across reads.
                queries.extend(data)
                consumed = 0
                for match in re.finditer(rb'\x1b(?:P\+q([0-9A-Fa-f;]+)\x1b\\|\[6n|\[>q|\[\?(1000|1006)\$p)', queries):
                    if match.group(1):
                        reply = b'\x1bP0+r' + match.group(1) + b'\x1b\\'
                    elif match.group(2):
                        reply = b'\x1b[?' + match.group(2) + b';2$y'
                    elif match[0] == b'\x1b[6n':
                        reply = b'\x1b[1;1R'
                    else:
                        reply = b'\x1bP>|XTerm(400)\x1b\\'
                    os.write(master, reply)
                    consumed = match.end()
                queries = queries[consumed:][-128:]
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
    result = subprocess.run([str(SOURCE / 'bin/pimux'), 'update'], env=env,
                            capture_output=True, text=True)
    assert result.returncode == download_status
    assert ('UPDATE_EXECUTED' in result.stdout) == (download_status == 0)
    assert not Path(log.read_text()).exists()


def test_mouse_click_passes_through_tmux_popup_to_manager(tmp_path, server):
    env, tmux = server
    tmux('source-file', str(SOURCE / 'config/tmux.conf'))
    tmux('set-option', '-g', '@pimux_launcher', str(SOURCE / 'bin/pimux'))
    tmux('set-environment', '-g', 'PIMUX_RUNTIME_FILE', env['PIMUX_RUNTIME_FILE'])
    tmux('set-environment', '-g', 'PIMUX_LANGUAGE_FILE', env['PIMUX_LANGUAGE_FILE'])
    original = tmux('display-message', '-p', '-t', 'seed', '#{window_id}')
    wanted = tmux('new-window', '-d', '-t', 'seed', '-n', 'mouse-target', '-P', '-F', '#{window_id}')
    directory = tmp_path / 'pane-target'
    directory.mkdir()
    wanted_pane = tmux('split-window', '-d', '-t', wanted, '-c', str(directory), '-P', '-F', '#{pane_id}', 'sleep 60')
    panes_before = set(tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}').splitlines())
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
        command = shlex.join([str(SOURCE / 'bin/pimux'), '__manager', socket, tty, 'windows'])
        popup = subprocess.Popen(['tmux', 'display-popup', '-E', '-c', tty,
                                  '-x', '0', '-y', '0', '-w', '100', '-h', '20', command], env=env)
        wait_for(lambda: '会话管理'.encode() in output)
        output.clear()
        os.write(master, b'/pane-target')
        wait_for(lambda: b'mouse-target' in output and b'[1/1]' in output)
        output.clear()
        os.write(master, b'\x1b[<0;10;9M\x1b[<0;10;9m')
        wait_for(lambda: '调整分屏'.encode() in output)
        os.write(master, b'h')
        wait_for(lambda: len(set(tmux('list-panes', '-t', wanted, '-F', '#{pane_height}').splitlines())) == 1)
        before_width = int(tmux('display-message', '-p', '-t', wanted_pane, '#{pane_width}'))
        os.write(master, b'r\x1b[C\x1b[C')
        wait_for(lambda: abs(int(tmux('display-message', '-p', '-t', wanted_pane, '#{pane_width}')) - before_width) == 4)
        output.clear()
        os.write(master, b'\rq')
        wait_for(lambda: b'mouse-target' in output and b'[1/1]' in output)
        output.clear()
        os.write(master, b'\x1b[<0;10;13M\x1b[<0;10;13m')
        wait_for(lambda: 'IP 与网络'.encode() in output)
        output.clear()
        os.write(master, b'q')
        wait_for(lambda: b'mouse-target' in output and b'[1/1]' in output)
        os.write(master, b'\x1b[<0;46;5M\x1b[<0;46;5m')
        wait_for(lambda: tmux('list-clients', '-F', '#{window_id}') == wanted)
        assert popup.wait(timeout=5) == 0
        assert tmux('list-clients', '-F', '#{pane_id}') == wanted_pane
        assert set(tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}').splitlines()) == panes_before
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


def test_manager_closes_only_the_selected_pane_after_confirmation(tmp_path, server):
    env, tmux = server
    directory = tmp_path / 'close-this-pane'
    directory.mkdir()
    target = tmux('split-window', '-d', '-t', 'seed', '-c', str(directory), '-P', '-F', '#{pane_id}', 'sleep 120')
    before = set(tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}').splitlines())
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 110, 0, 0))
    process = subprocess.Popen([str(SOURCE / 'bin/pimux')], env=env,
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
        wait_for(lambda: b'seed' in output)
        output.clear()
        os.write(master, b'/close-this-pane')
        wait_for(lambda: b'[1/1]' in output)
        output.clear()
        os.write(master, b'\t\tx')
        wait_for(lambda: '关闭分屏'.encode() in output)
        assert set(tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}').splitlines()) == before
        os.write(master, b'y')
        wait_for(lambda: target not in tmux('list-panes', '-a', '-F', '#{pane_id}').splitlines())
        assert set(tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}').splitlines()) == {
            row for row in before if not row.startswith(target + ' ')}
        os.write(master, b'q')
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)


def test_layout_controls_preserve_processes_and_never_retarget_a_closed_pane(server):
    from layout_ui import Layout

    _, tmux = server
    seed = tmux('list-panes', '-t', 'seed', '-F', '#{pane_id} #{pane_pid}')
    window, first = tmux('new-window', '-d', '-t', 'seed', '-P', '-F', '#{window_id} #{pane_id}', 'sleep 120').split()
    tmux('resize-window', '-t', window, '-x', '120', '-y', '36')
    for _ in range(2):
        tmux('split-window', '-d', '-t', first, 'sleep 120')
    processes = set(tmux('list-panes', '-t', window, '-F', '#{pane_id} #{pane_pid}').splitlines())
    active = tmux('display-message', '-p', '-t', window, '#{pane_id}')
    view = Layout(shutil.which('tmux'), tmux('display-message', '-p', '#{socket_path}'), first)
    assert view.refresh() and len(view.panes) == 3
    view.on_key('h')
    assert max(pane.width for pane in view.panes) - min(pane.width for pane in view.panes) <= 1
    assert len({pane.height for pane in view.panes}) == 1
    view.on_key('v')
    assert max(pane.height for pane in view.panes) - min(pane.height for pane in view.panes) <= 1
    assert len({pane.width for pane in view.panes}) == 1
    view.on_key('t')
    positions = tmux('list-panes', '-t', window, '-F', '#{pane_left} #{pane_top}').splitlines()
    assert len({row.split()[0] for row in positions}) > 1
    assert len({row.split()[1] for row in positions}) > 1
    before_index = view.panes[1].index
    view.on_key('n')
    assert next(pane.index for pane in view.panes if pane.identity == first) == before_index
    assert tmux('display-message', '-p', '-t', window, '#{pane_id}') == active
    view.on_key('h')
    width = next(pane.width for pane in view.panes if pane.identity == first)
    view.on_key('r')
    assert view.resizing
    view.on_key('KEY_RIGHT')
    view.on_key('KEY_RIGHT')
    assert abs(next(pane.width for pane in view.panes if pane.identity == first) - width) == 4
    assert not view.on_key('KEY_ESCAPE') and not view.resizing
    view.on_key('KEY_TAB')
    assert view.pane != first
    assert set(tmux('list-panes', '-t', window, '-F', '#{pane_id} #{pane_pid}').splitlines()) == processes
    tmux('kill-pane', '-t', view.pane)
    before_layout = tmux('display-message', '-p', '-t', window, '#{window_layout}')
    view.on_key('v')
    assert view.failed and not view.panes
    assert tmux('display-message', '-p', '-t', window, '#{window_layout}') == before_layout
    assert tmux('list-panes', '-t', 'seed:0', '-F', '#{pane_id} #{pane_pid}') == seed
    assert view.on_key('q')


def test_proxy_shell_apply_disable_restore_and_validation(tmp_path):
    proxy_file = tmp_path / 'proxy'
    env = {key: value for key, value in os.environ.items()
           if key.lower() not in ('http_proxy', 'https_proxy', 'all_proxy') and key not in ('TMUX', 'TMUX_PANE')}
    env.update(PATH=f'{SOURCE / "bin"}:{env["PATH"]}', PIMUX_PROXY_FILE=str(proxy_file),
               HTTP_PROXY='http://inherited.example:8080', no_proxy='localhost,127.0.0.1')
    script = r'''set -e
source "$1/lib/ui.bash"
source "$1/lib/proxy.bash"
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
bash -c 'source "$1"; pimux_proxy_shell_init; [[ $https_proxy == socks5h://127.0.0.1:7890 ]]' test "$1/lib/proxy.bash"
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
              'test', str(SOURCE / 'bin/pimux')]
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
    process = subprocess.Popen(['bash', '-c', script, 'test', str(SOURCE / 'bin/pimux')],
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


@pytest.mark.parametrize("source", ["path", "ip"])
def test_copy_path_targets_only_requesting_client(tmp_path, server, source):
    import base64
    env, tmux = server
    directory = tmp_path / 'project "quoted" $literal'
    directory.mkdir()
    if source == "ip":
        tools = tmp_path / "network-bin"
        tools.mkdir()
        (tools / "tmux").symlink_to(shutil.which("tmux"))
        ip = tools / "ip"
        ip.write_text("#!/bin/sh\ncase \"$*\" in *address*) echo '[{\"ifname\":\"eth0\",\"flags\":[\"UP\"],\"addr_info\":[{\"family\":\"inet\",\"local\":\"192.0.2.23\",\"prefixlen\":24}]}]';; *) echo '[]';; esac\n")
        ip.chmod(0o755)
        Path(env["PIMUX_RUNTIME_FILE"]).write_text(f"{tools / 'tmux'}\ndefault\n{tools / 'tmux'}\n")
        env["PATH"] = f'{tools}:{env["PATH"]}'
        tmux("set-environment", "-g", "PATH", env["PATH"])
    tmux('source-file', str(SOURCE / 'config/tmux.conf'))
    tmux('set-option', '-g', '@pimux_launcher', str(SOURCE / 'bin/pimux'))
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

        def clients_rendered():
            return all(f' {session} '.encode() in output
                       for session, output in zip(('seed', 'peer'), outputs))

        deadline = time.monotonic() + 8
        # Registration can precede terminal setup; identify each rendered session
        # by its status label, independently of the contextual shortcut hints.
        while not clients_rendered() and time.monotonic() < deadline:
            drain()
        assert clients_rendered(), outputs
        if source == "ip":
            os.write(clients[0][1], b'\x01h')
            deadline = time.monotonic() + 8
            while b'PiMux' not in outputs[0] or "工作终端".encode() not in outputs[0]:
                assert time.monotonic() < deadline, outputs[0].decode(errors="replace")
                drain()
            os.write(clients[0][1], b'i')
            deadline = time.monotonic() + 8
            while b'192.0.2.23/24' not in outputs[0]:
                assert time.monotonic() < deadline, outputs[0].decode(errors="replace")
                drain()
            os.write(clients[0][1], b'y')
        else:
            os.write(clients[0][1], b'\x01y')
        expected = "192.0.2.23" if source == "ip" else str(directory)
        encoded = base64.b64encode(expected.encode())
        deadline = time.monotonic() + 8
        while encoded not in outputs[0] and time.monotonic() < deadline:
            drain()
        assert tmux('show-buffer') == expected
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
    import re

    file = tmp_path / 'proxy'
    language = tmp_path / 'language'
    language.write_text('en\n')
    env = dict(os.environ, PIMUX_PROXY_FILE=str(file), TERM='xterm-256color',
               PIMUX_LANGUAGE_FILE=str(language), NO_COLOR='1')
    env.pop('TERM_PROGRAM', None)
    env.pop('TERM_PROGRAM_VERSION', None)
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 26, 120, 0, 0))
    process = subprocess.Popen([str(SOURCE / 'bin/pimux'), 'proxy'], env=env,
                               stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()
    queries = bytearray()

    def wait_for(condition):
        nonlocal queries
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            if select.select([master], [], [], .05)[0]:
                data = os.read(master, 65536)
                output.extend(data)
                queries.extend(data)
                consumed = 0
                for match in re.finditer(rb'\x1b(?:P\+q([0-9A-Fa-f;]+)\x1b\\|\[6n|\[>q|\[\?(1000|1006)\$p)', queries):
                    if match.group(1):
                        reply = b'\x1bP0+r' + match.group(1) + b'\x1b\\'
                    elif match.group(2):
                        reply = b'\x1b[?' + match.group(2) + b';2$y'
                    elif match[0] == b'\x1b[6n':
                        reply = b'\x1b[1;1R'
                    else:
                        reply = b'\x1bP>|XTerm(400)\x1b\\'
                    os.write(master, reply)
                    consumed = match.end()
                queries = queries[consumed:][-128:]
        pytest.fail(output.decode(errors='replace')[-1500:])

    try:
        wait_for(lambda: b'Set up a proxy' in output)
        os.write(master, b'e')
        wait_for(lambda: b'Proxy address' in output)
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
    tmux('source-file', str(SOURCE / 'config/tmux.conf'))
    pane = tmux('display-message', '-p', '-t', 'seed', '#{pane_id}')
    other = tmux('split-window', '-d', '-t', pane, '-P', '-F', '#{pane_id}')
    shell_env = {key: value for key, value in env.items()
                 if key.lower() not in ('http_proxy', 'https_proxy', 'all_proxy')}
    shell_env.update(TMUX=tmux('display-message', '-p', '#{socket_path},#{pid},0'), TMUX_PANE=pane)
    script = '''set -e
source "$1/lib/proxy.bash"
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
    right = tmux('show-options', '-gqv', 'status-right').removesuffix('#(#{q:@pimux_launcher} __gpu-status)')
    tmux('set-option', '-p', '-t', other, '@pimux_proxy_status', 'on')
    off_render = tmux('display-message', '-p', '-t', pane, right)
    on_render = tmux('display-message', '-p', '-t', other, right)
    assert off_render != on_render
    assert '⛓︎' in on_render
    assert off_render == ''
    assert '#{?' not in on_render

def test_window_preview_reports_exit_code_and_preserves_panes(server):
    import window_details

    env, tmux = server
    # Keep the process alive until tmux has finished registering its pane.
    tmux('set-window-option', '-g', 'remain-on-exit', 'on')
    target = tmux('new-window', '-d', '-t', 'seed', '-n', 'exited-preview', '-P', '-F', '#{window_id}',
                  'printf "preview-output\\n"; read -r ready; exit 7')
    tmux('send-keys', '-t', target, 'Enter')
    deadline = time.monotonic() + 3
    while tmux('display-message', '-p', '-t', target, '#{pane_dead}') != '1' and time.monotonic() < deadline:
        time.sleep(.03)
    before = tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid} #{pane_dead}')
    status_before = tmux('display-message', '-p', '-t', target, '#{pane_dead_status}')
    blocks = window_details.window_blocks(shutil.which('tmux'), tmux('display-message', '-p', '#{socket_path}'), target)
    content = '\n'.join(line.plain for block in blocks for line in block)
    status_after = tmux('display-message', '-p', '-t', target, '#{pane_dead_status}')
    # Match the native field, including unavailable status or a late collection.
    assert any(f'exit {code or "?"}' in content for code in (status_before, status_after)), tmux(
        'display-message', '-p', '-t', target,
        'dead=#{pane_dead} status=#{pane_dead_status} signal=#{pane_dead_signal} command=#{pane_start_command}')
    assert 'preview-output' in content
    assert tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid} #{pane_dead}') == before


def test_command_failures_mark_only_the_window_number_and_preserve_shell_status(tmp_path, server):
    import window_details

    env, tmux = server
    tmux('source-file', str(SOURCE / 'config/tmux.conf'))
    rc = tmp_path / 'command-status.bash'
    rc.write_text(f'''source "{SOURCE / 'lib/bashrc'}"
pimux_command_status_init
PROMPT_COMMAND+=('PS1="__PIMUX_READY__> "')
''')
    window, first = tmux('new-window', '-d', '-t', 'seed', '-n', 'commands', '-P', '-F',
                         '#{window_id} #{pane_id}', 'bash', '--noprofile', '--rcfile', str(rc), '-i').split()
    second = tmux('split-window', '-d', '-t', first, '-P', '-F', '#{pane_id}',
                  'bash', '--noprofile', '--rcfile', str(rc), '-i')

    def wait_for(condition):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.03)
        pytest.fail(tmux('capture-pane', '-p', '-t', first) + tmux('capture-pane', '-p', '-t', second))

    def status(pane):
        return tmux('show-options', '-pqv', '-t', pane, '@pimux_command_status')

    def output(pane):
        return tmux('capture-pane', '-p', '-t', pane, '-S', '-100')

    def command(pane, value):
        prompts = output(pane).count('__PIMUX_READY__>')
        tmux('send-keys', '-t', pane, '-l', value)
        tmux('send-keys', '-t', pane, 'Enter')
        wait_for(lambda: output(pane).count('__PIMUX_READY__>') > prompts)

    def highlighted():
        number = tmux('display-message', '-p', '-t', first, '#{window_index}')
        for key in ('window-status-format', 'window-status-current-format'):
            label = tmux('display-message', '-p', '-t', first, '#{E:' + key + '}')
            assert ('#[bold]#[reverse]' + number + '#[nobold]#[noreverse]') in label

    wait_for(lambda: status(first) == '0' and status(second) == '0' and
             '__PIMUX_READY__>' in output(first) and '__PIMUX_READY__>' in output(second))
    command(first, 'false')
    assert status(first) == '1'
    highlighted()
    assert '#[reverse]' not in tmux('display-message', '-p', '-t', 'seed:0', '#{E:window-status-format}')
    command(first, '')  # Empty input must retain the failed command's status.
    assert status(first) == '1'
    command(first, 'printf "preserved=%s pipes=%s\\n" "$?" "${PIPESTATUS[*]}"')
    assert 'preserved=1 pipes=1' in output(first) and status(first) == '0'
    command(first, 'false | true')
    command(first, 'printf "pipeline=%s\\n" "${PIPESTATUS[*]}"')
    assert 'pipeline=1 0' in output(first) and status(first) == '0'
    command(first, 'set -o pipefail; false | true')
    assert status(first) == '1'
    command(second, "bash -c 'exit 7'")
    command(first, 'true')
    highlighted()  # Success in one pane must not erase another pane's failure.
    blocks = window_details.window_blocks(shutil.which('tmux'), tmux('display-message', '-p', '#{socket_path}'), window)
    assert 'exit 7' in '\n'.join(line.plain for block in blocks for line in block)
    command(second, 'true')
    assert '#[reverse]' not in tmux('display-message', '-p', '-t', first, '#{E:window-status-format}')
    prompts = output(first).count('__PIMUX_READY__>')
    tmux('send-keys', '-t', first, 'sleep 30', 'Enter')
    wait_for(lambda: tmux('display-message', '-p', '-t', first, '#{pane_current_command}') == 'sleep')
    tmux('send-keys', '-t', first, 'C-c')
    wait_for(lambda: output(first).count('__PIMUX_READY__>') > prompts)
    assert status(first) == '0'
    command(second, 'false')
    tmux('kill-pane', '-t', second)
    assert '#[reverse]' not in tmux('display-message', '-p', '-t', first, '#{E:window-status-format}')

def test_proxy_icon_detects_legacy_foreground_process_without_restarting_it(server):
    env, tmux = server
    tmux('source-file', str(SOURCE / 'config/tmux.conf'))
    tmux('set-option', '-t', 'seed', '@pimux_launcher', str(SOURCE / 'bin/pimux'))
    # Keep the test independent of NVIDIA availability and asynchronous GPU output.
    right = tmux('show-options', '-gqv', 'status-right').removesuffix('#(#{q:@pimux_launcher} __gpu-status)') + 'cards'
    tmux('set-option', '-t', 'seed', 'status-right', right)
    pane = tmux('new-window', '-t', 'seed', '-P', '-F', '#{pane_id}',
                'env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u ALL_PROXY '
                'HTTPS_PROXY=http://test-user:private-test-secret@127.0.0.1:7890 sleep 60')
    assert tmux('show-options', '-pqv', '-t', pane, '@pimux_proxy_status') == ''
    pid = tmux('display-message', '-p', '-t', pane, '#{pane_pid}')
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 110, 0, 0))
    client = subprocess.Popen(['tmux', 'attach-session', '-t', 'seed'], env=env,
                              stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()
    try:
        deadline = time.monotonic() + 8
        while '⛓'.encode() not in output and time.monotonic() < deadline:
            if select.select([master], [], [], .05)[0]:
                output.extend(os.read(master, 65536))
        assert '⛓'.encode() in output, output.decode(errors='replace')[-1000:]
        assert b'private-test-secret' not in output
        assert b'cards' in output
        # A shell report takes precedence over the process startup environment.
        tmux('set-option', '-p', '-t', pane, '@pimux_proxy_status', 'off')
        rendered = tmux('display-message', '-p', '-t', pane, '#{E:status-right}')
        assert '⛓' not in rendered and rendered == 'cards'
        assert tmux('display-message', '-p', '-t', pane, '#{pane_pid}') == pid
        assert tmux('display-message', '-p', '-t', pane, '#{pane_dead}') == '0'
    finally:
        if client.poll() is None:
            client.terminate()
            client.wait(timeout=5)
        os.close(master)
        os.close(slave)

def test_close_pane_confirms_and_targets_only_the_selected_split(server):
    env, tmux = server
    tmux('source-file', str(SOURCE / 'config/tmux.conf'))
    tmux('set-option', '-g', '@pimux_launcher', str(SOURCE / 'bin/pimux'))
    survivor = tmux('display-message', '-p', '-t', 'seed:', '#{pane_id}')
    survivor_pid = tmux('display-message', '-p', '-t', survivor, '#{pane_pid}')
    closing = tmux('split-window', '-h', '-t', 'seed:', '-P', '-F', '#{pane_id}', 'sleep 60')
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 120, 0, 0))
    client = subprocess.Popen([str(SOURCE / 'bin/pimux'), '-n', 'seed'], env=env,
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
    def prefix(key):
        os.write(master, b'\x01')
        wait_for(lambda: tmux('list-clients', '-F', '#{client_prefix}') == '1')
        os.write(master, key)
    try:
        wait_for(lambda: b'Ctrl-a' in output)
        prefix(b'x')
        wait_for(lambda: '关闭当前分屏'.encode() in output)
        output.clear()
        os.write(master, b'n')
        wait_for(lambda: b'Ctrl-a' in output)
        assert closing in tmux('list-panes', '-t', 'seed:', '-F', '#{pane_id}').splitlines()
        output.clear()
        prefix(b'x')
        wait_for(lambda: '关闭当前分屏'.encode() in output)
        os.write(master, b'y')
        wait_for(lambda: tmux('list-panes', '-t', 'seed:', '-F', '#{pane_id}') == survivor)
        assert tmux('display-message', '-p', '-t', survivor, '#{pane_pid}') == survivor_pid
        prefix(b'd')
        assert client.wait(timeout=5) == 0
    finally:
        if client.poll() is None:
            client.terminate()
            client.wait(timeout=5)
        os.close(master)
        os.close(slave)


def native_pane_field(env, pane, field):
    # The server fixture strips whitespace; paths must lose only tmux's record LF.
    result = subprocess.run(['tmux', 'display-message', '-p', '-t', pane, '#{' + field + '}'],
                            env=env, capture_output=True, text=True, check=True)
    return result.stdout.removesuffix('\n')


@pytest.fixture
def preview_terminals():
    clients = []

    def start(command, env):
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 160, 0, 0))
        process = subprocess.Popen(command, env=env, stdin=slave, stdout=slave, stderr=slave,
                                   start_new_session=True)
        client = (process, master, slave, bytearray())
        clients.append(client)
        return client

    def wait_for(condition):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            for fd in select.select([client[1] for client in clients], [], [], .03)[0]:
                client = next(client for client in clients if client[1] == fd)
                client[3].extend(os.read(fd, 65536))
        pytest.fail('\n'.join(client[3].decode(errors='replace')[-2000:] for client in clients)
                    or 'Timed out waiting for native pane state')

    try:
        yield start, wait_for
    finally:
        for process, master, slave, _ in clients:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            os.close(master)
            os.close(slave)


@pytest.mark.parametrize('exited', [False, True], ids=['live', 'retained-exit'])
def test_window_preview_handles_real_multiline_cwd(tmp_path, server, preview_terminals, monkeypatch, exited):
    import window_details
    from inspect_ui import text

    env, tmux = server
    _, wait_for = preview_terminals
    monkeypatch.setenv('PIMUX_LANGUAGE', 'en')
    cwd = tmp_path / 'tab\tline\nleaf\\研究  '
    cwd.mkdir()
    tmux('set-window-option', '-g', 'remain-on-exit', 'on')
    window, pane = tmux('new-window', '-d', '-t', 'seed', '-c', str(cwd), '-P', '-F',
                        '#{window_id} #{pane_id}', 'bash', '-c',
                        'printf "preview-output\\n"; read -r ready; exit 7').split()
    other = tmux('split-window', '-d', '-t', pane, '-c', str(tmp_path), '-P', '-F', '#{pane_id}', 'sleep', '60')
    wait_for(lambda: 'preview-output' in tmux('capture-pane', '-p', '-t', pane))
    assert native_pane_field(env, pane, 'pane_current_path') == str(cwd)
    tmux('set-option', '-p', '-t', pane, '@pimux_command_status', '7')
    if exited:
        tmux('send-keys', '-t', pane, 'Enter')
        wait_for(lambda: tmux('display-message', '-p', '-t', pane, '#{pane_dead}:#{pane_dead_status}') == '1:7')
    native_cwd = native_pane_field(env, pane, 'pane_current_path')
    before = tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid} #{pane_dead}')
    blocks = window_details.window_blocks(shutil.which('tmux'), tmux('display-message', '-p', '#{socket_path}'), window)
    assert len(blocks) == 2
    assert [block[0].plain.split(' · ')[0] for block in blocks] == [pane, other]
    assert 'exit 7' in blocks[0][1].plain
    assert blocks[0][2].plain == text('Cwd: ' + (native_cwd or 'unavailable')).plain
    assert 'preview-output' in '\n'.join(line.plain for line in blocks[0])
    assert tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid} #{pane_dead}') == before


def test_window_preview_uses_real_foreground_cwd(tmp_path, server, preview_terminals, monkeypatch):
    import shlex
    import sys
    import window_details

    env, tmux = server
    _, wait_for = preview_terminals
    monkeypatch.setenv('PIMUX_LANGUAGE', 'en')
    parent, child = tmp_path / 'parent', tmp_path / 'child\\研究  '
    parent.mkdir()
    child.mkdir()
    rc = tmp_path / 'parent.bash'
    rc.write_text("PS1='__PARENT_READY__> '\n")
    window, pane = tmux('new-window', '-d', '-t', 'seed', '-c', str(parent), '-P', '-F',
                        '#{window_id} #{pane_id}', 'bash', '--noprofile', '--rcfile', str(rc), '-i').split()
    wait_for(lambda: '__PARENT_READY__>' in tmux('capture-pane', '-p', '-t', pane))
    shell_pid = tmux('display-message', '-p', '-t', pane, '#{pane_pid}')
    command = shlex.join([sys.executable, '-c', 'import os, sys; os.chdir(sys.argv[1]); input()', str(child)])
    tmux('send-keys', '-t', pane, '-l', command)
    tmux('send-keys', '-t', pane, 'Enter')
    wait_for(lambda: native_pane_field(env, pane, 'pane_current_path') == str(child))
    assert Path(f'/proc/{shell_pid}/cwd').readlink() == parent
    blocks = window_details.window_blocks(shutil.which('tmux'), tmux('display-message', '-p', '#{socket_path}'), window)
    assert blocks[0][2].plain == 'Cwd: ' + str(child)
    assert tmux('display-message', '-p', '-t', pane, '#{pane_pid}:#{pane_dead}') == shell_pid + ':0'


@pytest.mark.parametrize('search', [True, False], ids=['search', 'expanded-window'])
def test_manager_targets_exact_window_and_pane_with_control_characters(tmp_path, server, preview_terminals, search):
    env, tmux = server
    start, wait_for = preview_terminals
    cwd = tmp_path / 'prefix\nunique-tail\\研究  '
    cwd.mkdir()
    window, pane = tmux('new-window', '-d', '-t', 'seed', '-n', 'wanted\twindow\nname', '-c', str(cwd),
                        '-P', '-F', '#{window_id} #{pane_id}', 'sleep', '60').split()
    session = tmux('display-message', '-p', '-t', pane, '#{session_id}')
    assert native_pane_field(env, pane, 'pane_current_path') == str(cwd)
    before = tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}')
    script = '''source "$1"
configure_runtime
load_manager
connect_session() { printf '\\nOPEN:%s:%s:%s\\n' "$1" "$2" "$4"; }
manager
'''
    process, master, _, output = start(['bash', '-c', script, 'test', str(SOURCE / 'bin/pimux')], env)
    wait_for(lambda: '会话管理'.encode() in output)
    output.clear()
    if search:
        os.write(master, b'/unique-tail')

        def query_is_rendered():
            lines = bytes(output).rsplit(b'\x1b[H\x1b[2J', 1)[-1].splitlines()
            return len(lines) > 1 and '会话管理'.encode() in lines[0] and b'unique-tail' in lines[1]

        wait_for(query_is_rendered)
    else:
        os.write(master, b'\x1b[C')
        wait_for(lambda: b'wanted window name' in output)
        os.write(master, b'\x1b[B\x1b[B')
    os.write(master, b'\r')
    wait_for(lambda: f'OPEN:{session}:{window}:{pane if search else ""}'.encode() in output)
    assert process.wait(timeout=5) == 0
    assert tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid}') == before


def test_window_preview_popup_preserves_two_attached_clients(tmp_path, server, preview_terminals):
    env, tmux = server
    start, wait_for = preview_terminals
    tmux('source-file', str(SOURCE / 'config/tmux.conf'))
    tmux('set-option', '-g', '@pimux_launcher', str(SOURCE / 'bin/pimux'))
    for name in ('PIMUX_RUNTIME_FILE', 'PIMUX_LANGUAGE_FILE'):
        tmux('set-environment', '-g', name, env[name])
    original, original_pane = tmux('display-message', '-p', '-t', 'seed:', '#{window_id} #{pane_id}').split()
    tmux('split-window', '-d', '-t', original_pane, 'sleep', '60')
    received = tmp_path / 'received'
    receiver_window, receiver = tmux(
        'new-window', '-d', '-t', 'seed', '-n', 'input-receiver', '-P', '-F', '#{window_id} #{pane_id}',
        'bash', '-c', 'while IFS= read -r line; do printf "%s\\n" "$line" >> "$1"; done',
        'receiver', str(received)).split()
    first = start([str(SOURCE / 'bin/pimux'), '-n', 'seed'], env)
    wait_for(lambda: len(tmux('list-clients', '-F', '#{session_id}').splitlines()) == 1)
    first_view = tmux('list-clients', '-F', '#{session_id}')
    second = start([str(SOURCE / 'bin/pimux'), '-n', 'seed'], env)
    wait_for(lambda: len(tmux('list-clients', '-F', '#{session_id}').splitlines()) == 2)
    views = tmux('list-clients', '-F', '#{session_id}').splitlines()
    second_view = next(view for view in views if view != first_view)
    tmux('select-window', '-t', f'{first_view}:{original}')
    tmux('select-window', '-t', f'{second_view}:{receiver_window}')
    tmux('select-pane', '-t', original_pane)
    tmux('copy-mode', '-t', original_pane)

    def clients():
        return sorted(tmux('list-clients', '-F', '#{client_name} #{session_id} #{window_id} #{pane_id} #{pane_mode}').splitlines())

    before_clients = clients()
    before_panes = tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid} #{pane_dead} #{pane_mode}')
    before_output = tmux('capture-pane', '-p', '-t', original_pane)
    assert tmux('display-message', '-p', '-t', original_pane, '#{pane_mode}') == 'copy-mode'
    os.write(first[1], b'\x01w')
    wait_for(lambda: '会话管理'.encode() in first[3])
    first[3].clear()
    os.write(first[1], b'd')
    wait_for(lambda: '窗口预览'.encode() in first[3])
    assert clients() == before_clients
    assert tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid} #{pane_dead} #{pane_mode}') == before_panes
    os.write(second[1], b'second-client-input\r')
    wait_for(lambda: received.exists() and received.read_text() == 'second-client-input\n')
    assert tmux('display-message', '-p', '-t', receiver, '#{pane_dead}') == '0'
    assert tmux('capture-pane', '-p', '-t', original_pane) == before_output
    first[3].clear()
    os.write(first[1], b'q')
    wait_for(lambda: '会话管理'.encode() in first[3])
    os.write(first[1], b'q')
    wait_for(lambda: '__manager' not in tmux('show-messages', '-J'))
    assert clients() == before_clients
    assert tmux('list-panes', '-a', '-F', '#{pane_id} #{pane_pid} #{pane_dead} #{pane_mode}') == before_panes
