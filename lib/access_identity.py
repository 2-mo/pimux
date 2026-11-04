# pimux-managed: public metadata for an explicitly selected, verified identity.
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from access_preview import public_key


class SelectionError(ValueError): pass


def identity(key):
    private = Path(key['path'][:-4])
    # Metadata only: native OpenSSH/agent opens its own private material.
    return private if private.is_file() and not private.is_symlink() else Path(key['path'])


def directory(): return Path.home() / '.local/state/pimux/identities'


def location(host):
    import hosts
    hosts.validate_host(host)
    return directory() / (host['host_id'] + '.json')


def safe_directory(root, create=False):
    if create: root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for path in (root, *root.parents):
        if path.is_symlink(): raise SelectionError('Unsafe selected-identity directory')
    info = root.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SelectionError('Unsafe selected-identity directory')


def remember(host, key, review):
    from access_transport import configuration_digest
    if configuration_digest(host) != review['configuration_digest'] or public_key(key['path']) != key:
        raise SelectionError('Target configuration or public key changed; select and verify again')
    path = location(host)
    safe_directory(path.parent, create=True)
    record = {'version': 1, 'host_id': host['host_id'], 'key': key,
              'binding': {name: review[name] for name in ('configuration_digest', 'node_id', 'account', 'uid', 'host_key')}}
    descriptor, temporary = tempfile.mkstemp(prefix='.identity-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(record, stream, sort_keys=True); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def load(host):
    from access_transport import configuration_digest
    path = location(host)
    if not path.exists() and not path.is_symlink(): return None
    try:
        safe_directory(path.parent)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'r') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 65536:
                raise ValueError('Unsafe identity record')
            record = json.load(stream)
        if (record['version'] != 1 or record['host_id'] != host['host_id']
                or record['binding']['configuration_digest'] != configuration_digest(host)
                or public_key(record['key']['path']) != record['key']):
            raise ValueError('Changed identity inputs')
        binding = record['binding']
        if (not isinstance(binding['node_id'], str) or type(binding['uid']) is not int
                or not isinstance(binding['account'], str) or not isinstance(binding['host_key'], dict)):
            raise ValueError('Invalid identity binding')
        return record
    except (OSError, ValueError, TypeError, KeyError, RecursionError, subprocess.TimeoutExpired) as error:
        raise SelectionError('Saved identity cannot be reused; use identity-reset for this target, then access-setup to select and verify again') from error


def matches(record, snapshot, host_key):
    binding = record['binding']
    return (snapshot['node_id'] == binding['node_id'] and host_key == binding['host_key']
            and snapshot['account'] == {'name': binding['account'], 'uid': binding['uid']})


def forget(host):
    path = location(host)
    if path.exists() or path.is_symlink():
        safe_directory(path.parent)
        path.unlink()
