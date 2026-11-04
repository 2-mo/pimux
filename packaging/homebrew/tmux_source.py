#!/usr/bin/env python3
"""Read-only Homebrew tmux provenance for the shared installer's confirmation flow."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def query(argv):
    env = {**os.environ, 'HOMEBREW_NO_AUTO_UPDATE': '1', 'HOMEBREW_NO_ANALYTICS': '1',
           'HOMEBREW_NO_INSTALL_CLEANUP': '1', 'HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK': '1'}
    result = subprocess.run(argv, env=env, text=True, capture_output=True, timeout=5)
    if result.returncode or len(result.stdout) > 16384:
        raise ValueError('Source query failed; no upgrade proposed')
    return result.stdout.strip()


def inspect(binary, brew=None):
    binary = Path(binary)
    if not binary.is_absolute():
        raise ValueError('The caller must pass the selected absolute tmux path')
    result = {'selected': str(binary), 'source': 'unknown', 'upgrade_argv': None,
              'binary_content_verified': False,
              'requires_confirmation': True, 'running_server_checked': False}
    try:
        resolved = binary.resolve(strict=True)
        result.update(resolved=str(resolved), version_output=query([str(binary), '-V']))
        compatibility = Path(__file__).resolve().parents[2] / 'lib/tmux_compat.bash'
        check = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                                'source "$1" || exit; printf "%s\\n" "$PIMUX_TMUX_MINIMUM"; '
                                'pimux_tmux_version_supported "$2"', 'pimux-tmux-check',
                                str(compatibility), result['version_output']],
                               capture_output=True, text=True, timeout=5)
        if check.returncode not in (0, 1) or not check.stdout.strip():
            raise ValueError('Shared tmux version checker is unavailable')
        result.update(minimum=check.stdout.strip(), supported=check.returncode == 0)
        brew = brew or shutil.which('brew')
        if not brew or not Path(brew).is_absolute():
            raise ValueError('No Homebrew executable available; use the original installation source')
        cellar = Path(query([str(brew), '--cellar', 'tmux']))
        if not cellar.is_absolute():
            raise ValueError('Homebrew returned an invalid cellar')
        parts = resolved.relative_to(cellar.resolve(strict=True)).parts
        if len(parts) != 3 or parts[1:] != ('bin', 'tmux'):
            raise ValueError('Selected tmux is not a Homebrew tmux keg executable')
        receipt = resolved.parent.parent / 'INSTALL_RECEIPT.json'
        if receipt.is_symlink() or not receipt.is_file() or receipt.stat().st_size > 1024 * 1024:
            raise ValueError('Homebrew receipt is unavailable or invalid')
        data = json.loads(receipt.read_text())
        if not isinstance(data, dict) or not isinstance(data.get('source'), dict):
            raise ValueError('Homebrew receipt has invalid source metadata')
        if data['source'].get('tap') != 'homebrew/core':
            raise ValueError('Custom tap or unknown receipt: use its original upgrade instructions')
        result.update(source='homebrew/core/tmux-layout', brew=str(brew))
        current = Path(query([str(brew), '--prefix', '--installed', 'tmux'])) / 'bin/tmux'
        if not current.is_absolute() or current.resolve(strict=True) != resolved:
            raise ValueError('Selection points at an older keg; upgrading will not fix this explicit path')
        if result['supported']:
            result['note'] = 'Selected client meets the shared minimum; no upgrade proposed'
            return result
        result.update(manual_upgrade_argv=[str(brew), 'upgrade', '--formula', 'tmux'],
                      note='The Homebrew receipt has no installed-binary content checksum. '
                           'It cannot rule out a manually replaced executable. No automatic upgrade '
                           'is proposed; review the original installation before using this manual '
                           'command, which may replace modifications and update dependencies. '
                           'Client and running-server versions must be checked separately.')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result['note'] = str(error)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--brew', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.binary, args.brew), indent=2))
