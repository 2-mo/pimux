# pimux-managed: enforce the same policy on every OpenSSH ProxyJump process.
"""A private argv[0] wrapper is inherited by OpenSSH's implicit jump command."""
import os
from pathlib import Path
import resource
import sys

POLICY = ['StrictHostKeyChecking=yes', 'UpdateHostKeys=no', 'BatchMode=yes',
          'PermitLocalCommand=no', 'KnownHostsCommand=none', 'ForwardAgent=no', 'ClearAllForwardings=yes',
          'ControlMaster=no', 'ControlPath=none', 'ControlPersist=no',
          'ForkAfterAuthentication=no', 'RequestTTY=no', 'RemoteCommand=none',
          'ConnectionAttempts=1', 'LogLevel=DEBUG1']


def credential_policy():
    # Existing matching agent identities remain usable. Loading a file for this
    # invocation must not add an identity or persist its passphrase afterwards.
    return ['AddKeysToAgent=no'] + (['UseKeychain=no'] if sys.platform == 'darwin' else [])


def main():
    directory = Path(os.environ['PIMUX_SSH_LOG_DIR'])
    wrapper = os.environ['PIMUX_SSH_WRAPPER']
    depth = int(os.environ['PIMUX_SSH_DEPTH'])
    if not 0 <= depth < 8 or Path(wrapper).parent != directory:
        raise ValueError('SSH jump limit or invalid private wrapper')
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Unsafe private SSH directory')
    log = directory / ('hop-' + str(depth) + '.log')
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    # Bounds local diagnostics even if a peer induces verbose protocol messages.
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
    os.environ['PIMUX_SSH_DEPTH'] = str(depth + 1)
    args = [wrapper, '-E', str(log)]
    policy = [*credential_policy(), *POLICY]
    if os.environ.get('PIMUX_INTERACTIVE_AUTH') == '1':
        policy = ['BatchMode=no' if option == 'BatchMode=yes' else option for option in policy] + ['NumberOfPasswordPrompts=1']
    for option in policy: args += ['-o', option]
    forwarded = sys.argv[1:]
    if depth and os.environ.get('PIMUX_SSH_JUMP_CONFIG'):
        config = Path(os.environ['PIMUX_SSH_JUMP_CONFIG'])
        if config.parent != directory or config.is_symlink() or not config.is_file():
            raise ValueError('Invalid frozen jump configuration')
        # Implicit ProxyJump only forwards -F, not the destination's -i/-o
        # identity selection. Restore the original inspected Include closure.
        # -F is last-wins, unlike most -o options. Replace the generated -F
        # pair rather than prepending a value that the child would overwrite.
        original = iter(forwarded)
        forwarded = []
        for argument in original:
            if argument == '-F': next(original)
            elif argument.startswith('-F'): continue
            else: forwarded.append(argument)
        forwarded = ['-F', str(config), *forwarded]
    os.execv('/usr/bin/ssh', args + forwarded)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError):
        print('PiMux SSH policy setup failed.', file=sys.stderr)
        raise SystemExit(255) from None
