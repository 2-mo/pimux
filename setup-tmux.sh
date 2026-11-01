#!/usr/bin/env bash
# Install piux into the current user's home without depending on the checkout.
set -euo pipefail
PIUX_SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$PIUX_SOURCE_DIR/piux"

backup_file() {
    local path=$1 backup
    backup=$(mktemp "${path}.piux-backup.XXXXXX")
    cp -p -- "$path" "$backup"
    printf '备份：%s\n' "$backup"
}

quote_tmux() {
    local value=$1
    value=${value//\\/\\\\}
    value=${value//\"/\\\"}
    value=${value//\$/\\\$}
    printf '"%s"' "$value"
}

is_pimux_install() {
    local launcher="$1/.local/bin/pimux"
    [[ -f $launcher && ! -L $launcher ]] && grep -Fq '# pimux-managed:' "$launcher"
}

copy_without_legacy_reference() {
    local source=$1 destination=$2 marker=$3 include=$4 line
    cp -p -- "$source" "$destination"
    : > "$destination"
    while IFS= read -r line || [[ -n $line ]]; do
        if [[ $line != "$marker" && $line != "$include" ]]; then
            printf '%s\n' "$line" >> "$destination"
        fi
    done < "$source"
}

install_asset() {
    local source=$1 destination=$2 mode=$3 temporary
    if [[ -L $destination ]]; then
        printf '目标是已有符号链接，保留原样：%s\n' "$destination" >&2
        return 1
    fi
    if [[ -e $destination ]]; then
        if cmp -s -- "$source" "$destination"; then chmod "$mode" "$destination"; return; fi
        grep -Fq '# piux-managed:' "$destination" || {
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

# Parameters keep filesystem installation testable without changing HOME or a live server.
install_files() (
    local target_home=$1 source_dir=$2 config_dir main_conf include temporary old_config
    local legacy=false legacy_include archive
    config_dir="$target_home/.config/piux"
    main_conf="$target_home/.tmux.conf"
    [[ $target_home != *$'\n'* ]] || { printf '安装目录不能包含换行。\n' >&2; return 1; }
    mkdir -p -- "$target_home/.local/bin" "$config_dir"
    exec 9>"$config_dir/install.lock"
    flock 9
    # Follow an existing main-config symlink; keep the symlink itself intact.
    if [[ -L $main_conf ]]; then
        [[ -f $main_conf ]] || { printf '现有 .tmux.conf 链接无效。\n' >&2; return 1; }
        main_conf=$(readlink -f -- "$main_conf")
    fi
    if is_pimux_install "$target_home"; then legacy=true; fi
    install_asset "$source_dir/ui.bash" "$config_dir/ui.bash" 644
    install_asset "$source_dir/piux" "$target_home/.local/bin/piux" 755
    install_asset "$source_dir/piux.conf" "$config_dir/tmux.conf" 644
    install_asset "$source_dir/manager.bash" "$config_dir/manager.bash" 644
    # The socket is an existing server address, not a name to rewrite.
    if [[ $legacy == true && -f $target_home/.config/pimux/runtime.conf && \
          ! -e $config_dir/runtime.conf && ! -L $config_dir/runtime.conf ]]; then
        cp -p -- "$target_home/.config/pimux/runtime.conf" "$config_dir/runtime.conf"
    fi
    include="source-file $(quote_tmux "$config_dir/tmux.conf")"
    legacy_include="source-file $(quote_tmux "$target_home/.config/pimux/tmux.conf")"
    if [[ -f $main_conf ]] && grep -Fxq -- "$include" "$main_conf" && \
       ! grep -Fxq -- "$legacy_include" "$main_conf"; then
        printf '配置引用已存在，无需重复添加。\n'
    else
        temporary=$(mktemp "${main_conf}.new.XXXXXX")
        if [[ -f $main_conf ]]; then
            backup_file "$main_conf"
            copy_without_legacy_reference "$main_conf" "$temporary" \
                '# pimux: personal terminal theme and bindings' "$legacy_include"
        else
            chmod 644 "$temporary"
            # A new ~/.tmux.conf must retain the previously discovered XDG config.
            old_config="${XDG_CONFIG_HOME:-$target_home/.config}/tmux/tmux.conf"
            if [[ -f $old_config ]]; then
                printf 'source-file %s\n' "$(quote_tmux "$old_config")" >> "$temporary"
            fi
        fi
        printf '\n# piux: personal terminal theme and bindings\n%s\n' "$include" >> "$temporary"
        mv -- "$temporary" "$main_conf"
    fi
    if [[ $legacy == true ]]; then
        archive=$(mktemp "$target_home/.local/bin/pimux.piux-backup.XXXXXX")
        mv -- "$target_home/.local/bin/pimux" "$archive"
        printf '旧入口已归档：%s\n' "$archive"
    fi
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

install_shell_files() (
    local target_home=$1 source_dir=$2 config_dir rc include legacy_include temporary
    config_dir="$target_home/.config/piux"
    rc="$target_home/.bashrc"
    mkdir -p -- "$config_dir"
    exec 9>"$config_dir/install.lock"
    flock 9
    if [[ -L $rc ]]; then
        [[ -f $rc ]] || { printf '现有 .bashrc 链接无效。\n' >&2; return 1; }
        rc=$(readlink -f -- "$rc")
    fi
    install_asset "$source_dir/starship.toml" "$config_dir/starship.toml" 644
    install_asset "$source_dir/bashrc" "$config_dir/bashrc" 644
    printf -v include 'source %q' "$config_dir/bashrc"
    printf -v legacy_include 'source %q' "$target_home/.config/pimux/bashrc"
    if [[ -f $rc ]] && grep -Fxq -- "$include" "$rc" && \
       ! grep -Fxq -- "$legacy_include" "$rc"; then
        printf 'Bash 配置引用已存在，无需重复添加。\n'
        return
    fi
    temporary=$(mktemp "${rc}.new.XXXXXX")
    if [[ -f $rc ]]; then
        backup_file "$rc"
        copy_without_legacy_reference "$rc" "$temporary" \
            '# pimux: shared Bash prompt' "$legacy_include"
    else
        chmod 644 "$temporary"
    fi
    printf '\n# piux: shared Bash prompt\n%s\n' "$include" >> "$temporary"
    mv -- "$temporary" "$rc"
)

main() {
    local with_shell=false
    if [[ $# == 1 && $1 == --with-shell ]]; then
        with_shell=true
    elif [[ $# != 0 ]]; then
        printf '用法：bash setup-tmux.sh [--with-shell]\n安装并重载 tmux 配置；--with-shell 同时安装 Starship、提示符样式和 Bash 接入。\n'
        [[ $# == 1 && ( $1 == --help || $1 == -h ) ]]
        return
    fi
    local version
    for command in infocmp flock; do
        command -v "$command" >/dev/null || { printf '缺少系统命令：%s\n' "$command" >&2; return 1; }
    done
    if is_pimux_install "$HOME" && [[ ! -f $HOME/.config/piux/runtime.conf && \
          -f $HOME/.config/pimux/runtime.conf ]]; then
        PIUX_RUNTIME_FILE="$HOME/.config/pimux/runtime.conf" configure_runtime
    else
        configure_runtime
    fi
    require_tmux
    version=$(tmux -V)
    [[ $version =~ ([0-9]+)\.([0-9]+) ]] && \
        (( BASH_REMATCH[1] > 3 || (BASH_REMATCH[1] == 3 && BASH_REMATCH[2] >= 2) )) || {
            printf 'piux 配置要求 tmux >= 3.2；当前 %s。\n' "$version" >&2; return 1;
        }
    infocmp tmux-256color >/dev/null 2>&1 || {
        printf '缺少 tmux-256color terminfo，请安装 ncurses-term。\n' >&2; return 1;
    }
    install_files "$HOME" "$PIUX_SOURCE_DIR"
    if [[ $with_shell == true ]]; then
        install_starship
        install_shell_files "$HOME" "$PIUX_SOURCE_DIR"
        printf 'Starship 已配置；新建 Bash 窗口生效，已有 shell 可执行 source ~/.bashrc。\n'
    fi
    "$HOME/.local/bin/piux" reload
    printf '入口：%s/.local/bin/piux\n' "$HOME"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) printf '请在 shell 配置中加入：export PATH="$HOME/.local/bin:$PATH"\n' ;;
    esac
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
