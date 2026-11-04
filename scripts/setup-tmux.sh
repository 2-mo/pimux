#!/usr/bin/env bash
# Install the complete personal terminal into the current user's home.
set -euo pipefail
PIMUX_SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$PIMUX_SOURCE_DIR/lib/runtime.bash"
pimux_bootstrap "${BASH_SOURCE[0]}" "$@" || { return 1 2>/dev/null || exit 1; }
source "$PIMUX_SOURCE_DIR/bin/pimux"

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

install_command_path() {
    local target_home=$1 file login_file=.profile
    local line='case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac # pimux: command path'
    local -a files=(.bashrc)
    if [[ -f $target_home/.bash_profile ]]; then login_file=.bash_profile
    elif [[ -f $target_home/.bash_login ]]; then login_file=.bash_login
    fi
    files+=("$login_file")
    if [[ ${SHELL:-} == */zsh || -e $target_home/.zshrc || -e $target_home/.zprofile ]]; then
        files+=(.zshrc .zprofile)
    fi
    for file in "${files[@]}"; do
        file="$target_home/$file"
        if [[ -f $file ]]; then
            grep -Fxq -- "$line" "$file" && continue
            backup_file "$file"
        fi
        # Append through existing symlinks, keeping user content and permissions.
        printf '\n%s\n' "$line" >> "$file"
    done
}

# Replace managed assets and add only the standard user command directory to PATH.
install_files() (
    local target_home=$1 source_dir=$2 config_dir file
    config_dir="$target_home/.config/pimux"
    [[ $target_home != *$'\n'* ]] || { printf 'Installation path must not contain a newline.\n' >&2; return 1; }
    mkdir -p -- "$target_home/.local/bin" "$config_dir"
    exec 9>"$config_dir/install.lock"
    pimux_lock 9
    install_asset "$source_dir/bin/pimux" "$target_home/.local/bin/pimux" 755
    install_asset "$source_dir/config/tmux.conf" "$config_dir/tmux.conf" 644
    install_asset "$source_dir/config/starship.toml" "$config_dir/starship.toml" 644
    install_asset "$source_dir/scripts/uninstall.sh" "$config_dir/uninstall.sh" 644
    for file in runtime.bash host_runtime.py ui.bash manager.bash manager_ui.py navigation.py menu_ui.py layout_ui.py gpu.bash gpu.py gpu_ui.py inspect_ui.py macos.py ports.py network.py window_details.py utility_ui.py environment.py environment_ui.py environment.bash proxy_ui.py proxy_status.py proxy.bash command_status.bash shell.bash bashrc; do
        install_asset "$source_dir/lib/$file" "$config_dir/$file" 644
    done
    local shell_config
    shell_config=$(mktemp)
    trap 'rm -f -- "$shell_config"' EXIT
    printf '# pimux-managed: Bash runtime\n%s\n' "$PIMUX_BASH" > "$shell_config"
    install_asset "$shell_config" "$config_dir/shell.conf" 600
    install_command_path "$target_home"
)

install_gpu_runtime() (
    local target_home=$1 source_dir=$2 runtime uv installer
    runtime="$target_home/.local/share/pimux"
    if command -v uv >/dev/null 2>&1; then
        uv=$(command -v uv)
    elif [[ -x $runtime/uv/uv ]]; then
        uv="$runtime/uv/uv"
    else
        installer=$(mktemp)
        trap 'rm -f -- "$installer"' EXIT
        curl --fail --show-error --silent --location --proto '=https' --tlsv1.2 \
            https://astral.sh/uv/install.sh -o "$installer"
        UV_UNMANAGED_INSTALL="$runtime/uv" sh "$installer"
        uv="$runtime/uv/uv"
    fi
    # Keep Python packages separate from the user's active project environment.
    env -u VIRTUAL_ENV UV_PROJECT_ENVIRONMENT="$runtime/venv" \
        "$uv" sync --project "$source_dir" --locked --no-dev
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
    if [[ $OSTYPE == darwin* ]]; then
        for command in tmux infocmp curl python3; do
            type -P "$command" >/dev/null 2>&1 || {
                printf 'Missing macOS dependency: %s. Provide Bash >= 5.1, tmux >= 3.2, Python >= 3.10 and tmux-256color terminfo on PATH; no global packages are installed automatically.\n' "$command" >&2
                return 1
            }
        done
        python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || {
            printf 'PiMux requires Python >= 3.10.\n' >&2; return 1;
        }
        infocmp tmux-256color >/dev/null 2>&1 || {
            printf 'Missing tmux-256color terminfo.\n' >&2; return 1;
        }
        return
    fi
    for command in tmux infocmp flock timeout readlink curl ss ip; do
        # The launcher defines a tmux function; check executable files on PATH.
        type -P "$command" >/dev/null 2>&1 || missing=true
    done
    if command -v infocmp >/dev/null 2>&1; then
        infocmp tmux-256color >/dev/null 2>&1 || missing=true
    fi
    [[ $missing == true ]] || return 0
    command -v apt-get >/dev/null 2>&1 || {
        printf 'Install Bash 5.1+, tmux 3.2+, ncurses terminfo, util-linux, coreutils, iproute2 and curl, then rerun this installer.\n' >&2
        return 1
    }
    local -a admin=()
    if (( EUID != 0 )); then
        command -v sudo >/dev/null 2>&1 || { printf 'Missing system dependencies; administrator access is required.\n' >&2; return 1; }
        admin=(sudo)
    fi
    printf 'Installing missing terminal dependencies through apt.\n'
    "${admin[@]}" apt-get update
    "${admin[@]}" apt-get install -y tmux ncurses-term util-linux coreutils iproute2 curl ca-certificates
}

main() {
    if [[ $# != 0 ]]; then
        printf 'Usage: bash scripts/setup-tmux.sh\nInstalls the terminal, complete theme and Starship prompt.\n'
        [[ $# == 1 && ( $1 == --help || $1 == -h ) ]]
        return
    fi
    [[ $OSTYPE == linux* || $OSTYPE == darwin* ]] || { printf 'PiMux supports Linux and macOS.\n' >&2; return 1; }
    install_dependencies
    configure_runtime
    local version
    version=$(tmux -V)
    [[ $version =~ ([0-9]+)\.([0-9]+) ]] && \
        (( BASH_REMATCH[1] > 3 || (BASH_REMATCH[1] == 3 && BASH_REMATCH[2] >= 2) )) || {
            printf 'tmux >= 3.2 is required; found %s.\n' "$version" >&2; return 1;
        }
    if [[ $OSTYPE != darwin* ]]; then install_starship
    else printf 'macOS source preview: using an existing Starship prompt if available.\n'; fi
    install_gpu_runtime "$HOME" "$PIMUX_SOURCE_DIR"
    install_files "$HOME" "$PIMUX_SOURCE_DIR"
    if [[ $OSTYPE == darwin* && ! -e $HOME/.config/pimux/runtime.conf && ! -L $HOME/.config/pimux/runtime.conf ]]; then
        # A literal, private runtime pin; never replace a user's existing selection.
        (umask 077; set -C; printf '%s\npimux\n%s\n' "${PIMUX_COMMAND[0]}" "${PIMUX_COMMAND[0]}" > "$HOME/.config/pimux/runtime.conf")
    fi
    "$HOME/.local/bin/pimux" reload
    printf '\nPiMux %s is ready. Open your terminal workspace:\n  pimux\n' "$PIMUX_VERSION"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) printf 'For this terminal, run: export PATH="$HOME/.local/bin:$PATH"\nNew Bash and Zsh terminals are configured automatically.\n' ;;
    esac
    printf 'Theme and available prompt integrations are enabled. GPU telemetry depends on NVIDIA tooling; Apple GPU metrics are not supported.\n'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
