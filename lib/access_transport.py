# pimux-managed: bounded interactive SSH channel for explicit enrollment only.
import asyncio
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import termios
import time

import hosts
from ssh_discovery import inspected_configuration


def configuration_digest(host):
    config = inspected_configuration(host['ssh_config']) if 'ssh_config' in host else None
    return hashlib.sha256(json.dumps([host, config], sort_keys=True).encode()).hexdigest()


@contextlib.contextmanager
def terminal_state(tty):
    """The parent restores attributes even when a killed askpass cannot unwind."""
    if tty is None:
        yield
        return
    if not isinstance(tty, str) or not tty.startswith('/dev/'):
        raise ValueError('No authentication terminal')
    descriptor = os.open(tty, os.O_RDWR | os.O_NOCTTY)
    saved = None
    try:
        if not os.isatty(descriptor) or not stat.S_ISCHR(os.fstat(descriptor).st_mode):
            raise ValueError('Invalid authentication terminal')
        saved = termios.tcgetattr(descriptor)
        yield
    finally:
        try:
            if saved is not None:
                # TCSAFLUSH waits for output drain and can block indefinitely
                # on a Darwin PTY whose reader stopped during cancellation.
                termios.tcsetattr(descriptor, termios.TCSANOW, saved)
                termios.tcflush(descriptor, termios.TCIFLUSH)
        finally: os.close(descriptor)


@contextlib.contextmanager
def connection(host, tty=None, key_only=None):
    hosts.validate_host(host)
    if key_only:
        value = str(key_only)
        if (not value.startswith('/') or '%' in value or '${' in value
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError('Selected identity requires an absolute literal path without SSH expansion tokens')
    with terminal_state(tty), tempfile.TemporaryDirectory(prefix='pimux-access-', dir='/tmp') as directory:
        root = Path(directory)
        selected = host.copy()
        jump_config = None
        if 'ssh_config' in host:
            if key_only:
                selected['ssh_config'], jump_config, _ = inspected_configuration(host['ssh_config'], root, selected_identity=True)
            else:
                selected['ssh_config'], _ = inspected_configuration(host['ssh_config'], root)
        elif key_only:
            selected['identity_file'] = str(key_only)
        wrapper = root / 'ssh'
        helper = Path(__file__).with_name('ssh_hop.py')
        wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -I -S ' + shlex.quote(str(helper)) + ' "$@"\n')
        wrapper.chmod(0o700)
        env = {**os.environ, 'PIMUX_SSH_LOG_DIR':directory, 'PIMUX_SSH_WRAPPER':str(wrapper), 'PIMUX_SSH_DEPTH':'0', 'PIMUX_INTERACTIVE_AUTH':'0'}
        # Clear inherited policy inputs before setting this connection's values.
        env.pop('PIMUX_SSH_JUMP_CONFIG', None)
        if jump_config: env['PIMUX_SSH_JUMP_CONFIG'] = jump_config
        argv = [str(wrapper), *hosts.ssh_command(selected)[1:]]
        if tty:
            askpass = root / 'askpass'
            askpass.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -I -S ' +
                              shlex.quote(str(Path(__file__).with_name('ssh_askpass.py'))) + ' "$@"\n')
            askpass.chmod(0o700)
            env.update(PIMUX_AUTH_TTY=tty, PIMUX_INTERACTIVE_AUTH='1', SSH_ASKPASS=str(askpass),
                       SSH_ASKPASS_REQUIRE='force', DISPLAY='pimux-auth')
        if key_only:
            # All destination config identities have been removed from its
            # frozen copy. Disable automatic certificates for this public-key
            # workflow; jump clients retain their own identities/certificates.
            argv[1:1] = ['-i', str(key_only), '-o', 'IdentityFile=none', '-o', 'CertificateFile=none', '-o', 'IdentitiesOnly=yes', '-o', 'PreferredAuthentications=publickey',
                          '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no']
        yield argv, env, root


def verified_host_key(root):
    data = (root / 'hop-0.log').read_bytes()
    if len(data) > 65536: raise ValueError('SSH diagnostic output limit')
    matches = re.findall(rb'^debug1: Server host key: ([a-zA-Z0-9@._+-]+) (SHA256:[A-Za-z0-9+/]+)\r?$', data, re.MULTILINE)
    if len(matches) != 1: raise ValueError('Destination host key evidence unavailable')
    algorithm, fingerprint = matches[0]
    return {'algorithm':algorithm.decode(), 'fingerprint':fingerprint.decode()}


def accepted_public_key(root, fingerprint):
    data = (root / 'hop-0.log').read_bytes()
    accepted = re.findall(rb'^debug1: Server accepts key: .* (SHA256:[A-Za-z0-9+/]+)(?: .*|)\r?$', data, re.MULTILINE)
    return bool(accepted and accepted[-1].decode() == fingerprint and b'using "publickey"' in data)


class Channel:
    def __init__(self, argv, env, timeout=30):
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True, env=env)
        self.selector = selectors.DefaultSelector()
        self.output, self.errors, self.pending = bytearray(), bytearray(), bytearray()
        self.timeout = timeout
        self.closed = False
        self.eof = False
        for stream, data in ((self.process.stdout, self.output), (self.process.stderr, self.errors)):
            os.set_blocking(stream.fileno(), False)
            self.selector.register(stream, selectors.EVENT_READ, data)
        os.set_blocking(self.process.stdin.fileno(), False)

    async def pump(self, end):
        if time.monotonic() >= end: raise TimeoutError('Enrollment channel deadline exceeded')
        if self.pending:
            try:
                count = os.write(self.process.stdin.fileno(), self.pending[:65536])
                del self.pending[:count]
            except BlockingIOError: pass
        for key, _ in self.selector.select(0):
            try: chunk = os.read(key.fd, 65536)
            except BlockingIOError: continue
            if chunk:
                key.data.extend(chunk)
                if len(key.data) > 65536: raise ValueError('Enrollment output limit')
            else: self.selector.unregister(key.fileobj)
        if self.process.poll() is not None and not self.selector.get_map(): self.eof = True
        await asyncio.sleep(.005)

    def disconnected(self):
        root=Path(self.process.args[0]).parent
        logs=b''.join(path.read_bytes()[:65536] for path in root.glob('hop-*.log'))
        if b'Permission denied' in logs:
            return ConnectionError('SSH authentication denied; no credentials were stored. Jump hosts, the target or MFA may require separate authentication.')
        if b'Host key verification failed' in logs or b'REMOTE HOST IDENTIFICATION HAS CHANGED' in logs:
            return ConnectionError('SSH host identity verification failed; no authorization was changed.')
        return ConnectionError('Enrollment SSH channel closed')

    async def send(self, data):
        self.pending.extend(data)
        end = time.monotonic() + self.timeout
        while self.pending:
            if self.eof: raise self.disconnected()
            await self.pump(end)

    async def receive(self):
        end = time.monotonic() + self.timeout
        while b'\n' not in self.output:
            if self.eof: raise self.disconnected()
            await self.pump(end)
        header = bytes(self.output).split(b'\n', 1)[0]
        match = re.fullmatch(rb'PIMUX-ACCESS/1 ([0-9]{1,5})', header)
        if not match: raise ValueError('Invalid enrollment frame')
        size = int(match[1]); length = len(header) + 1 + size + 1
        if size > 60000: raise ValueError('Enrollment frame limit')
        while len(self.output) < length:
            if self.eof: raise self.disconnected()
            await self.pump(end)
        frame = bytes(self.output[:length]); del self.output[:length]
        if frame[-1:] != b'\n': raise ValueError('Invalid enrollment frame terminator')
        data = hosts.strict_json(frame[len(header)+1:-1])
        if not isinstance(data, dict): raise ValueError('Invalid enrollment response')
        return data

    def close(self):
        if self.closed: return
        self.closed = True
        try:
            # Darwin reports EPERM for an unreaped zombie-only process group.
            # Reap an exited leader before signaling its remaining descendants.
            try: self.process.wait(timeout=.1)
            except subprocess.TimeoutExpired: pass
            try: os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            except PermissionError as error:
                # Exit can race the preceding wait/poll on Darwin. Only accept
                # EPERM as an exit race after waitpid actually reaps the leader.
                try: self.process.wait(timeout=.25)
                except subprocess.TimeoutExpired: raise error
                try: os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
        finally:
            self.selector.close()
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr): stream.close()
            try: self.process.wait(timeout=2)
            except subprocess.TimeoutExpired: pass

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
