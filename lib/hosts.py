# pimux-managed: explicit host inventory and bounded read-only SSH aggregation.
"""Local alias discovery and host snapshots; confirmed enrollment is a separate command."""
import argparse
import asyncio
import fcntl
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import signal
import selectors
import subprocess
import time
import shlex
import sys
import tempfile
import uuid

MAX_OUTPUT = 1024 * 1024 + 64
MAX_HOSTS = 32
# A fixed remote command. Configuration and request values travel as framed stdin,
# never as shell command text. Only our bundled collector is executed in memory.
REMOTE_COMMAND = "python3 -I -S -B -c 'import sys; n=int(sys.stdin.buffer.readline()); assert 0<n<131072; exec(compile(sys.stdin.buffer.read(n),\"<pimux-snapshot>\",\"exec\"))'"
FIELDS = {'host_id', 'name', 'address', 'port', 'user', 'node_id', 'known_hosts', 'identity_file', 'socket', 'timeout'}
PROFILE_FIELDS = {'host_id', 'name', 'node_id', 'socket', 'timeout', 'ssh_config', 'alias'}


class ProtocolError(ValueError): pass
class IdentityError(ProtocolError): pass


def number(value, minimum=0):
    # Compare integers before any float conversion; even a 400-digit JSON int
    # must remain a per-host protocol error, never OverflowError from isfinite.
    return (type(value) in (int, float) and minimum <= value <= 2**53
            and (type(value) == int or math.isfinite(value)))


def literal(value, limit=4096):
    return isinstance(value, str) and len(value) <= limit and '\x00' not in value


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def constant(_value): raise ValueError('non-finite JSON number')
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def validate_host(host):
    if not isinstance(host, dict) or set(host) not in (FIELDS, PROFILE_FIELDS): raise ValueError('Invalid host fields')
    profile_mode = set(host) == PROFILE_FIELDS
    patterns = [('host_id', '[a-z0-9][a-z0-9_-]{0,63}'), ('socket', '[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}')]
    if not profile_mode: patterns += [('user', '[a-zA-Z_][a-zA-Z0-9_.-]{0,63}')]
    if not profile_mode or host['node_id'] is not None: patterns += [('node_id', '[a-f0-9]{32}')]
    for field, pattern in patterns:
        if not isinstance(host[field], str) or not re.fullmatch(pattern, host[field]):
            raise ValueError('Invalid ' + field)
    for field in (('name',) if profile_mode else ('name', 'address', 'known_hosts')):
        if not literal(host[field], 4096) or not host[field] or any(ord(c) < 32 or ord(c) == 127 for c in host[field]):
            raise ValueError('Invalid ' + field)
    if len(host['name']) > 100: raise ValueError('Host name too long')
    if not number(host['timeout'], 1) or host['timeout'] > 30: raise ValueError('Invalid timeout (1–30 seconds)')
    if profile_mode:
        from ssh_discovery import ALIAS
        if not isinstance(host['alias'], str) or not ALIAS.fullmatch(host['alias']): raise ValueError('Invalid SSH alias')
        path = host['ssh_config']
        if not literal(path) or not path.startswith('/') or any(ord(c) < 32 for c in path): raise ValueError('Invalid SSH config path')
        return host
    try: ipaddress.ip_address(host['address'])
    except ValueError:
        if not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}', host['address']): raise ValueError('Invalid address')
    if type(host['port']) != int or not 1 <= host['port'] <= 65535: raise ValueError('Invalid port')
    for field in ('known_hosts', 'identity_file'):
        value = host[field]
        if field == 'identity_file' and value is None: continue
        if (not literal(value) or not value.startswith('/') or '%' in value
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError('Use an absolute literal ' + field + ' path without SSH expansion tokens')
    return host


def read_config(path):
    if path.is_symlink(): raise ValueError('Refusing a symlink host configuration')
    if not path.exists(): return []
    if path.stat().st_size > 256 * 1024: raise ValueError('Host configuration too large')
    data = strict_json(path.read_bytes())
    if not isinstance(data, dict) or set(data) != {'version', 'hosts'} or type(data['version']) != int or data['version'] != 1:
        raise ValueError('Unsupported host configuration version')
    rows = data['hosts']
    if not isinstance(rows, list) or len(rows) > MAX_HOSTS: raise ValueError('Too many hosts')
    for row in rows: validate_host(row)
    if len({row['host_id'] for row in rows}) != len(rows): raise ValueError('Duplicate host_id')
    nodes = [row['node_id'] for row in rows if row['node_id'] is not None]
    if len(set(nodes)) != len(nodes): raise ValueError('Duplicate server node_id')
    return rows


def add_host(path, host):
    validate_host(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix('.lock')
    with os.fdopen(os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = read_config(path)
        if len(rows) >= MAX_HOSTS: raise ValueError('At most 32 explicit hosts are supported')
        if any(row['host_id'] == host['host_id'] or (host['node_id'] is not None and row['node_id'] == host['node_id']) for row in rows):
            raise ValueError('Host ID or server node ID already configured')
        descriptor, temporary = tempfile.mkstemp(prefix='.hosts-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                json.dump({'version': 1, 'hosts': rows + [host]}, stream, ensure_ascii=True, indent=2, allow_nan=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)


def decode_snapshot(wire, host, request_id, public_fingerprint=None):
    try:
        if len(wire) > MAX_OUTPUT: raise ValueError('output limit')
        header, body = wire.split(b'\n', 1)
        if not re.fullmatch(rb'PIMUX-SNAPSHOT/1 [0-9]{1,7}', header): raise ValueError('protocol frame/version')
        length = int(header.split(b' ')[1])
        if body[-1:] != b'\n' or len(body) != length + 1: raise ValueError('frame size or output pollution')
        data = strict_json(body[:-1])
        if not isinstance(data, dict) or set(data) != {'protocol', 'version', 'request_id', 'host_id', 'node_id', 'hostname', 'platform', 'socket', 'capabilities', 'account'}:
            raise ValueError('snapshot fields')
        if data['protocol'] != 'pimux.snapshot' or type(data['version']) != int or data['version'] != 1: raise ValueError('protocol version')
        if data['request_id'] != request_id or data['host_id'] != host['host_id'] or data['socket'] != host['socket']:
            raise ValueError('request/host/socket mismatch')
        if not isinstance(data['node_id'], str) or not re.fullmatch('[a-f0-9]{32}', data['node_id']): raise ValueError('server identity')
        if host['node_id'] is not None and data['node_id'] != host['node_id']: raise IdentityError('Server node ID differs from the explicit inventory')
        if not literal(data['hostname'], 255) or data['platform'] != 'linux': raise ValueError('server metadata')
        account = data['account']
        if (not isinstance(account, dict) or set(account) != {'name', 'uid'} or not literal(account['name'], 100)
                or type(account['uid']) != int or account['uid'] < 0): raise ValueError('server account')
        caps = data['capabilities']
        expected = {'sessions', 'resources', 'network', 'gpu'} | ({'access'} if public_fingerprint else set())
        if not isinstance(caps, dict) or set(caps) != expected: raise ValueError('capabilities')
        for name, cap in caps.items():
            if not isinstance(cap, dict) or set(cap) != {'status', 'reason', 'data'}: raise ValueError('capability fields')
            if cap['status'] not in {'available', 'unavailable', 'permission_denied', 'error'} or not literal(cap['reason'], 200):
                raise ValueError('capability status')
            if cap['status'] != 'available':
                if cap['data'] is not None or not cap['reason']: raise ValueError('unavailable data')
                continue
            value = cap['data']
            if cap['reason']: raise ValueError('available reason')
            if name == 'sessions':
                if not isinstance(value, list) or len(value) > 128: raise ValueError('sessions')
                seen = set()
                for row in value:
                    if (not isinstance(row, dict) or set(row) != {'id', 'name', 'windows'}
                        or not isinstance(row['id'], str) or not re.fullmatch(r'\$[0-9]+', row['id'])
                        or row['id'] in seen or not literal(row['name']) or type(row['windows']) != int or row['windows'] < 0):
                        raise ValueError('session row')
                    seen.add(row['id'])
            elif name == 'resources':
                if (not isinstance(value, dict) or set(value) != {'load', 'memory_total_kib', 'memory_available_kib'}
                    or not isinstance(value['load'], list) or len(value['load']) != 3
                    or not all(number(n) for n in value['load'])
                    or any(type(value[k]) != int or value[k] < 0 for k in ('memory_total_kib', 'memory_available_kib'))
                    or value['memory_available_kib'] > value['memory_total_kib']): raise ValueError('resources')
            elif name == 'network':
                if not isinstance(value, list) or len(value) > 4096: raise ValueError('network')
                for row in value:
                    if (not isinstance(row, dict) or set(row) != {'name', 'addresses'} or not literal(row['name'], 255)
                        or not isinstance(row['addresses'], list) or len(row['addresses']) > 1024): raise ValueError('interface')
                    for address in row['addresses']:
                        if not literal(address, 128): raise ValueError('address')
                        ipaddress.ip_interface(address)
            elif name == 'access':
                if (not isinstance(value, dict) or set(value) != {'fingerprint', 'state', 'restricted', 'file_status', 'scope'}
                    or value['fingerprint'] != public_fingerprint or value['state'] not in {'present', 'absent'}
                    or type(value['restricted']) != bool or value['file_status'] not in {'existing', 'missing'}
                    or value['scope'] != 'standard_user_authorized_keys_only'): raise ValueError('access state')
            else:
                if not isinstance(value, list) or len(value) > 256: raise ValueError('gpu')
                for row in value:
                    if (not isinstance(row, dict) or set(row) != {'index', 'name', 'memory_used_mib', 'memory_total_mib'}
                        or type(row['index']) != int or row['index'] < 0 or not literal(row['name'], 255)
                        or any(row[k] is not None and not number(row[k]) for k in ('memory_used_mib', 'memory_total_mib'))):
                        raise ValueError('GPU row')
        return data
    except IdentityError: raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError) as error:
        raise ProtocolError('Invalid snapshot: ' + str(error)) from None


def ssh_command(host):
    from ssh_hop import credential_policy
    validate_host(host)
    options = [*credential_policy(), 'BatchMode=yes', 'StrictHostKeyChecking=yes', 'UpdateHostKeys=no',
               'ForwardAgent=no', 'ClearAllForwardings=yes', 'PermitLocalCommand=no',
               'ControlMaster=no', 'ControlPath=none', 'RemoteCommand=none',
               'ConnectionAttempts=1', 'ConnectTimeout=' + str(math.ceil(host['timeout'])),
               'ServerAliveInterval=1', 'ServerAliveCountMax=1', 'LogLevel=DEBUG1']
    profile_mode = 'ssh_config' in host
    argv = ['/usr/bin/ssh', '-F', host['ssh_config'] if profile_mode else '/dev/null', '-T']
    if not profile_mode:
        path = host['known_hosts'].replace('\\', '\\\\').replace('"', '\\"')
        options += ['UserKnownHostsFile="' + path + '"', 'GlobalKnownHostsFile=/dev/null', 'ProxyCommand=none', 'ProxyJump=none']
        if host['identity_file']:
            argv += ['-i', host['identity_file']]
            options += ['IdentitiesOnly=yes', 'IdentityAgent=none']
        else:
            # Agent authentication is explicit; never search the user's private key files.
            options += ['IdentityFile=none', 'IdentitiesOnly=no']
    for option in options: argv += ['-o', option]
    if profile_mode: return argv + ['--', host['alias'], REMOTE_COMMAND]
    return argv + ['-p', str(host['port']), '-l', host['user'], '--', host['address'], REMOTE_COMMAND]


async def exchange(argv, payload, timeout, env=None):
    # Own OS pipe descriptors directly. Closing them after kill cannot depend
    # on asyncio StreamReader flow control or a child keeping a pipe open.
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True, env=env)
    selector = selectors.DefaultSelector()
    output, errors, offset = bytearray(), bytearray(), 0
    for stream, event, data in ((process.stdin, selectors.EVENT_WRITE, None),
                               (process.stdout, selectors.EVENT_READ, output),
                               (process.stderr, selectors.EVENT_READ, errors)):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, event, data)
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map() or process.poll() is None:
            if time.monotonic() >= deadline: raise TimeoutError('Host snapshot deadline exceeded')
            for key, event in selector.select(0):
                if event == selectors.EVENT_WRITE:
                    try: offset += os.write(key.fd, payload[offset:offset + 65536])
                    except BrokenPipeError: offset = len(payload)
                    except BlockingIOError: continue
                    if offset == len(payload):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                else:
                    try: chunk = os.read(key.fd, 65536)
                    except BlockingIOError: continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    else:
                        key.data.extend(chunk)
                        limit = MAX_OUTPUT if key.data is output else 65536
                        if len(key.data) > limit: raise ProtocolError('SSH output limit exceeded')
            await asyncio.sleep(.005)
        return process.returncode, bytes(output), bytes(errors)
    finally:
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        selector.close()
        for stream in (process.stdin, process.stdout, process.stderr): stream.close()
        # SIGKILL + waitpid is independent of the pipe transports. Keep cleanup
        # idempotent and bounded without replacing the original protocol error.
        try: process.wait(timeout=2)
        except subprocess.TimeoutExpired: pass


async def fetch_host(host, public_fingerprint=None, tty=None):
    import access_identity
    from access_transport import connection, accepted_public_key
    result = dict(host_id=host['host_id'], name=host['name'], address=host.get('address', host.get('alias')),
                  status='connected', reason='', snapshot=None, host_key=None)
    nonce = uuid.uuid4().hex
    code = Path(__file__).with_name('host_snapshot.py').read_bytes()
    request_data = dict(version=1, request_id=nonce, host_id=host['host_id'], socket=host['socket'])
    if public_fingerprint: request_data['public_fingerprint'] = public_fingerprint
    request = json.dumps(request_data).encode()
    payload = str(len(code)).encode() + b'\n' + code + request
    try:
        choice = access_identity.load(host)
        with connection(host, tty=tty if choice else None,
                        key_only=access_identity.identity(choice['key']) if choice else None) as (argv,env,root):
            status, out, err = await exchange(argv, payload, 120 if tty and choice else host['timeout'], env=env)
            diagnostics = []
            for index in range(8):
                path = root / ('hop-' + str(index) + '.log')
                if path.exists():
                    if path.stat().st_size > 65536: raise ProtocolError('SSH diagnostic output limit exceeded')
                    diagnostics.append(path.read_bytes())
            target_log = root / 'hop-0.log'
            local_handshake = target_log.read_bytes() if target_log.exists() else b''
            failure_details = b'\n'.join(diagnostics) + err
            selected_authenticated = not choice or (target_log.exists() and accepted_public_key(root,choice['key']['fingerprint']))
        if status:
            message = failure_details.lower()
            if b'host key verification failed' in message or b'remote host identification has changed' in message:
                result.update(status='host_key_error', reason='SSH host key verification failed')
            elif b'permission denied' in message:
                reason = ('Selected key could not authenticate. An encrypted key requires an interactive terminal or an already-unlocked agent identity; PiMux does not add agent keys or fall back to other target identities.'
                          if choice else 'SSH authentication denied')
                result.update(status='authentication_error', reason=reason)
            else: result.update(status='ssh_error', reason='SSH or remote collector failed (exit ' + str(status) + ')')
        else:
            result['snapshot'] = decode_snapshot(out, host, nonce, public_fingerprint)
            # Only the final client's private local -E log is trusted. Remote
            # stderr and nested jump logs never supply the destination fingerprint.
            fingerprints = re.findall(rb'^debug1: Server host key: ([a-zA-Z0-9@._+-]+) (SHA256:[A-Za-z0-9+/]+)\r?$', local_handshake, re.MULTILINE)
            if len(fingerprints) == 1:
                algorithm, fingerprint = fingerprints[0]
                result['host_key'] = dict(algorithm=algorithm.decode(), fingerprint=fingerprint.decode())
            if choice:
                if (not selected_authenticated or not access_identity.matches(choice,result['snapshot'],result['host_key'])
                        or access_identity.load(host) != choice):
                    raise access_identity.SelectionError('Saved target or selected key no longer matches; reset and verify this target again')
                result['identity_fingerprint'] = choice['key']['fingerprint']
    except access_identity.SelectionError as error:
        result.update(status='identity_selection_error', reason=str(error), snapshot=None)
    except TimeoutError: result.update(status='timeout', reason='Host snapshot deadline exceeded')
    except IdentityError: result.update(status='identity_mismatch', reason='Server node ID differs from inventory')
    except ProtocolError as error: result.update(status='protocol_error', reason=str(error))
    except ValueError:
        result.update(status='configuration_error', reason='SSH configuration is incomplete or contains local execution directives; use explicit configuration includes and ProxyJump', snapshot=None)
    except OSError: result.update(status='ssh_error', reason='SSH executable or local runtime unavailable')
    return result


async def aggregate(rows, tty=None):
    if tty:
        # Serialize interactive prompts; never ask multiple hosts for secrets
        # concurrently on one terminal. Batch callers retain bounded concurrency.
        return [await fetch_host(row,tty=tty) for row in rows]
    semaphore = asyncio.Semaphore(4)
    async def fetch(row):
        async with semaphore: return await fetch_host(row)
    return await asyncio.gather(*(fetch(row) for row in rows))


def run_operation(operation):
    cancelled_by = [signal.SIGINT]
    async def run():
        loop, task = asyncio.get_running_loop(), asyncio.current_task()
        def stop():
            cancelled_by[0] = signal.SIGTERM
            task.cancel()
        loop.add_signal_handler(signal.SIGTERM, stop)
        try: return await operation
        finally: loop.remove_signal_handler(signal.SIGTERM)
    try: return asyncio.run(run())
    except (KeyboardInterrupt, asyncio.CancelledError): raise SystemExit(128 + cancelled_by[0]) from None


def safe_text(value):
    # Literal labels and server metadata cannot emit ANSI, tabs or newlines.
    encoded = json.dumps(str(value), ensure_ascii=False)[1:-1]
    return ''.join(char if char.isprintable() else '\\u%04x' % ord(char) for char in encoded)


def render(results):
    lines = []
    for row in results:
        lines.append(f"[{row['host_id']}] {safe_text(row['name'])} · {safe_text(row['address'])} · {row['status']}")
        if row['snapshot'] is None:
            lines.append('  ' + safe_text(row['reason']))
            continue
        snapshot = row['snapshot']
        lines.append('  server=' + safe_text(snapshot['account']['name']) + '@' + safe_text(snapshot['hostname']) + ' node=' + snapshot['node_id'] + ' socket=' + snapshot['socket'])
        for name, cap in snapshot['capabilities'].items():
            lines.append('  ' + name + ': ' + cap['status'] + ((' (' + safe_text(cap['reason']) + ')') if cap['reason'] else ''))
            if cap['status'] != 'available': continue
            if name == 'sessions':
                for session in cap['data']:
                    lines.append('    ' + '/'.join((row['host_id'], snapshot['socket'], session['id'])) + ' ' + safe_text(session['name']) + ' · windows=' + str(session['windows']))
                if not cap['data']: lines.append('    (empty)')
            else: lines.append('    ' + json.dumps(cap['data'], ensure_ascii=True, separators=(',', ':')))
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Discover local SSH aliases, inspect Linux hosts read-only, and explicitly confirm public-key setup. No remote session actions.')
    parser.add_argument('--config', type=Path, default=Path.home() / '.config/pimux/hosts.json')
    parser.add_argument('--ssh-config', type=Path, action='append', help='Choose an existing SSH configuration; OpenSSH evaluates it only for an explicit connection')
    sub = parser.add_subparsers(dest='command', required=True)
    add = sub.add_parser('add', help='Save one explicit entry without connecting')
    add.add_argument('host_id')
    for field in ('name', 'address', 'user', 'node-id', 'known-hosts'): add.add_argument('--' + field, required=True)
    add.add_argument('--identity-file')
    add.add_argument('--port', type=int, default=22)
    add.add_argument('--socket', default='pimux')
    add.add_argument('--timeout', type=float, default=10)
    sub.add_parser('list', help='List configured hosts without connecting')
    discovery = sub.add_parser('discover', help='Read VS Code/OpenSSH aliases without executing commands or connecting')
    discovery.add_argument('--settings', type=Path, action='append', help='Explicit VS Code settings/profile path')
    discovery.add_argument('--json', action='store_true')
    access = sub.add_parser('access-preview', help='Discover public keys and inspect authorization; never write remote files')
    access.add_argument('host_id')
    access.add_argument('--key', type=Path, help='Choose a public .pub file only when several candidates exist')
    access.add_argument('--json', action='store_true')
    setup = sub.add_parser('access-setup', help='Confirm, install and verify one public key on an explicitly selected server')
    setup.add_argument('host_id')
    setup.add_argument('--key', type=Path)
    setup.add_argument('--operation', help='Reconcile a previously interrupted operation before any write')
    reset = sub.add_parser('identity-reset', help='Forget only PiMux\'s saved key choice; no server connection or authorization change')
    reset.add_argument('host_id')
    inspect = sub.add_parser('inspect', help='Fetch only explicitly selected hosts')
    inspect.add_argument('host_ids', nargs='*')
    inspect.add_argument('--all', action='store_true')
    inspect.add_argument('--json', action='store_true')
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments or ['discover'])
    try:
        if args.command == 'discover':
            from ssh_discovery import discover
            found = discover(settings=args.settings, config_files=args.ssh_config)
            if args.json: print(json.dumps(found, ensure_ascii=True))
            else:
                for candidate in found['candidates']:
                    print(safe_text(candidate['alias']) + ' · ' + safe_text(candidate['ssh_config']) + ' · not connected')
                for note in found['notes']: print('Note: ' + note)
            return 0
        if args.command == 'add':
            host = {field: getattr(args, field) for field in FIELDS}
            add_host(args.config, host)
            print('Added ' + host['host_id'] + '; no connection made.')
            return 0
        rows = read_config(args.config)
        if args.command == 'list':
            for row in rows: print('[' + row['host_id'] + '] ' + safe_text(row['name']) + ' · ' + safe_text(row.get('address', row.get('alias'))) + ' · not queried')
            return 0
        if args.command in {'access-setup','identity-reset'}:
            from ssh_discovery import resolve_alias
            from access_setup import run_wizard
            host = next((row for row in rows if row['host_id'] == args.host_id), None)
            if host is None: host = resolve_alias(args.host_id, args.ssh_config)
            if args.command == 'identity-reset':
                from access_identity import forget
                forget(host)
                print('Forgot the local identity choice; server authorizations are unchanged. Use access-setup to select and verify again.')
                return 0
            return run_wizard(host, args.key, args.operation)
        if args.command == 'access-preview':
            from ssh_discovery import resolve_alias
            from access_preview import preview, render_preview
            host = next((row for row in rows if row['host_id'] == args.host_id), None)
            if host is None: host = resolve_alias(args.host_id, args.ssh_config)
            result = run_operation(preview(host, args.key))
            print(json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2) if args.json else render_preview(result))
            return 0 if result['status'] in {'already_listed', 'already_listed_restricted', 'authorization_missing'} else 1
        if args.all == bool(args.host_ids): parser.error('Select host IDs or --all explicitly')
        if len(args.host_ids) != len(set(args.host_ids)): parser.error('Duplicate host selection')
        if args.all and args.ssh_config: parser.error('--all only queries saved inventory; select discovered aliases by name')
        from ssh_discovery import resolve_alias
        selected = rows if args.all else [next((row for row in rows if row['host_id'] == key), None) for key in args.host_ids]
        if not args.all:
            selected = [row if row is not None else resolve_alias(key, args.ssh_config) for key, row in zip(args.host_ids, selected)]
        from access_transport import terminal_state
        tty = os.ttyname(sys.stdin.fileno()) if sys.stdin.isatty() else None
        with terminal_state(tty):
            results = run_operation(aggregate(selected,tty=tty))
        print(json.dumps({'version': 1, 'hosts': results}, ensure_ascii=True, allow_nan=False) if args.json else render(results))
        return 1 if any(row['status'] != 'connected' for row in results) else 0
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__': raise SystemExit(main())
