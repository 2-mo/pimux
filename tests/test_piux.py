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


def test_install_preserves_config_and_is_repeatable(tmp_path):
    # Quotes and dollar signs in paths must stay literal in tmux configuration.
    home = tmp_path / 'personal "terminal" $dir'
    home.mkdir()
    original = "# personal settings\nset -g history-limit 100000\n"
    conf = home / ".tmux.conf"
    conf.write_text(original)
    conf.chmod(0o600)
    first = install(home)
    assert first.returncode == 0, first.stderr
    installed = conf.read_text()
    assert installed.startswith(original)
    assert installed.count("source-file ") == 1
    assert conf.stat().st_mode & 0o777 == 0o600
    backups = list(home.glob(".tmux.conf.piux-backup.*"))
    assert len(backups) == 1
    assert backups[0].read_text() == original
    assert os.access(home / ".local/bin/piux", os.X_OK)
    again = install(home)
    assert again.returncode == 0, again.stderr
    assert conf.read_text() == installed
    assert list(home.glob(".tmux.conf.piux-backup.*")) == backups


def test_install_keeps_config_symlink_and_refuses_unrelated_launcher(tmp_path):
    original = tmp_path / "personal.conf"
    original.write_text("# existing dotfiles\n")
    main = tmp_path / ".tmux.conf"
    main.symlink_to(original)
    bindir = tmp_path / ".local/bin"
    bindir.mkdir(parents=True)
    launcher = bindir / "piux"
    launcher.write_text("# unrelated user tool\n")
    result = install(tmp_path)
    assert result.returncode != 0
    assert launcher.read_text() == "# unrelated user tool\n"
    assert main.is_symlink()
    assert original.read_text() == "# existing dotfiles\n"
    # A previous managed install can be updated without replacing the config link.
    launcher.write_text("# piux-managed: earlier version\n")
    result = install(tmp_path)
    assert result.returncode == 0, result.stderr
    assert main.is_symlink()
    assert original.read_text().startswith("# existing dotfiles\n")
    assert "source-file " in original.read_text()


def test_shell_install_preserves_dotfiles_and_is_repeatable(tmp_path):
    home = tmp_path / 'shell "quoted" $dir'
    home.mkdir()
    dotfile = home / 'personal.bashrc'
    original = '# existing Bash config\nexport MY_SETTING=keep\n'
    dotfile.write_text(original)
    dotfile.chmod(0o600)
    (home / '.bashrc').symlink_to(dotfile)
    (home / '.config').mkdir()
    theme = home / '.config/starship.toml'
    theme.write_text('# existing Starship theme\n')
    first = install(home, "install_shell_files")
    assert first.returncode == 0, first.stderr
    installed = dotfile.read_text()
    assert installed.startswith(original)
    assert (home / '.bashrc').is_symlink()
    assert dotfile.stat().st_mode & 0o777 == 0o600
    assert theme.read_text() == '# existing Starship theme\n'
    backups = list(home.glob('personal.bashrc.piux-backup.*'))
    assert len(backups) == 1 and backups[0].read_text() == original
    again = install(home, "install_shell_files")
    assert again.returncode == 0, again.stderr
    assert dotfile.read_text() == installed
    assert list(home.glob('personal.bashrc.piux-backup.*')) == backups


def test_shell_initializes_starship_when_only_environment_was_inherited():
    if not shutil.which('starship'):
        pytest.skip('requires starship')
    env = dict(os.environ, STARSHIP_SHELL='bash')
    script = '''set -e
source "$1"
declare -F starship_precmd >/dev/null
before=$PROMPT_COMMAND
source "$1"
[[ $PROMPT_COMMAND == "$before" ]]
[[ $STARSHIP_CONFIG == "$HOME/.config/piux/starship.toml" ]]
'''
    result = subprocess.run(['bash', '--noprofile', '--norc', '-ic', script,
                             'test', str(SOURCE / 'bashrc')], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_rename_migrates_references_and_keeps_live_runtime_and_prompt_files(tmp_path):
    home = tmp_path / 'old home'
    legacy = home / '.config/pimux'
    legacy.mkdir(parents=True)
    bindir = home / '.local/bin'
    bindir.mkdir(parents=True)
    launcher = bindir / 'pimux'
    launcher.write_text('# pimux-managed: previous launcher\n')
    launcher.chmod(0o755)
    runtime = '/opt/tmux/bin/tmux\npimux-3.8\n/usr/bin/tmux\n'
    (legacy / 'runtime.conf').write_text(runtime)
    (legacy / 'tmux.conf').write_text('# pimux-managed: previous theme\n')
    (legacy / 'starship.toml').write_text('# still used by existing shells\n')
    (legacy / 'bashrc').write_text('# pimux-managed: previous Bash setup\n')
    conf = home / '.tmux.conf'
    conf.write_text('# personal tmux config\n# pimux: personal terminal theme and bindings\n'
                    f'source-file "{legacy}/tmux.conf"\n')
    bash_include = subprocess.check_output(
        ['bash', '-c', 'printf "source %q" "$1"', 'test', str(legacy / 'bashrc')], text=True
    )
    rc = home / '.bashrc'
    rc.write_text('# personal Bash config\n# pimux: shared Bash prompt\n' + bash_include + '\n')
    for function in ('install_files', 'install_shell_files'):
        result = install(home, function)
        assert result.returncode == 0, result.stderr
    assert (home / '.config/piux/runtime.conf').read_text() == runtime
    assert not launcher.exists()
    archives = list(bindir.glob('pimux.piux-backup.*'))
    assert len(archives) == 1
    assert archives[0].read_text() == '# pimux-managed: previous launcher\n'
    assert '.config/pimux/tmux.conf' not in conf.read_text()
    assert bash_include not in rc.read_text()
    assert conf.read_text().startswith('# personal tmux config\n')
    assert rc.read_text().startswith('# personal Bash config\n')
    assert (legacy / 'starship.toml').read_text() == '# still used by existing shells\n'
    installed = (conf.read_text(), rc.read_text())
    for function in ('install_files', 'install_shell_files'):
        result = install(home, function)
        assert result.returncode == 0, result.stderr
    assert (conf.read_text(), rc.read_text()) == installed
    assert list(bindir.glob('pimux.piux-backup.*')) == archives


@pytest.fixture
def server(tmp_path):
    if not shutil.which("tmux"):
        pytest.skip("requires tmux")
    socket_dir = tmp_path / "sockets"
    socket_dir.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in {"TMUX", "TMUX_PANE"}}
    env["TMUX_TMPDIR"] = str(socket_dir)
    env["TERM"] = "xterm-256color"
    env["PIUX_RUNTIME_FILE"] = str(tmp_path / "runtime.conf")
    env["PIUX_LANGUAGE_FILE"] = str(tmp_path / "language")
    Path(env["PIUX_LANGUAGE_FILE"]).write_text("zh\n")

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
    conf = str(home / ".tmux.conf")
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
    args = ["bash", "-c", call, "test", str(SOURCE / "piux"), "agents"]
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
    result = subprocess.run([str(SOURCE / "piux"), "-n", "new-project"], env=env,
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert tmux("list-sessions", "-F", "#{session_name}") == "seed"


@pytest.mark.parametrize("close_original", [False, True])
def test_independent_view_shares_programs_and_preserves_last_reference(tmp_path, server, close_original):
    env, tmux = server
    tmux("source-file", str(SOURCE / "piux.conf"))
    tmux("set-option", "-g", "@piux_launcher", str(SOURCE / "piux"))
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
        process = subprocess.Popen([str(SOURCE / "piux"), *args], env=env,
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
            "list-sessions", "-F", "#{session_id} #{@piux_view}"
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
        listing = subprocess.check_output([str(SOURCE / "piux"), "ls"], env=env, text=True)
        assert len(listing.splitlines()) == 2 and "~view-" not in listing
        caller_env = {**env, "TMUX_PANE": original_pane.split()[0]}
        caller = subprocess.run(["bash", "-c", 'source "$1"; current_client', "test", str(SOURCE / "piux")],
                                env=caller_env, capture_output=True, text=True)
        assert caller.returncode == 0
        assert caller.stdout.strip() == tmux("list-clients", "-t", first_view, "-F", "#{client_name}")
        tmux("select-window", "-t", f"{view}:{original}")
        ambiguous = subprocess.run(["bash", "-c", 'source "$1"; current_client', "test", str(SOURCE / "piux")],
                                   env=caller_env, capture_output=True, text=True)
        assert ambiguous.returncode != 0
        tmux("select-window", "-t", f"{view}:{second}")

        # Entering another session through the menu must keep this client's view
        # independent; opening the manager must not put a shared pane into a mode.
        tmux("new-session", "-d", "-s", "target")
        client_name = tmux("list-clients", "-t", view, "-F", "#{client_name}")
        output.clear()
        os.write(view_tty, b"\x01h")
        wait_for(lambda: "piux · 工作终端".encode() in output)
        os.write(view_tty, b"s")
        wait_for(lambda: "piux · 会话管理".encode() in output)
        assert not tmux("display-message", "-p", "-t", f"{first_view}:", "#{pane_mode}")
        os.write(view_tty, b"\x1b[B\r")
        wait_for(lambda: "target" in tmux("list-clients", "-F", "#{@piux_view}"))
        assert tmux("display-message", "-p", "-t", f"{first_view}:", "#{window_id}") == original
        wait_for(lambda: "__manager" not in tmux("show-messages", "-J"))
        os.write(view_tty, b"\x01L")
        wait_for(lambda: tmux("list-clients", "-F", "#{@piux_view}").splitlines() == ["seed", "seed"])
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
    runtime = Path(env["PIUX_RUNTIME_FILE"])
    runtime.write_text(f"{shutil.which('tmux')}\npiux-3.8\n{shutil.which('tmux')}\n")
    tmux("-L", "piux-3.8", "-f", "/dev/null", "new-session", "-d", "-s", "fresh")
    try:
        # A read-only command from an old pane must still address the selected server.
        env["TMUX"] = tmux("display-message", "-p", "#{socket_path},#{pid},0")
        env["TMUX_PANE"] = "%9999"
        fresh = subprocess.run([str(SOURCE / "piux"), "ls"], env=env,
                               text=True, capture_output=True, check=True)
        old = subprocess.run([str(SOURCE / "piux"), "--system", "ls"], env=env,
                             text=True, capture_output=True, check=True)
        assert "fresh" in fresh.stdout and "seed" not in fresh.stdout
        assert "seed" in old.stdout and "fresh" not in old.stdout
        diagnostics = subprocess.run([str(SOURCE / "piux"), "doctor"], env=env,
                                     text=True, capture_output=True, check=True)
        pid = tmux("-L", "piux-3.8", "display-message", "-p", "#{pid}")
        assert f"PID {pid}" in diagnostics.stdout
        # Theme updates must reach piux on both servers, leaving other sessions alone.
        tmux("new-session", "-d", "-s", "personal")
        tmux("set-option", "-t", "personal", "status-right", "personal status")
        for options, session in (([], "seed"), (["-L", "piux-3.8"], "fresh")):
            tmux(*options, "set-option", "-t", session, "@piux_launcher", str(SOURCE / "piux"))
            tmux(*options, "set-option", "-t", session, "status-right", "")
        before = tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}")
        subprocess.run(
            ["bash", "-c", 'source "$1"; configure_runtime; refresh_session_themes',
             "test", str(SOURCE / "piux")], env=env, check=True, capture_output=True,
        )
        for options, session in (([], "seed"), (["-L", "piux-3.8"], "fresh")):
            assert "__gpu-status" in tmux(*options, "show-options", "-qv", "-t", session, "status-right")
        assert tmux("show-options", "-qv", "-t", "personal", "status-right") == "personal status"
        assert tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}") == before
    finally:
        tmux("-L", "piux-3.8", "kill-server")


def test_cross_server_entry_refuses_before_creating_session(server):
    env, tmux = server
    Path(env["PIUX_RUNTIME_FILE"]).write_text(
        f"{shutil.which('tmux')}\npiux-3.8\n{shutil.which('tmux')}\n"
    )
    env["TMUX"] = tmux("display-message", "-p", "#{socket_path},#{pid},0")
    env["TMUX_PANE"] = "%0"
    master, slave = os.openpty()
    try:
        result = subprocess.run([str(SOURCE / "piux"), "-n", "agents"], env=env,
                                stdin=slave, stdout=slave, stderr=subprocess.PIPE,
                                text=True, timeout=5)
        assert result.returncode != 0
        assert "Ctrl-a d" in result.stderr
        assert tmux("list-sessions", "-F", "#{session_name}") == "seed"
        untouched = subprocess.run(["tmux", "-L", "piux-3.8", "list-sessions"],
                                   env=env, capture_output=True)
        assert untouched.returncode != 0
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize("has_other_session", [True, False])
def test_manager_can_close_its_own_session(server, has_other_session):
    env, tmux = server
    tmux("source-file", str(SOURCE / "piux.conf"))
    tmux("set-option", "-g", "@piux_launcher", str(SOURCE / "piux"))
    kept_pane = tmux("list-panes", "-t", "=seed:", "-F", "#{pane_id} #{pane_pid}")
    tmux("new-session", "-d", "-s", "self")
    if not has_other_session:
        tmux("kill-session", "-t", "=seed")
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    client = subprocess.Popen([str(SOURCE / "piux"), "-n", "self"], env=env, stdin=slave,
                              stdout=slave, stderr=slave, start_new_session=True)
    peer_master, peer_slave = os.openpty()
    fcntl.ioctl(peer_slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    peer = subprocess.Popen([str(SOURCE / "piux"), "-n", "self"], env=env, stdin=peer_slave,
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
        wait_for(lambda: "piux · 会话管理".encode() in output)
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


def test_empty_manager_creates_only_on_request_and_help_is_read_only(server):
    env, tmux = server
    tmux("kill-server")
    for args in (["-h"], ["ls"]):
        result = subprocess.run([str(SOURCE / "piux"), *args], env=env, text=True, capture_output=True)
        assert result.returncode == 0
    unknown = subprocess.run([str(SOURCE / "piux"), "arbitrary-name"], env=env, capture_output=True)
    assert unknown.returncode == 2
    assert subprocess.run(["tmux", "list-sessions"], env=env, capture_output=True).returncode != 0
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    client = subprocess.Popen([str(SOURCE / "piux")], env=env, stdin=slave,
                              stdout=slave, stderr=slave, start_new_session=True)
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
        os.write(master, b"bad.name\r")
        wait_for("不能")
        assert subprocess.run(["tmux", "list-sessions"], env=env, capture_output=True).returncode != 0
        output.clear()
        os.write(master, b"n")
        wait_for("会话名称")
        os.write(master, b"ls\r")
        wait_for("ls")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = subprocess.run(["tmux", "list-clients", "-F", "#{@piux_view}"],
                                    env=env, capture_output=True, text=True)
            if result.stdout.strip() == "ls":
                break
            time.sleep(0.05)
        else:
            pytest.fail(output.decode(errors="replace")[-1500:])
        os.write(master, b"\x01d")
        assert client.wait(timeout=8) == 0
        assert tmux("list-sessions", "-F", "#{session_name}") == "ls"
        listing = subprocess.check_output([str(SOURCE / "piux"), "ls"], env=env, text=True)
        assert "ls  " in listing and "~view-" not in listing
    finally:
        if client.poll() is None:
            client.terminate()
            client.wait(timeout=5)
        os.close(master)
        os.close(slave)


def test_language_menu_persists_and_syncs_only_piux_across_servers(server):
    env, tmux = server
    preference = Path(env["PIUX_LANGUAGE_FILE"])
    preference.unlink()
    Path(env["PIUX_RUNTIME_FILE"]).write_text(f"{shutil.which('tmux')}\nparallel\n{shutil.which('tmux')}\n")
    tmux("source-file", str(SOURCE / "piux.conf"))
    tmux("new-session", "-d", "-s", "untouched")
    untouched = tmux("display-message", "-p", "-t", "=untouched:", "#{session_id}")
    tmux("set-option", "-t", untouched, "@piux_launcher", "")
    original_options = tmux("show-options", "-t", untouched)
    tmux("-L", "parallel", "-f", "/dev/null", "new-session", "-d", "-s", "fresh")
    tmux("-L", "parallel", "source-file", str(SOURCE / "piux.conf"))
    before = {socket: tmux("-L", socket, "list-panes", "-a", "-F", "#{pane_id} #{pane_pid}")
              for socket in ["default", "parallel"]}
    clients = []
    outputs = {}

    def start(*args):
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        process = subprocess.Popen([str(SOURCE / "piux"), *args], env=env, stdin=slave,
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
        help_text = subprocess.check_output([str(SOURCE / "piux"), "-h"], env=env, text=True)
        assert "Personal terminal" in help_text and not preference.exists()
        first, first_tty = start("--system", "-n", "seed")
        second, second_tty = start("-n", "fresh")
        wait_for(lambda: bool(tmux("list-clients", "-F", "#{session_id}")) and
                        bool(tmux("-L", "parallel", "list-clients", "-F", "#{session_id}")))
        assert "detach" in tmux("list-clients", "-F", "#{E:status-format[1]}")
        change_language(first_tty, b"z", "Work terminal")
        wait_for(lambda: preference.exists() and preference.read_text() == "zh\n" and
                        tmux("-L", "parallel", "list-clients", "-F", "#{@piux_language}") == "zh")
        wait_for(lambda: "工作终端".encode() in outputs[first_tty])
        assert "离开" in tmux("list-clients", "-F", "#{E:status-format[1]}")
        assert tmux("show-options", "-t", untouched) == original_options
        for socket in ["default", "parallel"]:
            # Extra views link the same panes; all original programs must remain.
            assert set(before[socket].splitlines()) == set(tmux(
                "-L", socket, "list-panes", "-a", "-F", "#{pane_id} #{pane_pid}"
            ).splitlines())
        assert "个人工作终端" in subprocess.check_output([str(SOURCE / "piux"), "-h"], env=env, text=True)
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
        tmux("-L", "parallel", "source-file", str(SOURCE / "piux.conf"))
        third, third_tty = start("-n", "fresh")
        wait_for(lambda: bool(tmux("-L", "parallel", "list-clients", "-F", "#{session_id}")))
        assert tmux("-L", "parallel", "list-clients", "-F", "#{@piux_language}") == "zh"
        change_language(third_tty, b"e", "工作终端")
        wait_for(lambda: preference.read_text() == "en\n" and
                        tmux("show-options", "-Aqv", "-t", "=seed:", "@piux_language") == "en")
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
