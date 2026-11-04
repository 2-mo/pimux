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
    # The new launcher sources this module immediately; install it first.
    install_asset "$source_dir/lib/tmux_compat.bash" "$config_dir/tmux_compat.bash" 644
    install_asset "$source_dir/bin/pimux" "$target_home/.local/bin/pimux" 755
    install_asset "$source_dir/config/tmux.conf" "$config_dir/tmux.conf" 644
    install_asset "$source_dir/config/starship.toml" "$config_dir/starship.toml" 644
    install_asset "$source_dir/scripts/uninstall.sh" "$config_dir/uninstall.sh" 644
    for file in runtime.bash host_runtime.py hosts.py host_snapshot.py ssh_discovery.py ssh_hop.py access_preview.py access_setup.py access_agent.py access_identity.py access_transport.py ssh_askpass.py ui.bash manager.bash manager_ui.py navigation.py menu_ui.py layout_ui.py gpu.bash gpu.py gpu_ui.py theme.py inspect_ui.py macos.py ports.py network.py window_details.py utility_ui.py environment.py environment_ui.py environment.bash proxy_ui.py proxy_status.py proxy.bash command_status.bash shell.bash bashrc; do
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

install_macos_dependencies() {
    local command version
    for command in tmux infocmp curl python3 ssh ssh-keygen; do
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
    configure_runtime || return 1
    version=$("${PIMUX_COMMAND[0]}" -V) || return 1
    pimux_tmux_version_supported "$version" || {
        printf 'tmux >= %s is required; found %s. Upgrade the selected binary through its original package manager.\n' "$PIMUX_TMUX_MINIMUM" "$version" >&2
        return 1
    }
}

installer_next_step() {
    printf '%s\n' 'Rerun as your normal user after resolving the dependencies:' \
        '  curl -fsSL https://raw.githubusercontent.com/2-mo/pimux/main/install.sh | bash' >&2
}

installer_confirm() (
    local answer
    # The public install command reads its script from a pipe. Never consume it.
    if ! { exec 8<>/dev/tty; } 2>/dev/null; then
        printf 'No controlling terminal; no system packages changed.\n' >&2
        installer_next_step
        return 1
    fi
    printf 'Run the package command above? Type y to continue [y/N]: ' >&8
    IFS= read -r answer <&8 || {
        printf 'Confirmation ended; no system packages changed.\n' >&2
        return 1
    }
    [[ $answer == y || $answer == Y ]] || {
        printf 'Cancelled; no system packages changed.\n' >&2
        return 1
    }
)

installer_uid() { printf '%s\n' "$EUID"; }

apt_tmux_content_matches() {
    local binary=$1 canonical=$2 records digest path extra expected='' actual matches=0
    records=$(dpkg-query --control-show tmux md5sums) || return 1
    while read -r digest path extra; do
        [[ $path == usr/bin/tmux || $path == bin/tmux ]] || continue
        [[ $(readlink -f -- "/$path") == "$canonical" ]] || continue
        [[ $digest =~ ^[0-9a-fA-F]{32}$ && -z $extra ]] || return 1
        expected=$digest
        matches=$((matches + 1))
    done <<< "$records"
    (( matches == 1 )) || return 1
    actual=$(md5sum -- "$binary") || return 1
    actual=${actual%% *}
    [[ $actual == "$expected" ]]
}

apt_owns_tmux() {
    local binary=$1 canonical listed files owner diversion path
    # Custom launchers/symlinks are user-managed, even if they eventually run apt's tmux.
    [[ $binary == /usr/bin/tmux || $binary == /bin/tmux ]] || return 1
    canonical=$(readlink -f -- "$binary") || return 1
    [[ $canonical == /usr/bin/tmux || $canonical == /bin/tmux ]] || return 1
    [[ $(dpkg-query -W -f='${Status}' tmux 2>/dev/null) == 'install ok installed' ]] || return 1
    files=$(dpkg-query -L tmux) || return 1
    while IFS= read -r listed; do
        [[ $listed == /bin/tmux || $listed == /usr/bin/tmux ]] || continue
        [[ $(readlink -f -- "$listed") == "$canonical" ]] || continue
        owner=$(dpkg-query -S "$listed") || return 1
        [[ $owner =~ ^tmux(:[a-z0-9-]+)?:\ (.*)$ && ${BASH_REMATCH[2]} == "$listed" ]] || return 1
        [[ $owner != *$'\n'* ]] || return 1
        for path in "$binary" "$canonical" "$listed"; do
            diversion=$(dpkg-divert --list "$path") || return 1
            [[ -z $diversion ]] || return 1
        done
        apt_tmux_content_matches "$binary" "$canonical"
        return
    done <<< "$files"
    return 1
}

apt_candidate() {
    local package=$1 policy key value
    policy=$(LC_ALL=C apt-cache policy "$package") || return 1
    while read -r key value; do
        if [[ $key == Candidate: && -n $value && $value != '(none)' ]]; then
            printf '%s\n' "$value"
            return 0
        fi
    done <<< "$policy"
    return 1
}

missing_dependency_packages() {
    type -P infocmp >/dev/null && infocmp tmux-256color >/dev/null 2>&1 || printf '%s\n' ncurses-term
    type -P flock >/dev/null || printf '%s\n' util-linux
    { type -P timeout >/dev/null && type -P readlink >/dev/null; } || printf '%s\n' coreutils
    { type -P ss >/dev/null && type -P ip >/dev/null; } || printf '%s\n' iproute2
    { type -P ssh >/dev/null && type -P ssh-keygen >/dev/null; } || printf '%s\n' openssh-client
    type -P curl >/dev/null || printf '%s\n' curl
    return 0
}

install_dependencies() {
    local binary='' version='' package candidate command missing
    local upgrade=false
    local -a packages=() arguments=() admin=()
    PIMUX_TMUX_REPLACED=false
    if [[ $OSTYPE == darwin* ]]; then
        install_macos_dependencies || return 1
        return 0
    fi
    # Runtime configuration can select a different binary from the one on PATH.
    if [[ -f ${PIMUX_RUNTIME_FILE:-$HOME/.config/pimux/runtime.conf} ]] || type -P tmux >/dev/null; then
        configure_runtime || return 1
        binary=${PIMUX_COMMAND[0]}
        version=$("$binary" -V) || { printf 'Cannot read tmux version: %s\n' "$binary" >&2; return 1; }
        printf 'Selected tmux: %s (%s)\n' "$binary" "$version"
        if ! pimux_tmux_version_supported "$version"; then
            [[ $version =~ ^tmux\ [0-9]+\.[0-9]+[a-z]?$ ]] || {
                printf 'Unrecognized tmux version; check this binary manually: %s\n' "$binary" >&2
                return 1
            }
            printf 'tmux >= %s is required for popups, status formats and client-targeted clipboard copying.\n' "$PIMUX_TMUX_MINIMUM" >&2
            upgrade=true
            packages+=(tmux)
        fi
    else
        packages+=(tmux)
    fi
    while IFS= read -r package; do
        [[ -z $package ]] || packages+=("$package")
    done < <(missing_dependency_packages)
    (( ${#packages[@]} )) || return 0
    for command in apt-get apt-cache dpkg-query dpkg-divert; do
        type -P "$command" >/dev/null || {
            printf 'Install tmux >= %s and missing dependencies with their original package manager: %s\n' "$PIMUX_TMUX_MINIMUM" "${packages[*]}" >&2
            installer_next_step
            return 1
        }
    done
    if [[ $upgrade == true ]] && ! apt_owns_tmux "$binary"; then
        printf 'Cannot prove that apt owns %s with unchanged package content and no diversion or custom path. Upgrade it through its original source, or explicitly update runtime.conf to a supported binary.\n' "$binary" >&2
        installer_next_step
        return 1
    fi
    for package in "${packages[@]}"; do
        candidate=$(apt_candidate "$package") || {
            printf 'No apt candidate for %s. Check your configured repositories (apt-cache policy %s); no package changes made.\n' "$package" "$package" >&2
            installer_next_step
            return 1
        }
        if [[ $package == tmux ]] && ! pimux_tmux_package_supported "$candidate"; then
            printf 'apt candidate tmux %s is below %s or unrecognized. Choose a supported package from your distribution; no repositories were added.\n' "$candidate" "$PIMUX_TMUX_MINIMUM" >&2
            installer_next_step
            return 1
        fi
        arguments+=("$package=$candidate")
    done
    if (( $(installer_uid) != 0 )); then
        if ! type -P sudo >/dev/null; then
            printf 'Administrator access is required. Ask an administrator to run:\n  apt-get install --no-remove' >&2
            printf ' %q' "${arguments[@]}" >&2
            printf '\nDo not run the PiMux installer as root.\n' >&2
            installer_next_step
            return 1
        fi
        admin=(sudo --)
        printf 'This package step will request administrator privileges through sudo. PiMux itself stays in your home directory.\n'
    fi
    printf 'Package command (existing tmux servers will not be restarted):\n '
    printf ' %q' "${admin[@]}" apt-get install --no-remove -y "${arguments[@]}"
    printf '\n'
    installer_confirm || return 1
    "${admin[@]}" apt-get install --no-remove -y "${arguments[@]}" || {
        printf 'Package command failed. Check its output; PiMux installation stopped.\n' >&2
        return 1
    }
    if [[ $upgrade == true ]]; then PIMUX_TMUX_REPLACED=true; fi
    configure_runtime || return 1
    version=$("${PIMUX_COMMAND[0]}" -V) || return 1
    pimux_tmux_version_supported "$version" || {
        printf 'Selected binary still does not meet tmux >= %s: %s (%s).\n' "$PIMUX_TMUX_MINIMUM" "${PIMUX_COMMAND[0]}" "$version" >&2
        return 1
    }
    missing=$(missing_dependency_packages)
    [[ -z $missing ]] || { printf 'Dependencies still missing: %s\n' "$missing" >&2; return 1; }
}

reload_compatible_runtime() (
    local disk live
    disk=$("${PIMUX_COMMAND[0]}" -V) || return 1
    printf 'Installed binary: %s (%s)\n' "${PIMUX_COMMAND[0]}" "$disk"
    if live=$(tmux display-message -p '#{version}' 2>/dev/null); then
        printf 'Running server: tmux %s\n' "$live"
        if [[ ${PIMUX_TMUX_REPLACED:-false} == false && $disk == "tmux $live" ]] && pimux_tmux_version_supported "$disk"; then
            # The interactive reload command follows TMUX and visits other runtimes.
            # These launcher helpers retain exactly the command array checked above.
            PIMUX_LAUNCHER="$HOME/.local/bin/pimux"
            update_server_language
            update_server_theme
        else
            printf 'Existing server kept unchanged. Updating the binary does not upgrade a running server. Keep your work; start a new server after its sessions finish naturally.\n'
        fi
    else
        printf 'No server version could be read; no running server was reloaded. New servers use the installed configuration.\n'
    fi
)

main() {
    if [[ $# != 0 ]]; then
        printf 'Usage: bash scripts/setup-tmux.sh\nInstalls the personal terminal and theme. Linux installs Starship; macOS reuses an existing prompt.\n'
        [[ $# == 1 && ( $1 == --help || $1 == -h ) ]]
        return
    fi
    [[ $OSTYPE == linux* || $OSTYPE == darwin* ]] || { printf 'PiMux supports Linux and macOS.\n' >&2; return 1; }
    install_dependencies
    configure_runtime
    if [[ $OSTYPE != darwin* ]]; then install_starship
    else printf 'macOS source preview: using an existing Starship prompt if available.\n'; fi
    install_gpu_runtime "$HOME" "$PIMUX_SOURCE_DIR"
    install_files "$HOME" "$PIMUX_SOURCE_DIR"
    if [[ $OSTYPE == darwin* && ! -e $HOME/.config/pimux/runtime.conf && ! -L $HOME/.config/pimux/runtime.conf ]]; then
        # A literal, private runtime pin; never replace a user's existing selection.
        (umask 077; set -C; printf '%s\npimux\n%s\n' "${PIMUX_COMMAND[0]}" "${PIMUX_COMMAND[0]}" > "$HOME/.config/pimux/runtime.conf")
    fi
    reload_compatible_runtime
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
