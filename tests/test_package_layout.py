"""A packaged installation must not depend on copied files in the user's home."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time


SOURCE = Path(__file__).resolve().parents[1]


def test_package_shell_resources_and_stable_helpers(tmp_path):
    home = Path(os.environ['HOME'])
    personal = home / '.config/pimux'
    personal.mkdir(parents=True)
    preserved = personal / 'shell.bash'
    preserved.write_text('printf BAD_PERSONAL_RESOURCE; exit 41\n')
    original = preserved.read_bytes()
    prefix = tmp_path / 'package "quoted"'
    installed = prefix / 'Cellar/pimux-preview/0.10.1/libexec'
    installed.mkdir(parents=True)
    for name in ['bin', 'lib', 'config']:
        shutil.copytree(SOURCE / name, installed / name)
    (installed / '.venv/bin').mkdir(parents=True)
    (installed / '.venv/bin/python').symlink_to(sys.executable)
    opt = prefix / 'opt/pimux-preview'
    opt.parent.mkdir()
    opt.symlink_to(installed.parent)
    launcher = opt / 'libexec/bin/pimux'
    bash, tmux = shutil.which('bash'), shutil.which('tmux')
    assert bash and tmux
    with tempfile.TemporaryDirectory(prefix='pimux-pkg-', dir='/tmp') as sockets:
        env = {**os.environ, 'TMUX_TMPDIR': sockets, 'PIMUX_BASH': bash,
               'TERM': 'xterm-256color'}

        def run(argv):
            return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=10)

        def tm(*args):
            return run([tmux, '-L', 'pimux', *args])

        try:
            command = f'source {shlex.quote(str(launcher))}; configure_runtime; ensure_session packaged'
            result = run([bash, '-c', command])
            assert result.returncode == 0, result.stdout + result.stderr
            root = result.stdout.strip()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                ready = tm('show-options', '-pqv', '-t', root + ':', '@pimux_environment_ready')
                if ready.stdout.strip() == 'on':
                    break
                time.sleep(.03)
            assert ready.stdout.strip() == 'on', tm('capture-pane', '-p', '-t', root + ':').stdout
            helper = tm('show-options', '-qv', '-t', root, '@pimux_launcher').stdout.strip()
            assert helper == str(launcher), 'helpers must retain the stable opt path'
            assert str(opt / 'libexec/lib/shell.bash') in tm(
                'show-options', '-qv', '-t', root, 'default-command').stdout
            assert run([str(launcher), 'hosts', '--help']).returncode == 0
            assert preserved.read_bytes() == original

            # Keep the original Bash alive through an opt switch and removal of
            # its starting keg. A newly launched helper cannot cover this case.
            pane = tm('display-message', '-p', '-t', root + ':', '#{pane_id}').stdout.strip()
            pid = tm('display-message', '-p', '-t', pane, '#{pane_pid}').stdout.strip()

            def shell_snapshot(name):
                output = home / name
                command = ("{ printf 'PID=%s\\nVALUE=%s\\nRUNTIME=%s\\n' "
                           '"$BASHPID" "${PACKAGE_SAMPLE-}" "$PIMUX_RUNTIME_DIR"; '
                           'pimux_host_python signature "$HOME/.config/pimux/environment.json"; '
                           "printf 'STATUS=%s\\nDONE\\n' \"$?\"; } > "
                           + shlex.quote(str(output)) + ' 2>&1')
                # The no-op returns to the real prompt hook before we inspect
                # the shell; do not source new files or call apply explicitly.
                assert tm('send-keys', '-t', pane, ':', 'Enter').returncode == 0
                assert tm('send-keys', '-t', pane, '-l', command).returncode == 0
                assert tm('send-keys', '-t', pane, 'Enter').returncode == 0
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if output.exists() and output.read_text().endswith('DONE\n'):
                        return output.read_text()
                    time.sleep(.03)
                raise AssertionError(tm('capture-pane', '-p', '-t', pane).stdout)

            assert run([str(launcher), 'env', 'set', 'PACKAGE_SAMPLE', 'before']).returncode == 0
            before = shell_snapshot('before-upgrade')
            assert f'PID={pid}\nVALUE=before\n' in before and 'STATUS=0\n' in before
            upgraded = installed.parent.with_name('0.10.1_2')
            shutil.copytree(installed.parent, upgraded, symlinks=True)
            replacement = opt.with_name('pimux-next')
            replacement.symlink_to(upgraded)
            replacement.replace(opt)
            shutil.rmtree(installed.parent)
            assert not installed.exists()
            assert run([str(launcher), 'env', 'set', 'PACKAGE_SAMPLE', 'after-upgrade']).returncode == 0
            after = shell_snapshot('after-upgrade')
            assert f'PID={pid}\nVALUE=after-upgrade\n' in after, after
            assert f'RUNTIME={opt}/libexec/lib\n' in after, after
            assert 'STATUS=0\n' in after, after
            assert tm('display-message', '-p', '-t', pane, '#{pane_pid}').stdout.strip() == pid
            assert preserved.read_bytes() == original
        finally:
            tm('kill-server')


def test_homebrew_managed_commands_never_remove_source_launcher(tmp_path):
    root = tmp_path / 'packaged'
    for name in ['bin', 'lib', 'config', 'scripts']:
        shutil.copytree(SOURCE / name, root / name)
    (root / '.pimux-homebrew').write_text('pimux-preview\n')
    personal = Path(os.environ['HOME']) / '.local/bin/pimux'
    personal.parent.mkdir(parents=True)
    personal.write_text('# pimux-managed: original source installation\n')
    env = {**os.environ, 'PIMUX_BASH': shutil.which('bash')}
    for command in ['update', 'uninstall']:
        result = subprocess.run([str(root / 'bin/pimux'), command], env=env,
                                text=True, capture_output=True, timeout=5)
        assert result.returncode == 2
        assert 'brew ' in result.stderr
        assert personal.read_text() == '# pimux-managed: original source installation\n'
