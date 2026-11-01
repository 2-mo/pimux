#!/usr/bin/env bash
# Install the complete personal terminal into the current user's home.
set -euo pipefail
PIMUX_SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$PIMUX_SOURCE_DIR/pimux"

backup_file() {
    local path=$1 backup
    backup=$(mktemp "${path}.pimux-backup.XXXXXX")
    cp -p -- "$path" "$backup"
    printf 'Backup: %s\n' "$backup"
}

install_asset() {
    local source=$1 destination=$2 mode=$3 temporary
    if [[ -L $destination ]]; then
        printf '目标是已有符号链接，保留原样：%s\n' "$destination" >&2
        return 1
    fi
    if [[ -e $destination ]]; then
        if cmp -s -- "$source" "$destination"; then chmod "$mode" "$destination"; return; fi
        grep -Fq '# pimux-managed:' "$destination" || {
            printf '目标属于其他文件，保留原样：%s\n' "$destination" >&2
            return 1
        }
        backup_file "$destination"
    fi
    temporary=$(mktemp "${destination}.new.XXXXXX")
    cp -- "$source" "$temporary"
    chmod "$mode" "$temporary"
    mv -- "$temporary" "$destination"
}

# Only managed files are replaced; user configuration and system tmux stay intact.
install_files() (
    local target_home=$1 source_dir=$2 config_dir file
    config_dir="$target_home/.config/pimux"
    [[ $target_home != *$'\n'* ]] || { printf 'Installation path must not contain a newline.\n' >&2; return 1; }
    mkdir -p -- "$target_home/.local/bin" "$config_dir"
    exec 9>"$config_dir/install.lock"
    flock 9
    install_asset "$source_dir/pimux" "$target_home/.local/bin/pimux" 755
    install_asset "$source_dir/pimux.conf" "$config_dir/tmux.conf" 644
    for file in ui.bash manager.bash gpu.bash shell.bash bashrc starship.toml uninstall.sh; do
        install_asset "$source_dir/$file" "$config_dir/$file" 644
    done
)

install_starship() (
    if command -v starship >/dev/null 2>&1 || [[ -x $HOME/.local/bin/starship ]]; then
        printf '复用已安装的 Starship。\n'
        return
    fi
    [[ ! -e $HOME/.local/bin/starship && ! -L $HOME/.local/bin/starship ]] || {
        printf '已有 ~/.local/bin/starship 但不可执行，请先检查；保留原文件。\n' >&2
        return 1
    }
    command -v curl >/dev/null || { printf '安装 Starship 需要 curl。\n' >&2; return 1; }
    local installer
    installer=$(mktemp)
    trap 'rm -f -- "$installer"' EXIT
    curl --fail --show-error --silent --location --proto '=https' --tlsv1.2 \
        https://starship.rs/install.sh -o "$installer"
    mkdir -p -- "$HOME/.local/bin"
    sh "$installer" --yes --bin-dir "$HOME/.local/bin"
)

install_dependencies() {
    local command missing=false
    for command in tmux infocmp flock timeout readlink curl; do
        command -v "$command" >/dev/null 2>&1 || missing=true
    done
    if command -v infocmp >/dev/null 2>&1; then
        infocmp tmux-256color >/dev/null 2>&1 || missing=true
    fi
    [[ $missing == true ]] || return 0
    command -v apt-get >/dev/null 2>&1 || {
        printf 'Install Bash 4+, tmux 3.2+, ncurses terminfo, util-linux, coreutils and curl, then rerun this installer.\n' >&2
        return 1
    }
    local -a admin=()
    if (( EUID != 0 )); then
        command -v sudo >/dev/null 2>&1 || { printf 'Missing system dependencies; administrator access is required.\n' >&2; return 1; }
        admin=(sudo)
    fi
    printf 'Installing missing terminal dependencies through apt.\n'
    "${admin[@]}" apt-get update
    "${admin[@]}" apt-get install -y tmux ncurses-term util-linux coreutils curl ca-certificates
}

main() {
    if [[ $# != 0 ]]; then
        printf 'Usage: bash setup-tmux.sh\nInstalls the terminal, complete theme and Starship prompt.\n'
        [[ $# == 1 && ( $1 == --help || $1 == -h ) ]]
        return
    fi
    [[ $(uname -s) == Linux ]] || { printf 'This release supports Linux.\n' >&2; return 1; }
    install_dependencies
    configure_runtime
    local version
    version=$(tmux -V)
    [[ $version =~ ([0-9]+)\.([0-9]+) ]] && \
        (( BASH_REMATCH[1] > 3 || (BASH_REMATCH[1] == 3 && BASH_REMATCH[2] >= 2) )) || {
            printf 'tmux >= 3.2 is required; found %s.\n' "$version" >&2; return 1;
        }
    install_starship
    install_files "$HOME" "$PIMUX_SOURCE_DIR"
    "$HOME/.local/bin/pimux" reload
    printf '\nReady. Open your terminal workspace:\n  %s/.local/bin/pimux\n' "$HOME"
    printf 'Theme, prompt and GPU indicators are enabled automatically. No font installation is required.\n'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
