"""Create/remove two task-owned Docker SSH endpoints; never changes the host sshd."""
import argparse
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
import uuid


def run(*argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop'])
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    manifest = args.directory / 'manifest.json'
    if args.action == 'stop':
        data = json.loads(manifest.read_text())
        for name in data['containers'].values():
            if not name.startswith('pimux-ssh-fixture-'): raise ValueError('Not a fixture container')
            run('docker', 'rm', '-f', name)
        return
    args.directory.mkdir(mode=0o700)  # Refuse reuse after uncertain setup outcomes.
    names = {}
    data = {'version': 1, 'containers': names, 'hosts': []}
    manifest.write_text(json.dumps(data))
    try:
        run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(args.directory / 'client_key'))
        public = (args.directory / 'client_key.pub').read_text()
        known = []
        for label in ('alpha', 'beta'):
            root = args.directory / label
            root.mkdir(mode=0o755)
            (root / 'client_key.pub').write_text(public)
            run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(root / 'host_key'))
            node = uuid.uuid4().hex
            name = 'pimux-ssh-fixture-' + label + '-' + uuid.uuid4().hex[:8]
            names[label] = name
            manifest.write_text(json.dumps(data))
            run('docker', 'run', '-d', '--name', name, '--hostname', 'fixture-' + label,
                '--publish', '127.0.0.1::2222', '--env', 'FIXTURE_NODE_ID=' + node,
                '--mount', 'type=bind,source=' + str(root) + ',target=/fixture,readonly', 'pimux-ssh-fixture')
            binding = run('docker', 'port', name, '2222/tcp')
            if not binding.startswith('127.0.0.1:'): raise ValueError('Non-loopback fixture binding')
            port = int(binding.split(':')[1])
            key = ' '.join((root / 'host_key.pub').read_text().split()[:2])
            known.append(f'[127.0.0.1]:{port} {key}\n')
            data['hosts'].append(dict(host_id=label, name='Fixture ' + label, address='127.0.0.1', port=port,
                user='fixture', node_id=node, known_hosts=str(args.directory / 'known_hosts'),
                identity_file=str(args.directory / 'client_key'), socket='pimux', timeout=5))
            manifest.write_text(json.dumps(data, indent=2))
            end = time.monotonic() + 10
            while True:
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.2) as connection:
                        if connection.recv(100).startswith(b'SSH-2.0-'): break
                except OSError:
                    if time.monotonic() >= end: raise
                    time.sleep(.1)
        (args.directory / 'known_hosts').write_text(''.join(known))
        print(manifest)
    except BaseException:
        for name in names.values():
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True)
        raise


if __name__ == '__main__': main()
