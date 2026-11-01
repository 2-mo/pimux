#!/usr/bin/env bash
# pimux-managed: remove only the managed command; retain settings and live sessions.
set -euo pipefail

uninstall_launcher() {
    local target_home=$1 launcher="$1/.local/bin/pimux"
    if [[ ! -e $launcher && ! -L $launcher ]]; then
        printf 'PiMux is already uninstalled. Settings have been kept.\n'
        return
    fi
    if [[ -L $launcher ]] || ! grep -Fq '# pimux-managed:' "$launcher"; then
        printf 'Refusing to remove an unrelated file or symlink: %s\n' "$launcher" >&2
        return 1
    fi
    rm -- "$launcher"
    printf 'PiMux launcher removed. Settings remain in %s/.config/pimux.\n' "$target_home"
    printf 'Running tasks and the shared Starship installation have been kept.\n'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    [[ $# == 0 ]] || { printf 'Usage: bash uninstall.sh\n' >&2; exit 2; }
    uninstall_launcher "$HOME"
fi
