# pimux-managed: transient, read-only Linux snapshot collector; standard library only.
"""Sent over SSH stdin; no installation, shell configuration or remote writes."""
import csv
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import pwd
import shlex
import stat
import selectors
import signal
import socket
import subprocess
import sys
import time

LIMIT = 1024 * 1024


class CapabilityError(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason


def query(args):
    """Bound both output and lifetime; reap just this query's process group."""
    try:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True,
                                   env={**os.environ, 'LC_ALL': 'C', 'LANG': 'C'})
    except FileNotFoundError:
        raise CapabilityError('unavailable', 'tool_missing') from None
    except PermissionError:
        raise CapabilityError('permission_denied', 'permission_denied') from None
    out, err = bytearray(), bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, out)
            selector.register(process.stderr, selectors.EVENT_READ, err)
            end = time.monotonic() + 1.5
            while selector.get_map():
                if time.monotonic() >= end:
                    raise CapabilityError('error', 'query_timeout')
                for key, _ in selector.select(min(.1, max(0, end - time.monotonic()))):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        key.data.extend(chunk)
                        if len(out) + len(err) > LIMIT:
                            raise CapabilityError('error', 'output_limit')
            code = process.wait(timeout=max(.01, end - time.monotonic()))
        if code:
            message = bytes(err + out).lower()
            if b'permission denied' in message or b'operation not permitted' in message:
                raise CapabilityError('permission_denied', 'permission_denied')
            if args[0] == 'tmux' and (b'no server running' in message or b'no such file or directory' in message):
                raise CapabilityError('unavailable', 'server_not_running')
            raise CapabilityError('error', 'query_failed')
        return bytes(out)
    except subprocess.TimeoutExpired:
        raise CapabilityError('error', 'query_timeout') from None
    finally:
        # Kill descendants even if a query leader exited first.
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        process.wait()
        process.stdout.close()
        process.stderr.close()


def sessions(server):
    prefix = ['tmux', '-L', server]
    ids = query(prefix + ['list-sessions', '-F', '#{session_id}']).decode().splitlines()
    if len(ids) > 128 or len(ids) != len(set(ids)) or any(not re.fullmatch(r'\$[0-9]+', x) for x in ids):
        raise ValueError('session ids')
    rows = []
    for session in ids:
        # Query names independently: tabs/newlines are valid metadata, not record separators.
        name = query(prefix + ['display-message', '-p', '-t', session, '#{session_name}']).decode().removesuffix('\n')
        count = int(query(prefix + ['display-message', '-p', '-t', session, '#{session_windows}']))
        rows.append(dict(id=session, name=name, windows=count))
    return rows


def resources():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        name, value = line.split(':', 1)
        if name in {'MemTotal', 'MemAvailable'}: values[name] = int(value.split()[0])
    return dict(load=list(os.getloadavg()), memory_total_kib=values['MemTotal'],
                memory_available_kib=values['MemAvailable'])


def network():
    rows = json.loads(query(['ip', '-j', 'address', 'show']))
    return [dict(name=row['ifname'], addresses=[str(item['local']) + '/' + str(item['prefixlen'])
            for item in row.get('addr_info', [])]) for row in rows]


def gpu():
    output = query(['nvidia-smi', '--query-gpu=index,name,memory.used,memory.total',
                    '--format=csv,noheader,nounits']).decode()
    rows = []
    for index, name, used, total in csv.reader(io.StringIO(output), skipinitialspace=True):
        def metric(value):
            if value in {'N/A', '[N/A]', '[Not Supported]'}: return None
            number = float(value)
            if not math.isfinite(number) or number < 0: raise ValueError('GPU metric')
            return number
        rows.append(dict(index=int(index), name=name, memory_used_mib=metric(used), memory_total_mib=metric(total)))
    return rows


def collect(server):
    result = {}
    for name, function in [('sessions', lambda: sessions(server)), ('resources', resources), ('network', network), ('gpu', gpu)]:
        try:
            result[name] = dict(status='available', reason='', data=function())
        except CapabilityError as error:
            result[name] = dict(status=error.status, reason=error.reason, data=None)
        except PermissionError:
            result[name] = dict(status='permission_denied', reason='permission_denied', data=None)
        except FileNotFoundError:
            result[name] = dict(status='unavailable', reason='source_missing', data=None)
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, csv.Error):
            result[name] = dict(status='error', reason='invalid_query_data', data=None)
    return result


def access_state(fingerprint):
    """Read only the standard user authorization file, never keys or sshd config."""
    directory = Path(pwd.getpwuid(os.getuid()).pw_dir) / '.ssh'
    path = directory / 'authorized_keys'
    if directory.is_symlink() or path.is_symlink():
        raise CapabilityError('error', 'unsafe_authorization_path')
    for candidate in (directory, path):
        if candidate.exists():
            info = candidate.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise CapabilityError('permission_denied', 'unsafe_authorization_permissions')
    present, restricted = False, False
    if path.exists():
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
                raise CapabilityError('error', 'authorization_file_limit')
            data = stream.read(LIMIT + 1)
        for line in data.decode(errors='replace').splitlines():
            try: fields = shlex.split(line, comments=True)
            except ValueError: continue
            for index, token in enumerate(fields[:-1]):
                if token.startswith(('ssh-', 'ecdsa-', 'sk-')):
                    try:
                        blob = base64.b64decode(fields[index + 1], validate=True)
                        found = 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
                    except ValueError: continue
                    if found == fingerprint:
                        present = True
                        restricted = restricted or index > 0
                    break
    return dict(fingerprint=fingerprint, state='present' if present else 'absent', restricted=restricted,
                file_status='existing' if path.exists() else 'missing', scope='standard_user_authorized_keys_only')


def frame(data):
    body = json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()
    if len(body) > LIMIT: raise ValueError('snapshot limit')
    return b'PIMUX-SNAPSHOT/1 ' + str(len(body)).encode() + b'\n' + body + b'\n'


def main():
    # Termination interrupts the active query, whose finally block reaps its group.
    def stop(_signum, _frame): raise KeyboardInterrupt
    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGALRM): signal.signal(signum, stop)
    signal.alarm(12)
    request = json.loads(sys.stdin.buffer.read(4097))
    fields = {'version', 'request_id', 'host_id', 'socket'}
    if (set(request) not in (fields, fields | {'public_fingerprint'}) or request['version'] != 1
            or not re.fullmatch('[a-f0-9]{32}', request['request_id'])
            or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}', request['host_id'])
            or not re.fullmatch('[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}', request['socket'])):
        raise ValueError('invalid snapshot request')
    if sys.platform != 'linux': raise ValueError('Linux collector required')
    node = Path('/etc/machine-id').read_text().strip()
    if not re.fullmatch('[a-f0-9]{32}', node): raise ValueError('stable machine-id unavailable')
    caps = collect(request['socket'])
    if 'public_fingerprint' in request:
        fingerprint = request['public_fingerprint']
        if not isinstance(fingerprint, str) or not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', fingerprint): raise ValueError('public fingerprint')
        try: caps['access'] = dict(status='available', reason='', data=access_state(fingerprint))
        except CapabilityError as error: caps['access'] = dict(status=error.status, reason=error.reason, data=None)
        except PermissionError: caps['access'] = dict(status='permission_denied', reason='permission_denied', data=None)
        except OSError: caps['access'] = dict(status='error', reason='authorization_query_failed', data=None)
    data = dict(protocol='pimux.snapshot', version=1, request_id=request['request_id'],
                host_id=request['host_id'], node_id=node, hostname=socket.gethostname(),
                platform='linux', socket=request['socket'], capabilities=caps,
                account={'name': pwd.getpwuid(os.getuid()).pw_name, 'uid': os.getuid()})
    sys.stdout.buffer.write(frame(data))
    sys.stdout.buffer.flush()
    signal.alarm(0)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, TypeError, KeyError, KeyboardInterrupt):
        print('PiMux snapshot unavailable or cancelled.', file=sys.stderr)
        raise SystemExit(2) from None
