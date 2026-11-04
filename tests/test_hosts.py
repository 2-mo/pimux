"""Read-only host identity, strict protocol, configuration and process boundaries."""
import asyncio
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

import hosts
import host_snapshot

ROOT = Path(__file__).resolve().parents[1]


def entry(tmp_path, host_id='alpha'):
    known = tmp_path / 'known hosts'
    known.touch()
    return dict(host_id=host_id, name='测试 ' + host_id, address='127.0.0.1', port=2222,
                user='pimux', node_id='a' * 32, known_hosts=str(known), identity_file=None,
                socket='pimux', timeout=3)


def snapshot(host, nonce='f' * 32):
    return dict(protocol='pimux.snapshot', version=1, request_id=nonce,
                host_id=host['host_id'], node_id=host['node_id'], hostname='fixture',
                platform='linux', socket=host['socket'],
                account={'name': 'fixture', 'uid': 1000},
                capabilities={name: dict(status='available', reason='', data=data) for name, data in {
                    'sessions': [{'id': '$0', 'name': 'shared\nname', 'windows': 1}],
                    'resources': {'load': [0., 0., 0.], 'memory_total_kib': 10, 'memory_available_kib': 5},
                    'network': [{'name': 'lo', 'addresses': ['127.0.0.1/8']}],
                    'gpu': []}.items()})


def test_round_trip_keeps_host_identity_and_literal_session_names(tmp_path):
    host = entry(tmp_path)
    data = snapshot(host)
    assert hosts.decode_snapshot(host_snapshot.frame(data), host, 'f' * 32) == data


@pytest.mark.parametrize('mutation', ['prefix', 'suffix', 'version', 'request', 'host', 'node', 'socket',
                                      'capability', 'wrong_type', 'duplicate', 'nan', 'oversize'])
def test_untrusted_output_is_rejected_as_a_whole(tmp_path, mutation):
    host = entry(tmp_path)
    data = snapshot(host)
    if mutation in {'version', 'request', 'host', 'node', 'socket'}:
        key = {'request': 'request_id', 'host': 'host_id', 'node': 'node_id'}.get(mutation, mutation)
        data[key] = 99 if key == 'version' else 'incorrect'
    if mutation == 'capability':
        data['capabilities']['gpu']['status'] = 'probably okay'
    if mutation == 'wrong_type':
        data['capabilities']['sessions']['data'][0]['windows'] = True
    wire = host_snapshot.frame(data)
    if mutation == 'prefix': wire = b'welcome\n' + wire
    if mutation == 'suffix': wire += b'logout\n'
    if mutation == 'oversize': wire = b'x' * (hosts.MAX_OUTPUT + 1)
    if mutation in {'duplicate', 'nan'}:
        body = json.dumps(data).encode()
        body = body.replace(b'"version": 1', b'"version": 1, "version": 1') if mutation == 'duplicate' else body.replace(b'0.0', b'NaN', 1)
        wire = b'PIMUX-SNAPSHOT/1 ' + str(len(body)).encode() + b'\n' + body + b'\n'
    with pytest.raises(hosts.ProtocolError):
        hosts.decode_snapshot(wire, host, 'f' * 32)


def test_configuration_is_explicit_atomic_and_preserves_unrelated_files(tmp_path):
    path = tmp_path / 'config/hosts.json'
    host = entry(tmp_path)
    hosts.add_host(path, host)
    assert hosts.read_config(path) == [host]
    assert path.stat().st_mode & 0o777 == 0o600
    original = path.read_bytes()
    with pytest.raises(ValueError): hosts.add_host(path, host)
    assert path.read_bytes() == original
    unrelated = tmp_path / 'unrelated'
    unrelated.write_text('personal content')
    path.unlink()
    path.symlink_to(unrelated)
    with pytest.raises(ValueError): hosts.add_host(path, host)
    assert unrelated.read_text() == 'personal content'


@pytest.mark.parametrize('field,value', [('host_id', '../alpha'), ('address', '-oProxyCommand=bad'),
    ('address', 'host; touch x'), ('user', 'x@host'), ('socket', '../default'), ('port', True),
    ('timeout', float('nan')), ('timeout', 10**400), ('node_id', 'unverified'), ('name', '\x1b[2J'), ('known_hosts', '/tmp/%h')])
def test_configuration_rejects_ambiguous_or_executable_values(tmp_path, field, value):
    host = entry(tmp_path)
    host[field] = value
    with pytest.raises(ValueError): hosts.validate_host(host)


def test_ssh_boundary_does_not_import_user_configuration_or_disable_host_keys(tmp_path):
    host = entry(tmp_path)
    host['socket'] = 'explicit_fixture_socket'
    argv = hosts.ssh_command(host)
    assert argv[:4] == ['/usr/bin/ssh', '-F', '/dev/null', '-T']
    for option in ['StrictHostKeyChecking=yes', 'UpdateHostKeys=no', 'ForwardAgent=no',
                   'ClearAllForwardings=yes', 'PermitLocalCommand=no', 'ControlPath=none',
                   'ProxyCommand=none', 'ProxyJump=none', 'IdentityFile=none']:
        assert option in argv
    assert argv[-1] == hosts.REMOTE_COMMAND
    assert host['host_id'] not in argv[-1] and host['socket'] not in argv[-1]
    assert 'GlobalKnownHostsFile=/dev/null' in argv


def test_collector_reports_capabilities_separately_and_does_not_mask_permission_errors(monkeypatch):
    def query(args):
        if args[0] == 'tmux': raise host_snapshot.CapabilityError('permission_denied', 'permission_denied')
        if args[0] == 'nvidia-smi': raise host_snapshot.CapabilityError('unavailable', 'tool_missing')
        return b'[{"ifname":"lo","addr_info":[{"local":"127.0.0.1","prefixlen":8}]}]'
    monkeypatch.setattr(host_snapshot, 'query', query)
    monkeypatch.setattr(host_snapshot, 'resources', lambda: {'load': [0., 0., 0.], 'memory_total_kib': 10, 'memory_available_kib': 5})
    caps = host_snapshot.collect('pimux')
    assert caps['sessions']['status'] == 'permission_denied'
    assert caps['gpu']['status'] == 'unavailable'
    assert caps['network']['status'] == 'available'
    assert caps['resources']['status'] == 'available'


def test_cli_never_connects_without_an_explicit_selection(tmp_path):
    config = tmp_path / 'hosts.json'
    hosts.add_host(config, entry(tmp_path))
    result = subprocess.run([sys.executable, str(ROOT / 'lib/hosts.py'), '--config', str(config), 'inspect'],
                            capture_output=True, text=True, timeout=2)
    assert result.returncode == 2 and 'select' in result.stderr.lower()
    listed = subprocess.run([sys.executable, str(ROOT / 'lib/hosts.py'), '--config', str(config), 'list'],
                            capture_output=True, text=True, timeout=2)
    assert listed.returncode == 0 and 'alpha' in listed.stdout


def test_transport_is_bounded_and_cancellation_reaps_only_its_own_group(tmp_path):
    executable = tmp_path / 'fake-ssh'
    pid_file = tmp_path / 'pid'
    executable.write_text('#!' + sys.executable + '\nimport os,time\nopen(' + repr(str(pid_file)) + ',"w").write(str(os.getpid()))\ntime.sleep(30)\n')
    executable.chmod(0o755)
    async def run():
        task = asyncio.create_task(hosts.exchange([str(executable)], b'request', 10))
        for _ in range(100):
            if pid_file.exists(): break
            await asyncio.sleep(.01)
        assert pid_file.exists()
        pid = int(pid_file.read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        with pytest.raises(ProcessLookupError): os.kill(pid, 0)
        start = time.monotonic()
        with pytest.raises(TimeoutError): await hosts.exchange([str(executable)], b'', .1)
        assert time.monotonic() - start < 2
    asyncio.run(run())


def test_oversized_output_and_blocked_stdin_do_not_deadlock_cleanup(tmp_path):
    executable = tmp_path / 'flood-ssh'
    executable.write_text('#!' + sys.executable + '\nimport os,time\nos.write(1,b"x"*(2*1024*1024))\ntime.sleep(30)\n')
    executable.chmod(0o755)
    async def run():
        with pytest.raises(hosts.ProtocolError, match='output limit'):
            await asyncio.wait_for(hosts.exchange([str(executable)], b'y' * (1024 * 1024), 5), 3)
    asyncio.run(run())


@pytest.mark.parametrize('metric', ['load', 'gpu'])
def test_huge_numeric_frame_is_isolated_from_a_healthy_host(tmp_path, monkeypatch, metric):
    good, bad = entry(tmp_path, 'good'), entry(tmp_path, 'bad')
    async def exchange(_argv, payload, _timeout, **_kwargs):
        length, rest = payload.split(b'\n', 1)
        request = json.loads(rest[int(length):])
        host = good if request['host_id'] == 'good' else bad
        data = snapshot(host, request['request_id'])
        if host is bad:
            if metric == 'load': data['capabilities']['resources']['data']['load'][0] = 10**400
            else: data['capabilities']['gpu']['data'] = [{'index':0, 'name':'GPU', 'memory_used_mib':10**400, 'memory_total_mib':1}]
        return 0, host_snapshot.frame(data), b''
    monkeypatch.setattr(hosts, 'exchange', exchange)
    result = asyncio.run(hosts.aggregate([good, bad]))
    assert [row['status'] for row in result] == ['connected', 'protocol_error']
    assert result[1]['snapshot'] is None and result[0]['snapshot']['host_id'] == 'good'


@pytest.mark.parametrize('stream', [1, 2])
def test_stdout_and_stderr_flood_reap_descendants_without_touching_sentinel(tmp_path, stream):
    pid_file = tmp_path / 'pids'
    executable = tmp_path / 'flood-tree'
    executable.write_text('#!' + sys.executable + '\nimport os,time\npid=os.fork()\nif pid==0: time.sleep(30); raise SystemExit\n'
        'open(' + repr(str(pid_file)) + ',"w").write(str(os.getpid())+" "+str(pid))\nos.write(' + str(stream) + ', b"x"*(2*1024*1024))\ntime.sleep(30)\n')
    executable.chmod(0o755)
    sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    async def run():
        with pytest.raises(hosts.ProtocolError):
            await asyncio.wait_for(hosts.exchange([str(executable)], b'y' * 1024 * 1024, 5), 3)
    try:
        asyncio.run(run())
        assert sentinel.poll() is None
        for pid in map(int, pid_file.read_text().split()):
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try: os.kill(pid, 0)
                except ProcessLookupError: break
                time.sleep(.01)
            with pytest.raises(ProcessLookupError): os.kill(pid, 0)
    finally:
        sentinel.terminate(); sentinel.wait(timeout=3)


def test_exited_leader_with_descendant_holding_pipes_has_a_deadline(tmp_path):
    executable = tmp_path / 'held-pipes'
    executable.write_text('#!' + sys.executable + '\nimport os,time\nif os.fork()==0: time.sleep(30)\n')
    executable.chmod(0o755)
    async def run():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(hosts.exchange([str(executable)], b'', .15), 3)
    asyncio.run(run())
