# pimux-managed: public-key discovery and read-only authorization preview; no writer.
"""An explicit target is required; this module cannot install keys or confirm writes."""
import base64
import hashlib
from pathlib import Path
import re
import stat
import subprocess


def public_key(path):
    path = Path(path)
    if path.suffix != '.pub' or path.is_symlink(): raise ValueError('Select a regular public .pub file')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 16384: raise ValueError('Invalid public key file')
    source = path.read_text().strip()
    if '\n' in source or '\r' in source: raise ValueError('Choose exactly one public key')
    fields = source.split()
    if len(fields) < 2 or not fields[0].startswith(('ssh-', 'ecdsa-', 'sk-')):
        raise ValueError('Not an OpenSSH public key')
    blob = base64.b64decode(fields[1], validate=True)
    if len(blob) < 4: raise ValueError('Invalid public key')
    size = int.from_bytes(blob[:4], 'big')
    if blob[4:4 + size].decode() != fields[0]: raise ValueError('Public key algorithm mismatch')
    result = subprocess.run(['/usr/bin/ssh-keygen', '-l', '-E', 'sha256', '-f', str(path)],
                             capture_output=True, text=True, timeout=2)
    fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
    if result.returncode or fingerprint not in result.stdout: raise ValueError('Invalid public key')
    return dict(path=str(path.absolute()), algorithm=fields[0], fingerprint=fingerprint, public_line=' '.join(fields[:2]))


def candidates(home=None, extra=()):
    home = Path.home() if home is None else Path(home)
    paths = list((home / '.ssh').glob('*.pub')) + [Path(path) for path in extra]
    found = {}
    for path in sorted(set(paths)):
        try: candidate = public_key(path)
        except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired): continue
        found.setdefault(candidate['fingerprint'], candidate)
    return list(found.values())


async def preview(host, key=None, home=None):
    from hosts import fetch_host
    from ssh_discovery import discover
    if key is not None:
        options = [public_key(key)]
    else:
        discovered = discover(home=home, config_files=[host['ssh_config']] if 'ssh_config' in host else None)
        options = candidates(home=home, extra=discovered['public_key_paths'])
    result = dict(mode='preview_only', writes_supported=False, target=host['host_id'], candidates=options,
                  selected_key=None, status='choose_public_key', requires_write_confirmation=False)
    if key is None and 'match_not_evaluated' in discovered['notes']:
        result['reason'] = 'Conditional SSH rules were not evaluated; select the intended public key explicitly.'
        return result
    if len(options) != 1:
        if not options: result['status'] = 'no_public_key_available'
        return result
    chosen = options[0]
    result['selected_key'] = chosen
    remote = await fetch_host(host, chosen['fingerprint'])
    result['connection'] = remote
    if remote['status'] != 'connected' or remote['host_key'] is None:
        result['status'] = 'target_not_verified'
        return result
    cap = remote['snapshot']['capabilities']['access']
    if cap['status'] != 'available':
        result['status'] = 'authorization_state_unavailable'
        return result
    state = cap['data']
    result['authorization_scope'] = state['scope']
    if state['state'] == 'present':
        result['status'] = 'already_listed_restricted' if state['restricted'] else 'already_listed'
        result['proposed_change'] = 'none; preserve existing authorizations and restrictions'
    else:
        result['status'] = 'authorization_missing'
        result['requires_write_confirmation'] = True
        result['proposed_change'] = 'Add this public key for authentication as the verified account, under existing SSH policy; no privilege elevation.'
        result['next_step'] = 'Persistent authorization changes are not available in this preview.'
    return result


def render_preview(result):
    from hosts import safe_text
    lines = ['Public-key authorization preview · ' + result['status'], 'No authorization changes will be made.']
    for candidate in result['candidates']:
        lines.append('Public key: ' + safe_text(candidate['fingerprint']) + ' · ' + safe_text(candidate['path']))
    remote = result.get('connection')
    if remote and remote['status'] == 'connected':
        snapshot = remote['snapshot']
        lines.append('Target: ' + safe_text(snapshot['account']['name']) + '@' + safe_text(snapshot['hostname']) + ' · ' + remote['host_id'])
        lines.append('Server ID: ' + snapshot['node_id'])
        if remote['host_key']: lines.append('Verified host key: ' + remote['host_key']['fingerprint'])
        lines.append('Coverage: standard user authorized_keys; custom server policy is not inferred.')
    elif remote: lines.append('Connection: ' + remote['status'])
    if 'proposed_change' in result: lines.append(result['proposed_change'])
    if 'next_step' in result: lines.append(result['next_step'])
    if result['status'] == 'choose_public_key': lines.append('Choose one public key with --key; no connection was made.')
    return '\n'.join(lines)
