"""Installer contracts: fake package managers, real controlling terminals, no host writes."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import termios
import time

import pytest

SOURCE = Path(__file__).resolve().parents[1]
SETUP = SOURCE / 'scripts/setup-tmux.sh'


@pytest.fixture
def installer(tmp_path):
    tools = tmp_path / 'bin'
    tools.mkdir()
    state = tmp_path / 'state.json'
    log = tmp_path / 'commands.jsonl'
    data = dict(version='tmux 3.1c', candidate='3.4-1', after='tmux 3.4',
                package_status='install ok installed', files='/usr/bin/tmux',
                owner='tmux: /usr/bin/tmux', diversion='', live='3.1c', failure=0)
    stub = tools / 'stub'
    stub.write_text('''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
name=Path(sys.argv[0]).name
args=sys.argv[1:]
p=Path(os.environ['INSTALL_STATE']); s=json.loads(p.read_text())
with open(os.environ['INSTALL_LOG'], 'a') as f:
    f.write(json.dumps([name, *args])+'\\n')
if name in ('tmux', 'selected-tmux'):
    if args == ['-V']: print(s['version'] if name == 'selected-tmux' else s.get('path_version', s['version']))
    elif args[-1:] == ['#{version}']:
        if s['live']: print(s['live'])
        else: sys.exit(1)
    else: sys.exit(2)
elif name == 'apt-cache':
    print('  Candidate: '+s['candidate'])
elif name == 'apt-get':
    if s['failure']: sys.exit(s['failure'])
    s['version']=s['after']; p.write_text(json.dumps(s))
elif name == 'sudo':
    os.execv(str(Path(sys.argv[0]).parent/'apt-get'), ['apt-get', *args[2:]])
elif name == 'dpkg-query':
    print(s[{'-W':'package_status', '-L':'files', '-S':'owner'}[args[0]]])
elif name == 'dpkg-divert': print(s['diversion'], end='')
elif name == 'readlink':
    if args[-1] in ('/usr/bin/tmux', '/bin/tmux'): print(s.get('canonical', '/usr/bin/tmux'))
    else: os.execv('/usr/bin/readlink', ['readlink', *args])
elif name in ('infocmp', 'curl'): pass
elif name == 'pimux': pass
else: sys.exit(2)
''')
    stub.chmod(0o755)
    for name in ('tmux', 'selected-tmux', 'apt-cache', 'apt-get', 'sudo', 'dpkg-query',
                 'dpkg-divert', 'readlink', 'infocmp', 'curl'):
        (tools / name).symlink_to(stub)
    runtime = tmp_path / 'runtime.conf'
    runtime.write_text(f'{tools}/selected-tmux\ntest-installer\n{tools}/tmux\n')
    (tmp_path / '.local/bin').mkdir(parents=True)
    (tmp_path / '.local/bin/pimux').symlink_to(stub)
    env = {**os.environ, 'HOME': str(tmp_path), 'PATH': f'{tools}:/usr/bin:/bin',
           'PIMUX_RUNTIME_FILE': str(runtime), 'INSTALL_STATE': str(state),
           'INSTALL_LOG': str(log), 'TERM': 'xterm-256color'}
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)

    def run(code='install_dependencies', answer=None, managed=True, uid=0, **changes):
        data.update(changes)
        state.write_text(json.dumps(data))
        log.write_text('')
        # The selected executable lives in tmp. Test package provenance separately
        # against absolute system paths; only this boundary is injected here.
        prelude = f'source "$1"; installer_uid() {{ echo {uid}; }}; '
        if managed:
            prelude += 'apt_owns_tmux() { [[ $1 == "$EXPECTED_BINARY" ]]; }; '
        command = ['bash', '-c', prelude + code, 'test', str(SETUP)]
        child_env = {**env, 'EXPECTED_BINARY': str(tools / 'selected-tmux')}
        if answer is None:
            # setsid guarantees /dev/tty is unavailable, even when pytest has a TTY.
            return subprocess.run(command, env=child_env, text=True, capture_output=True,
                                  input='y\n', start_new_session=True, timeout=8)
        master, slave = pty.openpty()

        def controlling_terminal():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        process = subprocess.Popen(command, env=child_env, stdin=subprocess.PIPE,
                                   stdout=slave, stderr=slave, pass_fds=(slave,),
                                   preexec_fn=controlling_terminal)
        os.close(slave)
        output = bytearray()
        sent = False
        deadline = time.monotonic() + 8
        try:
            # Keep stdin a PIPE, as with curl | bash. Confirmation must use /dev/tty.
            while time.monotonic() < deadline:
                if select.select([master], [], [], .05)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                    if b'Type y to continue' in output and not sent:
                        os.write(master, answer.encode())
                        sent = True
                if process.poll() is not None:
                    # Drain already emitted output before the PTY closes.
                    continue
            assert process.poll() is not None or sent, output.decode()
            result = process.wait(timeout=2)
            return subprocess.CompletedProcess(command, result, output.decode(), '')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdin.close()
            os.close(master)

    def commands():
        return [json.loads(line) for line in log.read_text().splitlines()]

    return run, commands, tools


@pytest.mark.parametrize('version,supported', [
    ('tmux 3.1c', False), ('tmux 3.2', True), ('tmux 3.2a', True),
    ('tmux 3.4', True), ('tmux 3.10', True), ('tmux 4.0', True),
    ('', False), ('wrapper 3.4', False), ('tmux 3.2-rc1', False),
    ('tmux next-3.6', False), ('tmux 2.10', False),
])
def test_shared_tmux_version_check(version, supported):
    result = subprocess.run(['bash', '-c', 'source "$1"; pimux_tmux_version_supported "$2"',
                             'test', str(SOURCE / 'lib/tmux_compat.bash'), version])
    assert (result.returncode == 0) == supported


@pytest.mark.parametrize('answer', [None, 'n\n', '\n', 'yes\n', '\x04'])
def test_upgrade_requires_explicit_y_on_controlling_terminal(installer, answer):
    run, commands, _ = installer
    result = run(answer=answer)
    assert result.returncode != 0
    assert not any(c[0] in ('apt-get', 'sudo') for c in commands())
    if answer is None:
        assert 'No controlling terminal' in result.stdout + result.stderr
        assert 'https://raw.githubusercontent.com/2-mo/pimux/main/install.sh' in result.stderr


def test_upgrade_accepts_y_with_script_stdin_pipe(installer):
    run, commands, tools = installer
    result = run(answer='y\n')
    assert result.returncode == 0, result.stdout + result.stderr
    assert ['apt-get', 'install', '--no-remove', '-y', 'tmux=3.4-1'] in commands()
    assert 'Selected tmux: ' + str(tools / 'selected-tmux') in result.stdout
    assert commands()[-1] == ['infocmp', 'tmux-256color']


def test_nonroot_privileges_are_disclosed_before_confirmation(installer):
    run, commands, _ = installer
    result = run(answer='y\n', uid=1000)
    assert result.returncode == 0, result.stdout
    assert result.stdout.index('administrator privileges through sudo') < result.stdout.index('Type y')
    assert ['sudo', '--', 'apt-get', 'install', '--no-remove', '-y', 'tmux=3.4-1'] in commands()


@pytest.mark.parametrize('changes,diagnostic', [
    ({'candidate': '(none)'}, 'No apt candidate'),
    ({'candidate': '3.1c-1'}, 'below 3.2'),
    ({'candidate': '1:3.1c-1'}, 'below 3.2'),
    ({'version': ''}, 'Unrecognized tmux version'),
    ({'version': 'unknown 3.4'}, 'Unrecognized tmux version'),
])
def test_unusable_version_or_candidate_never_changes_packages(installer, changes, diagnostic):
    run, commands, _ = installer
    result = run(answer='y\n', **changes)
    assert result.returncode != 0
    assert diagnostic in result.stdout + result.stderr
    assert not any(c[0] in ('apt-get', 'sudo') for c in commands())


def test_custom_runtime_binary_is_not_replaced_by_path_tmux(installer):
    run, commands, tools = installer
    result = run(managed=False, path_version='tmux 3.4')
    assert result.returncode != 0
    assert 'Cannot prove that apt owns' in result.stderr
    assert str(tools / 'selected-tmux') in result.stderr
    assert not any(c[0] in ('apt-get', 'sudo', 'tmux') for c in commands())


@pytest.mark.parametrize('failure,after,diagnostic', [
    (8, 'tmux 3.4', 'Package command failed'),
    (0, 'tmux 3.1c', 'still does not meet'),
])
def test_failed_or_ineffective_upgrade_stops_installation(installer, failure, after, diagnostic):
    run, commands, _ = installer
    result = run(answer='y\n', failure=failure, after=after)
    assert result.returncode != 0
    assert diagnostic in result.stdout + result.stderr
    assert len([c for c in commands() if c[0] == 'apt-get']) == 1


@pytest.mark.parametrize('path,changes,owned', [
    ('/usr/bin/tmux', {}, True),
    ('/bin/tmux', {}, True),
    ('/usr/bin/tmux', {'files': '/bin/tmux', 'owner': 'tmux: /bin/tmux'}, True),
    ('/usr/bin/tmux', {'owner': 'tmux:arm64: /usr/bin/tmux'}, True),
    ('/usr/local/bin/tmux', {}, False),
    ('/usr/bin/tmux', {'files': '/unrelated/tmux'}, False),
    ('/usr/bin/tmux', {'canonical': '/opt/custom/tmux'}, False),
    ('/usr/bin/tmux', {'diversion': 'local diversion of /usr/bin/tmux'}, False),
    ('/usr/bin/tmux', {'owner': 'another: /usr/bin/tmux'}, False),
    ('/usr/bin/tmux', {'owner': 'tmux:arm64, another: /usr/bin/tmux'}, False),
    ('/usr/bin/tmux', {'owner': 'tmux: /usr/bin/tmux\nanother: /usr/bin/tmux'}, False),
    ('/usr/bin/tmux', {'package_status': 'deinstall ok config-files'}, False),
])
def test_apt_provenance_checks_file_list_owner_and_diversions(installer, path, changes, owned):
    run, commands, _ = installer
    result = run(code=f'apt_owns_tmux {path}', managed=False, **changes)
    assert (result.returncode == 0) == owned, result.stdout + result.stderr
    assert not any(c[0] in ('apt-get', 'sudo') for c in commands())


@pytest.mark.parametrize('live,replaced,reloaded', [
    ('3.1c', False, False), ('3.2a', False, False), ('', False, False),
    ('3.4', True, False), ('3.4', False, True),
])
def test_install_reload_keeps_old_or_replaced_servers_unchanged(installer, live, replaced, reloaded):
    run, commands, _ = installer
    result = run(code=f'configure_runtime; PIMUX_TMUX_REPLACED={str(replaced).lower()}; reload_compatible_runtime',
                 version='tmux 3.4', live=live)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (['pimux', 'reload'] in commands()) == reloaded
    assert not any('kill-server' in c or 'new-session' in c or 'source-file' in c for c in commands())
    assert 'Installed binary:' in result.stdout


def test_old_tmux_is_checked_before_missing_dependency_changes(installer):
    run, commands, _ = installer
    result = run(code='missing_dependency_packages() { echo curl; }; install_dependencies',
                 managed=False)
    assert result.returncode != 0
    assert not any(c[0] in ('apt-get', 'sudo') for c in commands())


def test_cancelled_nonroot_upgrade_never_invokes_sudo(installer):
    run, commands, _ = installer
    result = run(answer='n\n', uid=1000)
    assert result.returncode != 0
    assert not any(c[0] in ('apt-get', 'sudo') for c in commands())


def test_missing_dependencies_also_require_confirmation(installer):
    run, commands, _ = installer
    result = run(code='missing_dependency_packages() { echo curl; }; install_dependencies',
                 version='tmux 3.4')
    assert result.returncode != 0
    assert 'No controlling terminal' in result.stderr
    assert not any(c[0] in ('apt-get', 'sudo') for c in commands())


def test_failed_preflight_never_installs_assets_or_python(installer):
    run, commands, _ = installer
    result = run(code='''
        install_starship() { echo UNEXPECTED_STARSHIP; }
        install_gpu_runtime() { echo UNEXPECTED_PYTHON; }
        install_files() { echo UNEXPECTED_ASSETS; }
        main
    ''', candidate='(none)')
    assert result.returncode != 0
    assert 'UNEXPECTED_' not in result.stdout
    assert not any(c[0] in ('apt-get', 'sudo', 'pimux') for c in commands())


def test_real_distro_tmux_provenance_is_read_only():
    result = subprocess.run(['bash', '-c', 'source "$1"; apt_owns_tmux "$(type -P tmux)"',
                             'test', str(SETUP)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
