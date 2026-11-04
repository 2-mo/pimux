"""Real OpenSSH/container acceptance; a supplied fixture manifest is mandatory."""
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
import hosts
import access_preview
import ssh_discovery

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def endpoints():
    path = os.environ.get('PIMUX_SSH_FIXTURE_MANIFEST')
    if not path:
        pytest.skip('requires two explicitly started disposable SSH fixtures')
    manifest = json.loads(Path(path).read_text())
    assert len(manifest['hosts']) == 2
    assert all(row['address'] == '127.0.0.1' for row in manifest['hosts'])
    assert all(name.startswith('pimux-ssh-fixture-') for name in manifest['containers'].values())
    def docker(*args):
        binary = os.environ.get('PIMUX_FIXTURE_DOCKER', 'docker')
        result = subprocess.run([binary, *args], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        return result.stdout
    def mode(value):
        docker('exec', manifest['containers']['beta'], 'python3', '-c',
               'from pathlib import Path; import sys; Path("/tmp/fixture-mode").write_text(sys.argv[1])', value)
    def panes():
        return {(name, socket): docker('exec', name, 'runuser', '-u', 'fixture', '--', 'tmux', '-L', socket,
                             'list-panes', '-a', '-F', '#{session_name}|#{window_id}|#{pane_id}|#{pane_pid}')
                for name in manifest['containers'].values() for socket in ('pimux', 'untouched')}
    before = panes()
    mode('normal')
    try:
        yield manifest, mode, docker
    finally:
        mode('normal')
        assert panes() == before


def fetch(rows): return asyncio.run(hosts.aggregate(rows))


def test_two_real_servers_keep_duplicate_sessions_and_resources_separate(endpoints, tmp_path):
    manifest, _, _ = endpoints
    rows = fetch(manifest['hosts'])
    assert [row['status'] for row in rows] == ['connected', 'connected'], rows
    assert len({row['snapshot']['node_id'] for row in rows}) == 2
    for row in rows:
        caps = row['snapshot']['capabilities']
        assert caps['sessions']['data'] == [{'id': '$0', 'name': 'shared', 'windows': 1}]
        assert caps['resources']['status'] == caps['network']['status'] == 'available'
        assert caps['gpu']['status'] == 'unavailable'
    rendered = hosts.render(rows)
    assert 'alpha/pimux/$0 shared' in rendered and 'beta/pimux/$0 shared' in rendered
    config = tmp_path / 'hosts.json'
    config.write_text(json.dumps({'version': 1, 'hosts': manifest['hosts']}))
    result = subprocess.run([sys.executable, str(ROOT / 'lib/hosts.py'), '--config', str(config),
                             'inspect', 'alpha', 'beta', '--json'], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr + result.stdout
    assert [row['host_id'] for row in json.loads(result.stdout)['hosts']] == ['alpha', 'beta']


@pytest.mark.parametrize('fault', ['version', 'bad_data', 'pollution', 'flood', 'stderr_flood', 'huge_number'])
def test_real_ssh_rejects_protocol_faults_without_losing_the_healthy_host(endpoints, fault):
    manifest, mode, _ = endpoints
    mode(fault)
    rows = fetch(manifest['hosts'])
    assert rows[0]['status'] == 'connected', rows
    assert rows[1]['status'] == 'protocol_error' and rows[1]['snapshot'] is None, rows


def test_real_timeout_isolated_from_other_host_and_permission_is_explicit(endpoints):
    manifest, mode, _ = endpoints
    mode('timeout')
    start = time.monotonic()
    rows = fetch([manifest['hosts'][0], {**manifest['hosts'][1], 'timeout': 1}])
    assert time.monotonic() - start < 4
    assert [row['status'] for row in rows] == ['connected', 'timeout'], rows
    mode('denied')
    rows = fetch(manifest['hosts'])
    assert [row['status'] for row in rows] == ['connected', 'connected'], rows
    assert rows[1]['snapshot']['capabilities']['sessions']['status'] == 'permission_denied'
    assert rows[1]['snapshot']['capabilities']['network']['status'] == 'available'


def test_real_host_key_and_node_identity_mismatch_are_rejected_without_writes(endpoints, tmp_path):
    manifest, _, _ = endpoints
    empty = tmp_path / 'unknown_hosts'
    empty.write_text('')
    bad = {**manifest['hosts'][1], 'known_hosts': str(empty)}
    rows = fetch([manifest['hosts'][0], bad])
    assert [row['status'] for row in rows] == ['connected', 'host_key_error'], rows
    assert empty.read_bytes() == b'' and list(tmp_path.iterdir()) == [empty]
    first_key = Path(manifest['hosts'][0]['known_hosts']).read_text().splitlines()[0].split(' ', 1)[1]
    wrong = f'[127.0.0.1]:{manifest["hosts"][1]["port"]} {first_key}\n'
    empty.write_text(wrong)
    rows = fetch([manifest['hosts'][0], bad])
    assert [row['status'] for row in rows] == ['connected', 'host_key_error'], rows
    assert empty.read_text() == wrong
    bad = {**manifest['hosts'][1], 'node_id': '0' * 32}
    rows = fetch([manifest['hosts'][0], bad])
    assert [row['status'] for row in rows] == ['connected', 'identity_mismatch'], rows


def test_real_cancellation_reaps_client_and_bounded_remote_query(endpoints, tmp_path):
    manifest, mode, docker = endpoints
    mode('slow_query')
    name = manifest['containers']['beta']
    docker('exec', name, 'rm', '-f', '/tmp/slow-query-pid')
    config = tmp_path / 'hosts.json'
    config.write_text(json.dumps({'version': 1, 'hosts': manifest['hosts']}))
    process = subprocess.Popen([sys.executable, str(ROOT / 'lib/hosts.py'), '--config', str(config),
                                'inspect', 'beta'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        pid = ''
        while time.monotonic() < deadline:
            pid = docker('exec', name, 'python3', '-c',
                         'from pathlib import Path; p=Path("/tmp/slow-query-pid"); print(p.read_text() if p.exists() else "")').strip()
            if pid: break
            time.sleep(.05)
        assert pid.isdigit(), process.communicate(timeout=2)
        children = subprocess.run(['pgrep', '-P', str(process.pid)], capture_output=True, text=True).stdout.split()
        assert children
        process.send_signal(signal.SIGTERM)
        _, error = process.communicate(timeout=3)
        assert process.returncode == 143, error
        for child in children:
            with pytest.raises(ProcessLookupError): os.kill(int(child), 0)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            alive = docker('exec', name, 'python3', '-c',
                           'from pathlib import Path; import sys; print(Path("/proc", sys.argv[1]).exists())', pid).strip()
            if alive == 'False': break
            time.sleep(.1)
        assert alive == 'False'
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=3)


def test_disconnected_endpoint_does_not_hide_the_other_server(endpoints):
    manifest, mode, _ = endpoints
    # A real SSH channel closes without a snapshot. Unlike an unlistened local
    # socket, this has the same deterministic meaning on macOS and Linux.
    mode('disconnect')
    rows = fetch(manifest['hosts'])
    assert rows[0]['status'] == 'connected' and rows[1]['status'] == 'ssh_error', rows


def test_existing_ssh_aliases_and_include_work_without_reentering_connection_details(endpoints, tmp_path):
    manifest, _, _ = endpoints
    include = tmp_path / 'hosts included.conf'
    include.write_text(''.join(f'Host {row["host_id"]}_alias\n HostName 127.0.0.1\n Port {row["port"]}\n'
                              for row in manifest['hosts']))
    original = (f'Include {json.dumps(str(include))}\nHost *\n User fixture\n'
                f' IdentityFile {json.dumps(manifest["hosts"][0]["identity_file"])}\n'
                f' UserKnownHostsFile {json.dumps(manifest["hosts"][0]["known_hosts"])}\n'
                ' GlobalKnownHostsFile /dev/null\n StrictHostKeyChecking yes\n BatchMode yes\n IdentitiesOnly yes\n IdentityAgent none\n')
    config = tmp_path / 'ssh config'
    config.write_text(original)
    rows = [ssh_discovery.resolve_alias(alias, [config]) for alias in ('alpha_alias', 'beta_alias')]
    result = fetch(rows)
    assert [row['status'] for row in result] == ['connected', 'connected'], result
    assert len({row['snapshot']['node_id'] for row in result}) == 2
    assert all(row['host_key'] and row['snapshot']['account']['name'] == 'fixture' for row in result)
    assert config.read_text() == original
    command = subprocess.run([sys.executable, str(ROOT / 'lib/hosts.py'), '--ssh-config', str(config),
                              'inspect', 'alpha_alias', 'beta_alias', '--json'], capture_output=True, text=True, timeout=15)
    assert command.returncode == 0, command.stderr + command.stdout


@pytest.mark.parametrize('gateway_key', ['known', 'unknown', 'wrong', 'two_jumps', 'cancel'])
def test_real_proxyjump_uses_openssh_configuration_and_verified_keys(endpoints, tmp_path, monkeypatch, gateway_key):
    manifest, mode, docker = endpoints
    alpha, beta = manifest['containers']['alpha'], manifest['containers']['beta']
    beta_ip = docker('inspect', '-f', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', beta).strip()
    alpha_ip = docker('inspect', '-f', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', alpha).strip()
    public = ' '.join(docker('exec', beta, 'cat', '/fixture/host_key.pub').split()[:2])
    known = tmp_path / 'jump known_hosts'
    gateway_entries = Path(manifest['hosts'][0]['known_hosts']).read_text()
    if gateway_key == 'unknown': gateway_entries = ''
    elif gateway_key == 'wrong': gateway_entries = f'[127.0.0.1]:{manifest["hosts"][0]["port"]} {public}\n'
    known.write_text(gateway_entries + f'[{beta_ip}]:2222 {public}\n')
    if gateway_key == 'two_jumps':
        alpha_public = ' '.join(docker('exec', alpha, 'cat', '/fixture/host_key.pub').split()[:2])
        with known.open('a') as stream: stream.write(f'[{alpha_ip}]:2222 {alpha_public}\n')
    known_before = known.read_bytes()
    marker, control = tmp_path / 'local-command-fired', tmp_path / 'persistent-control'
    config = tmp_path / 'jump config'
    config.write_text(f'Host gateway\n HostName 127.0.0.1\n Port {manifest["hosts"][0]["port"]}\n'
        f' StrictHostKeyChecking no\n UpdateHostKeys yes\n PermitLocalCommand yes\n LocalCommand touch {marker}\n'
        f' ControlMaster auto\n ControlPersist 600\n ControlPath {control}\n'
        f'Host target\n HostName {beta_ip}\n Port 2222\n ProxyJump gateway\n'
        f'Host *\n User fixture\n IdentityFile {json.dumps(manifest["hosts"][0]["identity_file"])}\n'
        f' UserKnownHostsFile {json.dumps(str(known))}\n GlobalKnownHostsFile /dev/null\n'
        ' StrictHostKeyChecking yes\n BatchMode yes\n IdentitiesOnly yes\n IdentityAgent none\n')
    if gateway_key == 'two_jumps':
        config.write_text(config.read_text().replace('ProxyJump gateway\n', 'ProxyJump gateway,second_gateway\n') +
                          f'Host second_gateway\n HostName {alpha_ip}\n Port 2222\n StrictHostKeyChecking no\n')
    change = ('from pathlib import Path; import os,signal,sys; p=Path("/etc/ssh/sshd_config"); '
              's=p.read_text(); p.write_text(s.replace("AllowTcpForwarding no", "AllowTcpForwarding local") + "\\nPermitOpen " + sys.argv[1] + ":2222\\n"); '
              'os.kill(int(Path("/run/sshd/fixture.pid").read_text()), signal.SIGHUP)')
    original = docker('exec', alpha, 'cat', '/etc/ssh/sshd_config')
    traces = []
    exchange = hosts.exchange
    async def capture(*args, **kwargs):
        result = await exchange(*args, **kwargs)
        traces.append(result[2].decode(errors='replace'))
        return result
    monkeypatch.setattr(hosts, 'exchange', capture)
    try:
        permits = beta_ip if gateway_key != 'two_jumps' else beta_ip + ':2222 ' + alpha_ip
        docker('exec', alpha, 'python3', '-c', change, permits)
        host = ssh_discovery.resolve_alias('target', [config])
        if gateway_key == 'cancel':
            mode('slow_query')
            docker('exec', beta, 'rm', '-f', '/tmp/slow-query-pid')
            process = subprocess.Popen([sys.executable, str(ROOT / 'lib/hosts.py'), '--ssh-config', str(config),
                                        'inspect', 'target'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    pid = docker('exec', beta, 'python3', '-c',
                        'from pathlib import Path; p=Path("/tmp/slow-query-pid"); print(p.read_text() if p.exists() else "")').strip()
                    if pid: break
                    time.sleep(.05)
                assert pid.isdigit()
                table = subprocess.run(['ps', '-axo', 'pid=,ppid='], capture_output=True, text=True, check=True).stdout
                edges = [tuple(map(int, line.split())) for line in table.splitlines()]
                descendants = {process.pid}
                for _ in range(8): descendants |= {child for child, parent in edges if parent in descendants}
                descendants.remove(process.pid)
                assert len(descendants) >= 2
                process.terminate()
                _, error = process.communicate(timeout=3)
                assert process.returncode == 143, error
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    alive = []
                    for child in descendants:
                        try: os.kill(child, 0); alive.append(child)
                        except ProcessLookupError: pass
                    if not alive: break
                    time.sleep(.05)
                assert not alive
            finally:
                if process.poll() is None: process.kill(); process.communicate(timeout=3)
            return
        row = asyncio.run(hosts.fetch_host(host))
        if gateway_key in {'known', 'two_jumps'}:
            assert row['status'] == 'connected', (row, '\n'.join(traces))
            assert row['snapshot']['node_id'] == manifest['hosts'][1]['node_id']
            assert row['host_key']['fingerprint'] == asyncio.run(hosts.fetch_host(manifest['hosts'][1]))['host_key']['fingerprint']
        else: assert row['status'] == 'host_key_error' and row['snapshot'] is None, row
        assert known.read_bytes() == known_before
        assert not marker.exists() and not control.exists()
    finally:
        docker('exec', alpha, 'python3', '-c',
               'from pathlib import Path; import os,signal,sys; Path("/etc/ssh/sshd_config").write_text(sys.argv[1]); os.kill(int(Path("/run/sshd/fixture.pid").read_text()),signal.SIGHUP)', original)


def test_real_public_key_preview_is_idempotent_read_only_and_verifies_target(endpoints, tmp_path):
    manifest, _, docker = endpoints
    host = manifest['hosts'][0]
    name = manifest['containers']['alpha']
    before = docker('exec', name, 'cat', '/home/fixture/.ssh/authorized_keys')
    public = Path(host['identity_file'] + '.pub')
    for _ in range(2):
        result = asyncio.run(access_preview.preview(host, public, home=tmp_path))
        assert result['status'] == 'already_listed', result
        assert result['connection']['host_key'] and not result['writes_supported']
        assert not result['requires_write_confirmation']
        assert result['connection']['snapshot']['account']['name'] == 'fixture'
    other = tmp_path / 'proposed_key'
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(other)], check=True)
    missing = asyncio.run(access_preview.preview(host, Path(str(other) + '.pub'), home=tmp_path))
    assert missing['status'] == 'authorization_missing' and missing['requires_write_confirmation']
    assert not missing['writes_supported']
    assert docker('exec', name, 'cat', '/home/fixture/.ssh/authorized_keys') == before


def test_remote_stderr_cannot_forge_verified_host_fingerprint(endpoints, monkeypatch):
    manifest, mode, _ = endpoints
    expected = asyncio.run(hosts.fetch_host(manifest['hosts'][1]))['host_key']
    assert expected
    mode('forged_stderr')
    captured = []
    exchange = hosts.exchange
    async def capture(*args, **kwargs):
        result = await exchange(*args, **kwargs)
        captured.append(result[2])
        return result
    monkeypatch.setattr(hosts, 'exchange', capture)
    row = asyncio.run(hosts.fetch_host(manifest['hosts'][1]))
    assert b'SHA256:BBBBBBBB' in b''.join(captured)
    assert row['status'] == 'connected' and row['host_key'] == expected


def test_unreachable_listener_is_bounded_and_keeps_the_healthy_snapshot(endpoints):
    import socket
    manifest, _, _ = endpoints
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
        start = time.monotonic()
        rows = fetch([manifest['hosts'][0], {**manifest['hosts'][1], 'port':port, 'timeout':1}])
    assert time.monotonic() - start < 3
    assert rows[0]['status'] == 'connected' and rows[0]['snapshot'] is not None
    # Linux refuses this port immediately; the tested Darwin stack may time out.
    assert rows[1]['status'] in {'ssh_error', 'timeout'} and rows[1]['snapshot'] is None
