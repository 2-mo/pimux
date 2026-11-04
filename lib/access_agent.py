# pimux-managed: explicit, confirmed standard authorized_keys enrollment agent.
# Transmitted in memory. Linux/OpenSSH only; no sudo or service configuration.
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import signal
import socket
import stat
import sys
import tempfile

LIMIT = 1024 * 1024


def digest(data): return hashlib.sha256(data).hexdigest()


def fingerprint(blob):
    return 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')


def public_line(value):
    if not isinstance(value, str) or '\n' in value or '\r' in value or len(value) > 16000: raise ValueError('Invalid public key')
    fields = value.split()
    if len(fields) != 2 or not fields[0].startswith(('ssh-', 'ecdsa-', 'sk-')): raise ValueError('Invalid public key')
    blob = base64.b64decode(fields[1], validate=True)
    size = int.from_bytes(blob[:4], 'big')
    if len(blob) < 8 or blob[4:4+size].decode() != fields[0]: raise ValueError('Invalid public key algorithm')
    return ' '.join(fields), fingerprint(blob)


def listed(data, wanted):
    present, restricted = False, False
    for line in data.decode(errors='replace').splitlines():
        try: fields = shlex.split(line, comments=True)
        except ValueError: continue
        for index, token in enumerate(fields[:-1]):
            if token.startswith(('ssh-', 'ecdsa-', 'sk-')):
                try: found = fingerprint(base64.b64decode(fields[index+1], validate=True))
                except ValueError: continue
                if found == wanted: present, restricted = True, restricted or index > 0
                break
    return present, restricted


def login_mode():
    # Tailscale address routing is independent of login policy. Only an actual
    # sshd ancestor certifies the ordinary OpenSSH authorized_keys workflow.
    pid = os.getppid()
    for _ in range(16):
        try:
            name = Path('/proc', str(pid), 'comm').read_text().strip()
            fields = Path('/proc', str(pid), 'status').read_text().splitlines()
            if name == 'tailscaled': return 'tailscale_ssh_policy'
            if name in {'sshd', 'sshd-session', 'sshd-auth'}: return 'openssh'
            pid = int(next(line.split()[1] for line in fields if line.startswith('PPid:')))
            if pid <= 1: break
        except (OSError, ValueError, StopIteration): break
    return 'unknown'


def secure_path(path, directory=False):
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError('Unsafe authorization ownership, type or permissions')
    return info


class Store:
    def __init__(self, home):
        self.home = Path(home)
        self.directory = self.home / '.ssh'
        self.path = self.directory / 'authorized_keys'
        self.journals = self.directory / '.pimux-enrollment'

    def read(self):
        secure_path(self.home, True)
        if not self.directory.exists() and not self.directory.is_symlink(): return b''
        secure_path(self.directory, True)
        if not self.path.exists() and not self.path.is_symlink(): return b''
        secure_path(self.path)
        with os.fdopen(os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o022 or info.st_size > LIMIT:
                raise ValueError('Unsafe authorization file')
            data = stream.read(LIMIT+1)
        if len(data) > LIMIT: raise ValueError('Authorization size limit')
        return data

    @contextlib.contextmanager
    def locked(self):
        # Called only after explicit confirmation, never for preview/status.
        secure_path(self.home, True)
        self.directory.mkdir(mode=0o700, exist_ok=True)
        secure_path(self.directory, True)
        self.journals.mkdir(mode=0o700, exist_ok=True)
        secure_path(self.journals, True)
        descriptor = os.open(self.journals / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        with os.fdopen(descriptor, 'r+') as lock:
            info = os.fstat(lock.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('Unsafe enrollment lock')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def journal(self, operation, data=None):
        if not re.fullmatch('[a-f0-9]{32}', operation): raise ValueError('Invalid operation ID')
        path = self.journals / (operation + '.json')
        if data is None:
            if not path.exists(): return None
            secure_path(self.directory, True); secure_path(self.journals, True); secure_path(path)
            if path.stat().st_size > 20000: raise ValueError('Operation journal limit')
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream: return json.loads(stream.read(20001))
        self.atomic(path, json.dumps(data, sort_keys=True).encode() + b'\n')

    def atomic(self, path, data):
        descriptor, temporary = tempfile.mkstemp(prefix='.pimux-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
            parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(parent)
            finally: os.close(parent)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def apply(self, operation, key, expected):
        key, wanted = public_line(key)
        with self.locked():
            previous = self.journal(operation)
            if previous is not None:
                # An uncertain request is reconciled, never replayed as a write.
                return self.status(operation)
            before = self.read()
            if digest(before) != expected: return {'state':'changed_requires_confirmation'}
            present, restricted = listed(before, wanted)
            if present: return {'state':'already_listed_restricted' if restricted else 'already_listed'}
            suffix = (b'\n' if before and not before.endswith(b'\n') else b'') + (key + ' pimux:' + operation + '\n').encode()
            if len(before)+len(suffix)>LIMIT: raise ValueError('Authorization size limit')
            record = dict(operation=operation, fingerprint=wanted, before=digest(before), before_size=len(before), after=digest(before+suffix),
                          suffix=suffix.decode(), state='prepared')
            self.journal(operation, record)
            # O_APPEND preserves existing bytes and other users' authorizations.
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            with os.fdopen(fd, 'r+b', buffering=0) as stream:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o022:
                    raise ValueError('Unsafe authorization file')
                current = stream.read(LIMIT+1)
                if digest(current) != expected: return {'state':'changed_requires_confirmation'}
                if os.write(fd, suffix) != len(suffix): raise OSError('Incomplete authorization append')
                os.fsync(fd)
            record['state'] = 'applied'
            self.journal(operation, record)
            return self.status(operation)

    def status(self, operation):
        record = self.journal(operation)
        if record is None: return {'state':'not_started'}
        data = self.read()
        if digest(data) == record['after']: return {'state':'applied', 'fingerprint':record['fingerprint']}
        if digest(data) == record['before']: return {'state':'rolled_back' if record['state'] == 'rolled_back' else 'not_applied'}
        offset=record['before_size']
        if digest(data[:offset])==record['before'] and record['suffix'].encode().startswith(data[offset:]):
            return {'state':'partial_write', 'fingerprint':record['fingerprint']}
        return {'state':'changed_requires_review', 'fingerprint':record['fingerprint']}

    def rollback(self, operation):
        # This shared file has no enforceable coordination contract with other
        # authorized_keys editors. A digest followed by replace/truncate cannot
        # safely revoke our line: a concurrent edit can land between them.
        # Observe only, retaining both the authorization and recovery evidence.
        record = self.journal(operation)
        if record is None: return {'state':'not_started'}
        observed = self.status(operation)
        return {'state':'rollback_requires_review', 'observed_state':observed['state'],
                'reason':'shared_authorization_file_has_no_exclusive_writer_contract'}


def send(data):
    body = json.dumps(data, ensure_ascii=True, allow_nan=False).encode()
    if len(body) > 60000: raise ValueError('Response limit')
    sys.stdout.buffer.write(b'PIMUX-ACCESS/1 ' + str(len(body)).encode() + b'\n' + body + b'\n'); sys.stdout.buffer.flush()


def receive():
    raw = sys.stdin.buffer.readline(20001)
    if not raw or len(raw) > 20000 or not raw.endswith(b'\n'): raise ValueError('Request limit or closed channel')
    return json.loads(raw)


def main():
    def stop(*_args): raise KeyboardInterrupt
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGALRM): signal.signal(sig, stop)
    signal.alarm(300)
    request = receive()
    if request.get('version') != 1 or not re.fullmatch('[a-f0-9]{32}', request.get('operation', '')): raise ValueError('Request version or operation')
    account = pwd.getpwuid(os.getuid())
    node = Path('/etc/machine-id').read_text().strip()
    if not re.fullmatch('[a-f0-9]{32}', node): raise ValueError('Server identity unavailable')
    store = Store(account.pw_dir)
    key, wanted = public_line(request['key'])
    before = store.read(); present, restricted = listed(before, wanted)
    review = dict(version=1, operation=request['operation'], account=account.pw_name, uid=os.getuid(),
                  hostname=socket.gethostname(), node_id=node, mode=login_mode(), fingerprint=wanted,
                  file_digest=digest(before), present=present, restricted=restricted)
    review['token'] = digest(json.dumps(review, sort_keys=True).encode())
    send({'type':'review', 'review':review, 'operation_state':store.status(request['operation'])})
    command = receive()
    if command.get('action') == 'cancel': return
    if command.get('action') != 'apply' or command.get('token') != review['token'] or review['mode'] != 'openssh':
        raise ValueError('Explicit confirmation or OpenSSH server required')
    result = store.apply(request['operation'], key, review['file_digest'])
    send({'type':'result', **result})
    command = receive()
    if command.get('action') == 'rollback': send({'type':'result', **store.rollback(request['operation'])})
    elif command.get('action') != 'finish': raise ValueError('Invalid final command')


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, TypeError, KeyError, KeyboardInterrupt):
        print('PiMux enrollment refused, interrupted or unavailable.', file=sys.stderr)
        raise SystemExit(2) from None
