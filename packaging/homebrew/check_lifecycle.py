#!/usr/bin/env python3
"""Exercise an existing task-only Homebrew preview installation through upgrade/removal."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import signal
import shutil
import struct
import subprocess
import tempfile
import termios
import time

from render import render


def check(base, archive, commit, revision):
    base = base.resolve(strict=True)
    prefix = base / 'brew'
    settings = json.loads((base / 'env.json').read_text())
    for key in ['HOME', 'HOMEBREW_CACHE', 'HOMEBREW_LOGS', 'HOMEBREW_TEMP']:
        if not Path(settings[key]).resolve().is_relative_to(base):
            raise ValueError(f'Test {key} must remain inside its dedicated environment')
    if prefix.resolve() in (Path('/opt/homebrew'), Path('/usr/local')):
        raise ValueError('Refusing a user/system Homebrew prefix')
    env = {**os.environ, **settings}
    brew, launcher, tmux = prefix / 'bin/brew', prefix / 'bin/pimux', prefix / 'opt/tmux/bin/tmux'
    assert subprocess.check_output([str(brew), '--prefix'], env=env, text=True).strip() == str(prefix)
    old_keg = (prefix / 'opt/pimux-preview').resolve(strict=True)
    home = base / f'lifecycle-home-r{revision}'
    home.mkdir()  # Refuse to repeat a run with an uncertain previous outcome.
    files = {'.bashrc': '# personal Bash\n', '.zshrc': '# personal Zsh\n',
             '.local/bin/pimux': '# pimux-managed: original source launcher\n',
             '.config/pimux/language': 'en\n'}
    for name, value in files.items():
        path = home / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)
    baseline = {name: hashlib.sha256((home / name).read_bytes()).hexdigest() for name in files}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'), TERM='xterm-256color')
    env.pop('TMUX', None); env.pop('TMUX_PANE', None)
    clients = []
    result = {'source_commit': commit, 'source_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
              'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'package_revision': revision, 'old_keg': str(old_keg), 'steps': []}
    log = (base / 'evidence' / f'lifecycle-r{revision}.log').open('w')

    def command(argv, timeout=30):
        p = subprocess.run([str(a) for a in argv], env=env, text=True, capture_output=True, timeout=timeout)
        log.write(json.dumps([str(a) for a in argv]) + '\n' + p.stdout + p.stderr); log.flush()
        if p.returncode:
            raise RuntimeError(f'Command failed ({p.returncode}): {argv}; see lifecycle log')
        return p.stdout.strip()

    def tm(*args, socket='pimux'):
        return command([tmux, '-L', socket, *args])

    def wait(condition, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition(): return
            for fd in select.select([c['master'] for c in clients], [], [], .03)[0]:
                client = next(c for c in clients if c['master'] == fd)
                try: data = os.read(fd, 65536)
                except OSError: data = b''
                client['output'].extend(data)
                if len(client['output']) > 131072: del client['output'][:-65536]
        raise TimeoutError('Terminal checkpoint not reached; output saved in the evidence directory')

    def start():
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 140, 0, 0))
        p = subprocess.Popen([str(launcher), '-n', 'lifecycle'], env=env, cwd=home,
                             stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        client = {'process': p, 'master': master, 'slave': slave, 'tty': os.ttyname(slave), 'output': bytearray()}
        clients.append(client)
        return client

    def state(client):
        p = subprocess.run([str(tmux), '-L', 'pimux', 'list-clients', '-F',
                            '#{client_name}|#{session_id}|#{window_id}|#{pane_id}'],
                           env=env, capture_output=True, text=True, timeout=5)
        if p.returncode:
            if client.get('connected') or client['process'].poll() is not None:
                raise RuntimeError('Client/server exited: ' + p.stderr)
            return []
        for row in p.stdout.splitlines():
            if row.startswith(client['tty'] + '|'):
                client['connected'] = True
                return row.split('|')[1:]
        return []

    def panes():
        return set(tm('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}').splitlines())

    def originals():
        return {name: hashlib.sha256((home / name).read_bytes()).hexdigest() for name in files}

    with tempfile.TemporaryDirectory(prefix='pmb-life-', dir='/tmp') as sockets:
        env['TMUX_TMPDIR'] = sockets
        try:
            tm('-f', '/dev/null', 'new-session', '-d', '-s', 'sentinel', 'sleep 600', socket='sentinel')
            sentinel = tm('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}', socket='sentinel')
            first = start(); wait(lambda: len(state(first)) == 3)
            window = tm('new-window', '-d', '-t', '=lifecycle:', '-n', 'peer', '-P', '-F', '#{window_id}')
            second = start(); wait(lambda: len(state(second)) == 3)
            tm('select-window', '-t', state(second)[0] + ':' + window)
            before_second = state(second)
            before_first = state(first)
            os.write(first['master'], b'\x01c')
            wait(lambda: state(first)[1] != before_first[1])
            assert state(second) == before_second
            result['steps'].append('two clients keep distinct window targets')

            shell_pane = state(first)[2]
            wait(lambda: tm('show-options', '-pqv', '-t', shell_pane, '@pimux_environment_ready') == 'on')
            shell_pid = tm('display-message', '-p', '-t', shell_pane, '#{pane_pid}')

            def shell_snapshot(name):
                output = home / name
                script = ("{ printf 'PID=%s\\nVALUE=%s\\nRUNTIME=%s\\n' "
                          '"$BASHPID" "${PACKAGE_SAMPLE-}" "$PIMUX_RUNTIME_DIR"; '
                          'pimux_host_python signature "$HOME/.config/pimux/environment.json"; '
                          "printf 'STATUS=%s\\nDONE\\n' \"$?\"; } > "
                          + shlex.quote(str(output)) + ' 2>&1')
                # Let the already loaded prompt hook run. Never replace this
                # with sourcing the new rc or launching a fresh helper shell.
                os.write(first['master'], b':\r' + script.encode() + b'\r')
                wait(lambda: output.exists() and output.read_text().endswith('DONE\n'))
                return output.read_text()

            command([launcher, 'env', 'set', 'PACKAGE_SAMPLE', 'before'])
            shell_before = shell_snapshot('shell-before-upgrade')
            assert f'PID={shell_pid}\nVALUE=before\n' in shell_before and 'STATUS=0\n' in shell_before
            result['old_shell_before'] = shell_before
            before = panes()
            formula = prefix / 'Library/Taps/pimux/homebrew-preview/Formula/pimux-preview.rb'
            manifest = render(archive, commit, revision, formula)
            result['formula_sha256'] = manifest['formula_sha256']
            command([brew, 'upgrade', '--formula', 'pimux/preview/pimux-preview'], timeout=180)
            new_keg = (prefix / 'opt/pimux-preview').resolve(strict=True)
            assert new_keg != old_keg
            assert (new_keg / 'libexec/source-commit').read_text().strip() == commit
            assert panes() == before and originals() == baseline
            command([brew, 'cleanup', '--prune=all', 'pimux-preview'], timeout=60)
            assert not old_keg.exists()
            result['steps'].append('real brew upgrade and old-keg cleanup preserve programs and original files')

            command([launcher, 'env', 'set', 'PACKAGE_SAMPLE', 'after-upgrade'])
            shell_after = shell_snapshot('shell-after-upgrade')
            result['old_shell_after'] = shell_after
            assert f'PID={shell_pid}\nVALUE=after-upgrade\n' in shell_after, shell_after
            assert f'RUNTIME={prefix}/opt/pimux-preview/libexec/lib\n' in shell_after, shell_after
            assert 'STATUS=0\n' in shell_after, shell_after
            assert tm('display-message', '-p', '-t', shell_pane, '#{pane_pid}') == shell_pid
            assert panes() == before and originals() == baseline
            result['steps'].append('same pre-upgrade shell PID refreshes environment and platform helper after cleanup')

            helper = tm('show-options', '-qv', '-t', state(first)[0], '@pimux_launcher')
            assert '/opt/pimux-preview/' in helper and '/Cellar/' not in helper
            command([helper, 'hosts', 'discover', '--json'])
            before_second = state(second)
            first['output'].clear()
            os.write(first['master'], b'\x01/')
            wait(lambda: b'Help' in first['output'])
            os.write(first['master'], b'q')
            wait(lambda: state(second) == before_second)
            assert panes() == before
            result['steps'].append('existing client help popup and Python helper work after old keg removal')

            command([brew, 'uninstall', '--formula', 'pimux/preview/pimux-preview'], timeout=60)
            assert not launcher.exists()
            assert panes() == before and originals() == baseline
            assert tm('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}', socket='sentinel') == sentinel
            result['steps'].append('real uninstall preserves running panes, source launcher and sentinel server')
            command([brew, 'install', '--formula', 'pimux/preview/pimux-preview'], timeout=180)
            assert originals() == baseline
            result['steps'].append('reinstall restores package without overwriting original files')
            result.update(success=True, new_keg=str(new_keg), original_file_hashes=baseline)
        finally:
            # Only sockets created inside this context are eligible for cleanup.
            for socket in ['pimux', 'sentinel']:
                subprocess.run([str(tmux), '-L', socket, 'kill-server'], env=env, capture_output=True, timeout=5)
            try: wait(lambda: all(c['process'].poll() is not None for c in clients), timeout=3)
            except TimeoutError:
                for client in clients:
                    if client['process'].poll() is None:
                        os.killpg(client['process'].pid, signal.SIGTERM)
                        client['process'].wait(timeout=3)
            # An early failure may race a launching client's server creation.
            # Its process group has now exited; remove only this run's sockets again.
            for socket in ['pimux', 'sentinel']:
                subprocess.run([str(tmux), '-L', socket, 'kill-server'], env=env, capture_output=True, timeout=5)
            for i, client in enumerate(clients):
                (base / 'evidence' / f'lifecycle-r{revision}-client-{i}.terminal').write_bytes(client['output'])
                os.close(client['master']); os.close(client['slave'])
            log.close()
            result['owned_servers_stopped'] = True
            (base / 'evidence' / f'lifecycle-r{revision}.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', type=Path)
    parser.add_argument('archive', type=Path)
    parser.add_argument('commit')
    parser.add_argument('--revision', type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.environment, args.archive, args.commit, args.revision), indent=2))
