# pimux-managed: Bash 3.2-readable bootstrap and platform boundary.
PIMUX_RUNTIME_DIR=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

pimux_valid_bash() {
    [[ $1 == /* && -x $1 && $1 != *$'\n'* ]] &&
        "$1" --noprofile --norc -c '(( BASH_VERSINFO[0] > 5 || (BASH_VERSINFO[0] == 5 && BASH_VERSINFO[1] >= 1) ))' >/dev/null 2>&1
}

pimux_bootstrap() {
    local script=$1 candidate=${PIMUX_BASH:-} marker='' extra='' file=${PIMUX_SHELL_FILE:-$HOME/.config/pimux/shell.conf}
    shift
    if [[ -z $candidate && -f $file ]]; then
        local invalid=false
        { IFS= read -r marker || invalid=true; IFS= read -r candidate || invalid=true;
          if IFS= read -r extra || [[ -n $extra ]]; then invalid=true; fi; } < "$file"
        if [[ $invalid == true || $marker != '# pimux-managed: Bash runtime' || -z $candidate ]]; then
            printf 'Invalid PiMux shell runtime configuration: %s\n' "$file" >&2
            return 1
        fi
    fi
    if [[ -n $candidate ]]; then
        pimux_valid_bash "$candidate" || {
            printf 'PiMux requires Bash >= 5.1; configured executable is unavailable or too old: %s\n' "$candidate" >&2
            return 1
        }
    else
        for candidate in "$BASH" /opt/homebrew/bin/bash /usr/local/bin/bash "$(type -P bash)"; do
            pimux_valid_bash "$candidate" && break
            candidate=''
        done
        [[ -n $candidate ]] || {
            printf 'PiMux requires Bash >= 5.1. Set PIMUX_BASH to an installed modern Bash executable.\n' >&2
            return 1
        }
    fi
    export PIMUX_BASH=$candidate
    if [[ ! $BASH -ef $candidate && $script == "$0" ]]; then
        exec "$candidate" "$script" "$@"
    fi
    if (( BASH_VERSINFO[0] < 5 || (BASH_VERSINFO[0] == 5 && BASH_VERSINFO[1] < 1) )); then
        printf 'Source PiMux with Bash >= 5.1: %s\n' "$candidate" >&2
        return 1
    fi
    # Preserve the user's tool precedence when PATH already resolves this Bash.
    if [[ ! $(type -P bash) -ef $candidate ]]; then
        export PATH="${candidate%/*}:$PATH"
    fi
}

pimux_host_python() {
    local python="$HOME/.local/share/pimux/venv/bin/python"
    [[ ! -x $PIMUX_RUNTIME_DIR/../.venv/bin/python ]] || python="$PIMUX_RUNTIME_DIR/../.venv/bin/python"
    [[ -x $python ]] || python=$(type -P python3)
    [[ -x $python ]] || { printf 'PiMux platform helpers require Python 3.10+.\n' >&2; return 1; }
    "$python" -E "$PIMUX_RUNTIME_DIR/host_runtime.py" "$@"
}

pimux_realpath() {
    if [[ $OSTYPE == darwin* ]]; then pimux_host_python realpath "$1"
    else readlink -m -- "$1"; fi
}

pimux_lock() {
    if [[ $OSTYPE == darwin* ]]; then pimux_host_python lock "$1"
    else flock "$1"; fi
}

pimux_signature() {
    if [[ $OSTYPE == darwin* ]]; then pimux_host_python signature "$1"
    else stat -Lc '%i:%s:%y' -- "$1"; fi
}

pimux_timeout() {
    if [[ $OSTYPE == darwin* ]]; then pimux_host_python timeout "$@"
    else timeout -k 1 "$@"; fi
}

pimux_process_cwd() {
    if [[ $OSTYPE == darwin* ]]; then pimux_host_python cwd "$1"
    else readlink -- "/proc/$1/cwd"; fi
}
