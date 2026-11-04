"""Fault injection confined to disposable test containers; not shipped to users."""
import os
from pathlib import Path
import sys
import time
import json
import socket

mode_file = Path('/tmp/fixture-mode')
mode = mode_file.read_text().strip() if mode_file.exists() else 'normal'
if mode in {'enrollment_drop_after_append','enrollment_drop_before_append'}:
    # Execute the product agent, then terminate the real SSH channel before its
    # successful write acknowledgement reaches the client.
    length=int(sys.stdin.buffer.readline());code=sys.stdin.buffer.read(length)
    namespace={'__name__':'fixture_enrollment'}
    exec(compile(code,'<fixture-enrollment>','exec'),namespace)
    original=namespace['send']
    def dropped(data):
        if data.get('type')=='result' and data.get('state')=='applied': os._exit(255)
        return original(data)
    namespace['send']=dropped
    if mode=='enrollment_drop_before_append': namespace['Store'].apply=lambda *_args: os._exit(255)
    namespace['main']()
    raise SystemExit(0)
if mode == 'disconnect': raise SystemExit(255)
if mode == 'timeout':
    time.sleep(8)
    raise SystemExit(1)
if mode == 'version':
    sys.stdout.buffer.write(b'PIMUX-SNAPSHOT/99 2\n{}\n')
    raise SystemExit(0)
if mode == 'bad_data':
    sys.stdout.buffer.write(b'PIMUX-SNAPSHOT/1 2\n{}\n')
    raise SystemExit(0)
if mode == 'pollution': os.write(1, b'Unexpected login output\n')
if mode == 'forged_stderr': os.write(2, b'debug1: Server host key: ssh-ed25519 SHA256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB\n')
if mode == 'stderr_flood':
    os.write(2, b'x' * (2 * 1024 * 1024))
    raise SystemExit(0)
if mode == 'huge_number':
    length = int(sys.stdin.buffer.readline())
    sys.stdin.buffer.read(length)
    request = json.loads(sys.stdin.buffer.read())
    data = dict(protocol='pimux.snapshot', version=1, request_id=request['request_id'], host_id=request['host_id'],
        node_id=Path('/etc/machine-id').read_text().strip(), hostname=socket.gethostname(), platform='linux',
        socket=request['socket'], account={'name':'fixture', 'uid':os.getuid()},
        capabilities={name:dict(status='available',reason='',data=value) for name,value in {
            'sessions':[], 'network':[], 'gpu':[], 'resources':{'load':[10**400,0,0], 'memory_total_kib':10, 'memory_available_kib':5}}.items()})
    body = json.dumps(data).encode()
    os.write(1, b'PIMUX-SNAPSHOT/1 ' + str(len(body)).encode() + b'\n' + body + b'\n')
    raise SystemExit(0)
if mode == 'flood':
    os.write(1, b'x' * (2 * 1024 * 1024))
    raise SystemExit(0)
if mode == 'denied': os.environ['PATH'] = '/opt/pimux-fixture/denied:' + os.environ['PATH']
if mode == 'slow_query': os.environ['PATH'] = '/opt/pimux-fixture/slow:' + os.environ['PATH']
# This is the same shell execution boundary as sshd; the product sends one fixed command.
os.execl('/bin/sh', 'sh', '-c', os.environ['SSH_ORIGINAL_COMMAND'])
