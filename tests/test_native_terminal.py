"""Installed native macOS terminal, with task-owned homes, processes and sockets."""

import fcntl
import os
from pathlib import Path
import select
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time

import pytest

SOURCE = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='requires native macOS terminal')


def test_native_source_install_two_clients_and_reinstall(tmp_path):
    home = tmp_path / 'home "quoted" $literal'
    home.mkdir()
    originals = {'.bashrc': '# personal bash\n', '.zshrc': '# personal zsh\n', '.tmux.conf': '# personal tmux\n'}
    for name, value in originals.items():
        (home / name).write_text(value)
    bash, binary = shutil.which('bash'), shutil.which('tmux')
    assert bash and binary and bash != '/bin/bash'
    with tempfile.TemporaryDirectory(prefix='pimux-native-', dir='/tmp') as sockets:
        env = {**os.environ, 'HOME': str(home), 'TMUX_TMPDIR': sockets, 'TERM': 'xterm-256color',
               'UV_PYTHON': sys.executable, 'UV_OFFLINE': '1', 'PIMUX_BASH': bash}
        env.pop('TMUX', None)
        env.pop('TMUX_PANE', None)
        launcher = home / '.local/bin/pimux'
        clients = []

        def run(command, **kwargs):
            return subprocess.run(command, env=env, capture_output=True, text=True, timeout=30, **kwargs)

        def tmux(*args, socket='pimux'):
            result = run([binary, '-L', socket, *args])
            assert result.returncode == 0, result.stderr
            return result.stdout.removesuffix('\n')

        def install():
            result = run(['/bin/bash', str(SOURCE / 'scripts/setup-tmux.sh')])
            assert result.returncode == 0, result.stdout + result.stderr

        def start():
            master, slave = os.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 140, 0, 0))
            process = subprocess.Popen([str(launcher), '-n', 'local'], env=env, cwd=home,
                                       stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
            client = (process, master, slave, bytearray())
            clients.append(client)
            return client

        def wait(condition):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if condition():
                    return
                for fd in select.select([c[1] for c in clients], [], [], .03)[0]:
                    client = next(c for c in clients if c[1] == fd)
                    client[3].extend(os.read(fd, 65536))
            pytest.fail('\n'.join(c[3].decode(errors='replace')[-1600:] for c in clients))

        def state(client):
            tty = os.ttyname(client[2])
            result = run([binary, '-L', 'pimux', 'list-clients', '-F', '#{client_name}|#{session_id}|#{window_id}|#{pane_id}'])
            if result.returncode:
                assert client[0].poll() is None, client[3].decode(errors='replace') + result.stderr
                return []
            rows = result.stdout.splitlines()
            return next((row.split('|')[1:] for row in rows if row.startswith(tty + '|')), [])

        try:
            tmux('-f', '/dev/null', 'new-session', '-d', '-s', 'sentinel', 'sleep 180', socket='untouched')
            sentinel = tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}', socket='untouched')
            install()
            config = home / '.config/pimux'
            (config / 'language').write_text('en\n')
            assert (config / 'shell.conf').read_text() == '# pimux-managed: Bash runtime\n' + bash + '\n'
            assert (config / 'runtime.conf').read_text() == binary + '\npimux\n' + binary + '\n'
            # A fresh Apple shell must recover both pinned runtimes with only
            # the system PATH, rather than inheriting the developer's toolchain.
            env.pop('PIMUX_BASH')
            env['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
            assert run([str(launcher), '--version']).returncode == 0
            first = start()
            wait(lambda: len(state(first)) == 3)
            first_view, first_window, first_pane = state(first)
            wait(lambda: tmux('show-options', '-pqv', '-t', first_pane, '@pimux_environment_ready') == 'on')
            assert tmux('show-options', '-Aqv', '-t', first_view, 'default-shell') == bash
            assert tmux('display-message', '-p', '-t', first_pane, '#{pane_current_path}') == str(home)
            os.write(first[1], b'\x01v')
            wait(lambda: len(tmux('list-panes', '-t', first_window, '-F', '#{pane_id}').splitlines()) == 2)
            second_window = tmux('new-window', '-d', '-t', '=local:', '-n', 'peer', '-P', '-F', '#{window_id}', '-c', str(home))
            second = start()
            wait(lambda: len(state(second)) == 3)
            second_view = state(second)[0]
            tmux('select-window', '-t', second_view + ':' + second_window)
            peer_pane = state(second)[2]
            wait(lambda: tmux('show-options', '-pqv', '-t', peer_pane, '@pimux_environment_ready') == 'on')
            before_second = state(second)
            os.write(first[1], b'\x01c')
            wait(lambda: state(first)[1] not in (first_window, second_window))
            assert state(second) == before_second
            first_state = state(first)
            # A mouse click selects only the second client's target window/pane.
            right = tmux('split-window', '-h', '-d', '-t', peer_pane, '-P', '-F', '#{pane_id}', '-c', str(home))
            x, y = map(int, tmux('display-message', '-p', '-t', right, '#{pane_left} #{pane_top}').split())
            os.write(second[1], f'\x1b[<0;{x + 2};{y + 2}M\x1b[<0;{x + 2};{y + 2}m'.encode())
            wait(lambda: state(second)[2] == right)
            assert state(first) == first_state
            # Snapshot the close target: switching the peer cannot retarget it.
            first[3].clear()
            os.write(first[1], b'\x01x')
            wait(lambda: b'Close this pane' in first[3])
            os.write(first[1], b'n')
            wait(lambda: tmux('list-clients', '-F', '#{client_name}:#{client_key_table}').count(':root') == 2)
            assert tmux('display-message', '-p', '-t', first_state[2], '#{pane_dead}') == '0'
            wait(lambda: tmux('show-options', '-pqv', '-t', right, '@pimux_environment_ready') == 'on')
            received = home / 'peer-input'
            command = shlex.join(['printf', '%s\\n', 'peer-only']) + ' > ' + shlex.quote(str(received))
            os.write(second[1], command.encode() + b'\r')
            wait(lambda: received.exists() and received.read_text() == 'peer-only\n')
            assert 'peer-only' not in tmux('capture-pane', '-p', '-t', first_state[2])
            before_close = set(tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}').splitlines())
            closing = tmux('display-message', '-p', '-t', first_state[2], '#{pane_id}:#{pane_pid}')
            first[3].clear()
            os.write(first[1], b'\x01x')
            wait(lambda: b'Close this pane' in first[3])
            os.write(second[1], b'\x01\x1b[D')
            wait(lambda: state(second)[2] == peer_pane)
            os.write(first[1], b'y')
            wait(lambda: closing not in tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}').splitlines())
            assert set(tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}').splitlines()) == before_close - {closing}
            assert state(second)[1:] == [second_window, peer_pane]
            # Proxy writes use the installed launcher/modern Bash from a system PATH.
            result = run([str(launcher), 'proxy', 'set', 'http://127.0.0.1:7890'])
            assert result.returncode == 0, result.stderr
            assert run([str(launcher), '__proxy-read']).stdout == 'on\nhttp://127.0.0.1:7890\n'
            assert run([str(launcher), 'proxy', 'off']).returncode == 0
            assert run([str(launcher), '__proxy-read']).stdout.startswith('off\n')
            panes = tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}')
            for client in clients:
                os.write(client[1], b'\x01d')
            wait(lambda: all(c[0].poll() is not None for c in clients))
            assert all(c[0].returncode == 0 for c in clients)
            # View cleanup changes references, so compare unique pane/process pairs.
            assert set(tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}').splitlines()) == set(panes.splitlines())
            saved_proxy = (config / 'proxy').read_bytes()
            env['PATH'] = os.environ['PATH']
            install()
            assert (config / 'proxy').read_bytes() == saved_proxy
            assert set(tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}').splitlines()) == set(panes.splitlines())
            result = run([str(launcher), 'uninstall'])
            assert result.returncode == 0, result.stderr
            assert not launcher.exists() and (config / 'proxy').read_bytes() == saved_proxy
            assert set(tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}').splitlines()) == set(panes.splitlines())
            install()
            assert launcher.is_file()
            for name, value in originals.items():
                assert (home / name).read_text().startswith(value)
            assert (home / '.tmux.conf').read_text() == originals['.tmux.conf']
            assert tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}', socket='untouched') == sentinel
        finally:
            for name in ('pimux', 'untouched'):
                run([binary, '-L', name, 'kill-server'])
            for process, master, slave, _ in clients:
                os.close(master)
                os.close(slave)
                process.wait(timeout=5)
