# pimux-managed: English / Simplified Chinese UI and language preference.
declare -A PIMUX_EN=(
    ['显卡界面的运行环境未就绪，请运行 pimux update 完成安装。']='The GPU dashboard environment is missing. Run pimux update to complete installation.'
    ['工作终端']='Work terminal'
    ['会话管理']='Session manager'
    ['窗口']=windows
    [' 搜索：%s  [%s/%s]\n\n']=' Search: %s  [%s/%s]\n\n'
    [' 没有匹配的窗口，Esc 清除搜索。\n']=' No matching windows. Esc clears the search.\n'
    [' / 搜索  ↑↓ 选择  ←→ 展开  Enter 进入  n 新建  x 关闭  q 返回']=' / search  Arrows select/expand  Enter open  n new  x close  q back'
    [' 输入筛选  ↑↓ 选择  Enter 进入  Backspace 删除  Esc 清除']=' Type to filter  Arrows select  Enter open  Backspace delete  Esc clear'
    [' / 搜索  Enter 进入  n 新建  q 返回']=' / search  Enter open  n new  q back'
    [' 输入筛选  Enter 进入  Esc 清除']=' Type to filter  Enter open  Esc clear'
    [' 点击进入  滚轮翻动']=' Click to open  Wheel to scroll'
    ['显卡详情']='GPU details'
    ['更新 PiMux']='Update PiMux'
    ['PiMux 更新失败。']='PiMux update failed.'
    ['按 Enter 返回。']='Press Enter to return.'
    [' 点击进入  点箭头展开/收起  滚轮翻动']=' Click to open  Click arrow to expand/collapse  Wheel to scroll'
    ['查看显卡详情；q / Esc 返回']='Show GPU details; q / Esc to return'
    ['未找到 nvidia-smi；显卡详情需要 NVIDIA 驱动。']='nvidia-smi was not found; GPU details require an NVIDIA driver.'
    ['显卡查询失败或超时；按 r 重试。']='GPU query failed or timed out; press r to retry.'
    ['每 5 秒刷新  滚轮 / ↑↓ / PgUp / PgDn 滚动  r 刷新  q / Esc 返回']='Every 5s  Wheel / Arrows / PgUp / PgDn scroll  r refresh  q / Esc back'
    ['新建窗口']='New window'
    ['重命名窗口']='Rename window'
    ['窗口名称：']='Window name:'
    ['完整目录路径']='Full directory path'
    ['复制当前目录路径']='Copy current directory path'
    ['路径已复制到 tmux，并发送到终端剪贴板。']='Path copied to tmux and sent to the terminal clipboard.'
    ['置顶当前会话']='Pin this session'
    ['取消置顶当前会话']='Unpin this session'
    ['无法保存置顶设置。']='Could not save pinned sessions.'
    ['网络代理']='Network proxy'
    ['启用']='Enabled'
    ['停用']='Disabled'
    ['继承启动环境']='Inherit startup environment'
    ['地址']='Address'
    ['当前终端传入的环境：']='Environment inherited from this terminal:'
    ['代理地址需以 http://、https://、socks5:// 或 socks5h:// 开头，且不能含空白。']='Use an http://, https://, socks5:// or socks5h:// proxy URL without whitespace.'
    ['请先设置代理地址。']='Set a proxy address first.'
    ['代理配置无效，请重新设置。']='Invalid proxy configuration; set it again.'
    ['已保存；新终端自动应用，已集成的 PiMux shell 在下次提示符应用。']='Saved. New terminals apply it automatically; integrated PiMux shells apply it at the next prompt.'
    ['仅影响 PiMux shell；运行中的程序保持原环境。']='Applies to PiMux shells; running programs keep their environment.'
    ['已有 shell 回到提示符后按 Enter 生效；升级前的旧 shell 请新开窗口。']='At an existing prompt, press Enter to apply. For shells from before this upgrade, open a new window.'
    ['e 设置地址  o 启用  d 停用  i 继承环境  q 返回']='e set address  o enable  d disable  i inherit  q back'
    ['代理地址（清空取消）：']='Proxy URL (clear to cancel):'
    ['当前 shell 配有代理时显示青色 ⛓︎，否则隐藏。']='A cyan ⛓︎ appears when this shell has a proxy configured; otherwise it stays hidden.'
    [' / 搜索  Enter 进入  p 置顶  q 返回']=' / search  Enter open  p pin  q back'
    [' / 搜索  ↑↓ 选择  ←→ 展开  Enter 进入  p 置顶  n 新建  x 关闭  q 返回']=' / search  Arrows select/expand  Enter open  p pin  n new  x close  q back'
    ['管理会话 / 窗口']='Manage sessions / windows'
    ['左右分屏']='Split left / right'
    ['上下分屏']='Split top / bottom'
    ['放大 / 恢复']='Zoom / restore'
    ['离开，保留任务']='Detach, keep tasks running'
    ['快捷键帮助']='Keyboard help'
    [' 会话名称（Enter 确认，清空取消）：']=' Session name (Enter accepts, clear to cancel):'
    [' ↑↓ 选择  ←→ 展开/收起  Enter 进入  n 新建  x 关闭  r 刷新  q 返回']=' Arrows select/expand  Enter open  n new  x close  r refresh  q back'
    [' 暂无会话。按 n 新建，或 q 返回后运行 pimux -n NAME。\n']=' No sessions. Press n to create one, or q and run pimux -n NAME.\n'
    [' 关闭会话 %s 及其全部窗口，影响所有连接？[y/N] ']=' Close session %s and ALL its windows for every connection? [y/N] '
    [' 关闭窗口 %s，影响所有连接？[y/N] ']=' Close window %s for every connection? [y/N] '
    ['会话已关闭或不存在。']='Session is already closed or no longer exists.'
    ['窗口已关闭或不存在。']='Window is already closed or no longer exists.'
    ['运行配置应为三行：新版程序路径、socket 名称、系统程序路径：%s\n']='Runtime config must have three lines: new binary, socket name, system binary: %s\n'
    ['运行配置中的程序路径或 socket 名称无效：%s\n']='Invalid binary path or socket name in runtime config: %s\n'
    ['请先安装 tmux（Ubuntu：sudo apt install tmux）。\n']='Install tmux first (Ubuntu: sudo apt install tmux).\n'
    ['请在交互终端中运行；只读查看请用 pimux ls。\n']='Run this in an interactive terminal; use pimux ls for a read-only listing.\n'
    ['当前位于另一个 tmux server。请先按 Ctrl-a d 离开，再运行此命令；旧会话用 pimux --system。\n']='You are in another tmux server. Detach with Ctrl-a d first; use pimux --system for old sessions.\n'
    ['已重载配置；会话和任务继续运行。前缀为 Ctrl-a。\n']='Configuration reloaded; sessions and tasks keep running. Prefix: Ctrl-a.\n'
    ['配置会在此 tmux server 下次启动时加载。\n']='Configuration will load when this tmux server starts.\n'
    ['会话名不能为空，也不能以 - 开头或包含 . : $ { } # 或控制字符。\n']='A session name must not be empty, start with -, or contain . : $ { } # or control characters.\n'
    ['当前窗口有多个连接，请用 Ctrl-a h → 管理，明确操作当前终端。\n']='The current window has multiple connections. Use Ctrl-a h > Manage to address this terminal.\n'
    ['暂无会话。运行 pimux -n NAME 创建，或在 pimux 管理列表中按 n。\n']='No sessions. Run pimux -n NAME or press n in the pimux manager.\n'
    ['没有匹配的窗口。\n']='No matching windows.\n'
    ['tmux：%s\n']='tmux: %s\n'
    ['程序：%s\nsocket：%s\n']='Binary: %s\nSocket: %s\n'
    ['版本：满足 pimux 配置要求（>= 3.2）\n']='Version: meets the pimux requirement (>= 3.2).\n'
    ['版本：配置要求 tmux >= 3.2\n']='Version: pimux requires tmux >= 3.2.\n'
    ['terminfo：tmux-256color 可用\n']='terminfo: tmux-256color is available.\n'
    ['terminfo：缺少 tmux-256color，请安装 ncurses-term\n']='terminfo: tmux-256color is missing; install ncurses-term.\n'
    ['当前 TERM：%s（tmux 内的 TERM 不代表外层 VS Code）\n']='Current TERM: %s (the inner TERM does not identify the outer VS Code terminal).\n'
    ['未设置']=unset
    ['尚未加载 pimux']='pimux has not been loaded'
    ['运行中的 server：#{version}（PID #{pid}）']='Running server: #{version} (PID #{pid})'
    ['运行配置：%s\n']='Active configuration: %s\n'
    ['客户端：#{client_name}  TERM=#{client_termname}  能力=#{client_termfeatures}']='Client: #{client_name}  TERM=#{client_termname}  Features=#{client_termfeatures}'
    ['运行配置：尚未启动 tmux，会在新会话启动时读取。\n']='Active configuration: no server yet; it will load on startup.\n'
    ['本地剪贴板需实际验证；配置能力不等于复制成功。\n']='Test the local clipboard by pasting; advertised support does not guarantee success.\n'
    ['已发送测试文字，请在本地编辑器粘贴并检查：pimux clipboard test\n']='Test text sent. Paste into your local editor and check: pimux clipboard test\n'
    ['未知命令：%s；会话请用 pimux -n NAME，帮助请用 pimux -h。\n']='Unknown command: %s. Use pimux -n NAME for a session or pimux -h for help.\n'
    ['先按 Ctrl-a 并松开，再按下列操作键；数字键直接切窗口。']='Press Ctrl-a, release it, then press an action key below. Number keys select windows.'
    ['向应用发送 Ctrl-a（shell 中回到行首）']='Send Ctrl-a to the application (start of line in a shell)'
    ['新建 shell 窗口，继承当前目录']='New shell window in the current directory'
    ['重命名当前窗口']='Rename the current window'
    ['查看完整目录路径；q / Esc 返回']='Show the full directory path; q / Esc to return'
    ['展开当前会话的窗口列表']='Open the window list for the current session'
    ['管理会话和窗口；n 新建，x 关闭（需确认），q 返回']='Manage sessions and windows; n new, x close (confirm), q back'
    ['左右分屏，继承当前目录']='Split left / right in the current directory'
    ['上下分屏，继承当前目录']='Split top / bottom in the current directory'
    ['切换到左侧分屏']='Select the pane to the left'
    ['切换到右侧分屏']='Select the pane to the right'
    ['切换到上方分屏']='Select the pane above'
    ['切换到下方分屏']='Select the pane below'
    ['上一个窗口']='Previous window'
    ['下一个窗口']='Next window'
    ['返回上次使用的窗口']='Last used window'
    ['返回上次使用的会话，保持独立窗口选择']='Last used session, with independent window selection'
    ['放大当前分屏 / 恢复分屏']='Zoom / restore the current pane'
    ['进入历史复制模式；v 选择，y 复制，/ 搜索']='Enter copy mode; v select, y copy, / search'
    ['粘贴 tmux 缓冲区；本地剪贴板用 VS Code 粘贴键']='Paste the tmux buffer; use VS Code paste for the local clipboard'
    ['离开当前客户端，保留会话和任务']='Detach this client, keeping sessions and tasks running'
    ['重载配置']='Reload configuration'
    ['查看此帮助；先按 Ctrl-a 并松开，再按操作键；数字键直接切窗口']='Show keyboard help; press and release Ctrl-a before an action key'
    ['打开操作菜单']='Open the menu'
    ['pimux 配置已重载']='pimux configuration reloaded'
)
load_language() {
    PIMUX_LANGUAGE=en
    local value=''
    if [[ -f ${PIMUX_LANGUAGE_FILE:-$HOME/.config/pimux/language} ]]; then
        IFS= read -r value < "${PIMUX_LANGUAGE_FILE:-$HOME/.config/pimux/language}" || true
        case $value in en|zh) PIMUX_LANGUAGE=$value ;; esac
    fi
}

tr_ui() {
    if [[ $PIMUX_LANGUAGE == en ]]; then
        printf '%s' "${PIMUX_EN[$1]:-$1}"
    else
        printf '%s' "$1"
    fi
}

printf_ui() {
    local format
    format=$(tr_ui "$1")
    shift
    printf "$format" "$@"
}

# Keep a printable key typed immediately after Esc for the next interaction.
read_ui_key() {
    local suffix='' tail='' report=''
    local -a options=(-rsn1)
    PIMUX_KEY=''
    if [[ -n ${PIMUX_PENDING_KEY:-} ]]; then
        PIMUX_KEY=$PIMUX_PENDING_KEY; PIMUX_PENDING_KEY=''
    else
        [[ $# == 0 ]] || options+=(-t "$1")
        IFS= read "${options[@]}" PIMUX_KEY || return
    fi
    if [[ $PIMUX_KEY == $'\e' ]]; then
        IFS= read -rsn1 -t 0.05 suffix || true
        if [[ $suffix == '[' || $suffix == O ]]; then
            IFS= read -rsn1 -t 0.05 tail || true
            PIMUX_KEY+="$suffix$tail"
            if [[ $PIMUX_KEY == $'\e[<' ]]; then
                # SGR mouse reports contain decimal button, column and row.
                PIMUX_KEY=ignored
                while (( ${#report} < 32 )); do
                    IFS= read -rsn1 -t 0.05 tail || return 0
                    report+=$tail
                    [[ $tail != M && $tail != m ]] || break
                done
                if [[ $report =~ ^([0-9]{1,6})\;([0-9]{1,6})\;([0-9]{1,6})M$ ]]; then
                    PIMUX_MOUSE_BUTTON=$((10#${BASH_REMATCH[1]}))
                    PIMUX_MOUSE_X=$((10#${BASH_REMATCH[2]}))
                    PIMUX_MOUSE_Y=$((10#${BASH_REMATCH[3]}))
                    PIMUX_KEY=mouse
                fi
                return 0
            fi
            if [[ $PIMUX_KEY == $'\e[5' || $PIMUX_KEY == $'\e[6' ]]; then
                tail=''; IFS= read -rsn1 -t 0.05 tail || true; PIMUX_KEY+=$tail
            fi
        else
            PIMUX_PENDING_KEY=$suffix
        fi
    fi
}

# Refresh only sessions marked as pimux, preserving other users of a shared server.
refresh_language() (
    local sid launcher
    update_server_language() {
        while IFS=$'\t' read -r sid launcher; do
            [[ -n $sid && -n $launcher ]] || continue
            tmux set-option -t "$sid" @pimux_language "$PIMUX_LANGUAGE"
        done < <(tmux list-sessions -F $'#{session_id}\t#{@pimux_launcher}' 2>/dev/null || true)
    }
    update_server_language
    if [[ -f ${PIMUX_RUNTIME_FILE:-$HOME/.config/pimux/runtime.conf} ]]; then
        configure_runtime; update_server_language
        configure_runtime true; update_server_language
    fi
)

save_language() (
    local value=$1 file=${PIMUX_LANGUAGE_FILE:-$HOME/.config/pimux/language} temporary
    case $value in en|zh) ;; *) return 2 ;; esac
    mkdir -p -- "$(dirname -- "$file")"
    exec 9>"${file}.lock"
    flock 9
    temporary=$(mktemp "${file}.new.XXXXXX")
    printf '%s\n' "$value" > "$temporary"
    mv -- "$temporary" "$file"
    PIMUX_LANGUAGE=$value
    refresh_language
)

menu_action() {
    local client=$1 action=$2 background=${3:-true} socket command
    socket=$(tmux display-message -p '#{socket_path}')
    command="$(shell_quote "$PIMUX_LAUNCHER") __client $(shell_quote "$socket") $(shell_quote "$client") $(shell_quote "$action")"
    if [[ $background == true ]]; then printf 'run-shell -b '; else printf 'run-shell '; fi
    shell_quote "$command"
}

show_menu() {
    local client=$1 target rename pin_label='置顶当前会话' name
    target=$(client_session "$client")
    load_manager
    name=$(tmux display-message -p -t "$(logical_session "$target"):" '#{session_name}')
    if session_pin_names | grep -Fxq -- "$name"; then pin_label='取消置顶当前会话'; fi
    rename="command-prompt -p $(shell_quote "$(tr_ui '窗口名称：')") -I #{q:window_name} \"rename-window -- '%%'\""
    tmux display-menu -c "$client" -t "$target:" -T "#[fg=#b7a1e8]pimux · $(tr_ui '工作终端')" -x C -y C \
        "$(tr_ui '新建窗口')" c 'new-window -n shell -c #{q:pane_current_path}' \
        "$(tr_ui '重命名窗口')" , "$rename" \
        "$(tr_ui '完整目录路径')" P "$(menu_action "$client" path false)" \
        "$(tr_ui '复制当前目录路径')" y "$(menu_action "$client" copy-path)" \
        "$(tr_ui '管理会话 / 窗口')" s "$(menu_action "$client" manager)" \
        "$(tr_ui "$pin_label")" p "$(menu_action "$client" pin)" \
        "$(tr_ui '显卡详情')" g "$(menu_action "$client" gpu)" \
        '' \
        "$(tr_ui '左右分屏')" '|' 'split-window -h -c #{q:pane_current_path}' \
        "$(tr_ui '上下分屏')" '-' 'split-window -v -c #{q:pane_current_path}' \
        "$(tr_ui '放大 / 恢复')" z 'resize-pane -Z' \
        '' \
        'Language / 语言' l "$(menu_action "$client" language)" \
        "$(tr_ui '离开，保留任务')" d 'detach-client' \
        "$(tr_ui '快捷键帮助')" / "$(menu_action "$client" help false)" \
        "$(tr_ui '更新 PiMux')" u "$(menu_action "$client" update)" \
        "$(tr_ui '网络代理')" o "$(menu_action "$client" proxy)"
}

show_language_menu() {
    local client=$1 zh='简体中文' en='English'
    if [[ $PIMUX_LANGUAGE == zh ]]; then zh="* $zh"; else en="* $en"; fi
    tmux display-menu -c "$client" -T 'Language / 语言' -x C -y C \
        "$en" e "$(menu_action "$client" lang-en)" \
        "$zh" z "$(menu_action "$client" lang-zh)"
}

shortcut_help() {
    local line prefix description
    printf '%s\n\n' "$(tr_ui '先按 Ctrl-a 并松开，再按下列操作键；数字键直接切窗口。')"
    while IFS= read -r line; do
        [[ $line == *'pimux: '* ]] || continue
        prefix=${line%%pimux:*}; description=${line#*pimux: }
        printf '%s%s\n' "$prefix" "$(tr_ui "$description")"
    done < <(tmux list-keys -N -T prefix)
}

load_language
