# pimux-managed: interactive manager, sourced by the standalone Bash launcher.
# Run outside application panes; inside tmux this lives in a client-local popup.
session_pin_names() {
    local file=${PIMUX_PINS_FILE:-$HOME/.config/pimux/pinned-sessions} socket name
    [[ -f $file ]] || return 0
    while IFS=$'\t' read -r socket name; do
        [[ $socket != "$PIMUX_TARGET_SOCKET" ]] || printf '%s\n' "$name"
    done < "$file"
}

toggle_session_pin() (
    local target=$1 file=${PIMUX_PINS_FILE:-$HOME/.config/pimux/pinned-sessions}
    local name socket saved temporary found=false
    target=$(logical_session "$target")
    name=$(tmux display-message -p -t "$target:" '#{session_name}') || return
    [[ ! $name =~ [[:cntrl:]] ]] || return 1
    mkdir -p -- "$(dirname -- "$file")"
    exec 9>"${file}.lock"
    flock 9
    temporary=$(mktemp "${file}.new.XXXXXX")
    trap 'rm -f -- "$temporary"' EXIT
    if [[ -f $file ]]; then
        while IFS=$'\t' read -r socket saved; do
            if [[ $socket == "$PIMUX_TARGET_SOCKET" && $saved == "$name" ]]; then found=true
            else printf '%s\t%s\n' "$socket" "$saved" >> "$temporary"; fi
        done < "$file"
    fi
    [[ $found == true ]] || printf '%s\t%s\n' "$PIMUX_TARGET_SOCKET" "$name" >> "$temporary"
    mv -- "$temporary" "$file"
)

manager() (
    local client=${1:-} expand_current=${2:-} selected=0 offset=0 rows cols visible
    local sid wid label key answer name current='' error='' i count root resized=false
    local query='' searching=false candidate suggestion current_window='' preview_target
    local navigation=false button column width nav_index
    local -a roots=() windows=() labels=() pinned_ids=() other_ids=()
    local -a nav_keys=(e o g t '?') nav_labels=('环境' '代理' '显卡' '端口' '帮助') nav_starts=() nav_ends=()
    local -A expanded=() pinned=() names=()
    if [[ -n $client ]]; then
        current=$(logical_session "$(client_session "$client")")
        [[ $expand_current != windows ]] || expanded[$current]=1
    fi
    restore_manager() { printf '\033[?1000l\033[?1006l\033[0m\033[?7h\033[?25h\033[?1049l'; }
    manager_view() {
        current=${roots[selected]:-}; current_window=${windows[selected]:-}
        restore_manager
        load_gpu
        (python_view "$@") || true
        printf '\033[?1049h\033[?25l\033[?7l\033[?1000h\033[?1006h'
    }
    trap restore_manager EXIT
    trap 'exit 130' INT TERM HUP
    trap 'resized=true' WINCH
    printf '\033[?1049h\033[?25l\033[?7l\033[?1000h\033[?1006h'
    while :; do
        load_language
        pinned=(); names=(); pinned_ids=(); other_ids=()
        while IFS= read -r name; do [[ -z $name ]] || pinned[$name]=1; done < <(session_pin_names)
        while read -r sid; do
            name=$(tmux display-message -p -t "$sid:" '#{session_name}') || continue
            names[$sid]=$name
            if [[ ${pinned[$name]:-} == 1 ]]; then pinned_ids+=("$sid")
            else other_ids+=("$sid"); fi
        done < <(logical_sessions)
        roots=(); windows=(); labels=()
        for sid in "${pinned_ids[@]}" "${other_ids[@]}"; do
            name=${names[$sid]}
            label=$(tmux display-message -p -t "$sid:" "#{session_name}  (#{session_windows} $(tr_ui '窗口'))") || continue
            [[ ${pinned[$name]:-} != 1 ]] || label+=' *'
            if [[ -n $query ]]; then
                while IFS=$'\t' read -r wid label; do
                    candidate="$name / $label"
                    [[ ${candidate,,} == *"${query,,}"* ]] || continue
                    roots+=("$sid"); windows+=("$wid"); labels+=("$candidate")
                done < <(tmux list-windows -t "$sid" -F $'#{window_id}\t#{window_index}:#{window_name}  [#{pane_current_command}]  #{pane_current_path}')
                continue
            fi
            roots+=("$sid"); windows+=('')
            if [[ ${expanded[$sid]:-} == 1 ]]; then
                labels+=("v $label")
                while IFS=$'\t' read -r wid label; do
                    roots+=("$sid"); windows+=("$wid"); labels+=("    $label")
                done < <(tmux list-windows -t "$sid" -F $'#{window_id}\t#{window_index}:#{window_name}  [#{pane_current_command}]  #{pane_current_path}')
            else
                labels+=("> $label")
            fi
        done
        count=${#roots[@]}
        if [[ -n $current ]]; then
            for ((i=0; i<count; i++)); do
                if [[ ${roots[i]} == "$current" && ${windows[i]} == "$current_window" ]]; then selected=$i; break; fi
            done
            current=''; current_window=''
        fi
        (( selected < count )) || selected=$((count > 0 ? count - 1 : 0))
        read -r rows cols < <(stty size)
        visible=$((rows > 8 ? rows - 8 : 1))
        (( selected >= offset )) || offset=$selected
        (( selected < offset + visible )) || offset=$((selected - visible + 1))
        printf '\033[H\033[2J\033[38;2;183;161;232m PiMux · %s\033[0m\n' "$(tr_ui '会话管理')"
        printf_ui ' 搜索：%s  [%s/%s]\n\n' "$query" "$((count > 0 ? selected + 1 : 0))" "$count"
        printf '\033[3;1H '
        nav_starts=(); nav_ends=(); column=2
        for nav_index in "${!nav_keys[@]}"; do
            button=$(tr_ui "${nav_labels[nav_index]}")
            if [[ $PIMUX_LANGUAGE == zh ]]; then width=6
            else width=$((2 + ${#button})); fi
            (( column + width - 1 <= cols )) || break
            nav_starts+=("$column"); nav_ends+=("$((column + width - 1))")
            printf '\033[38;2;255;175;95m%s\033[38;2;99;197;248m %s\033[0m  ' "${nav_keys[nav_index]}" "$button"
            column=$((column + width + 2))
        done
        printf '\033[K\n'
        if (( count == 0 )); then
            if [[ -n $query ]]; then printf_ui ' 没有匹配的窗口，Esc 清除搜索。\n'
            else printf_ui ' 暂无会话。按 n 新建，或 q 返回后运行 pimux -n NAME。\n'
            fi
        else
            for ((i=offset; i<count && i<offset+visible; i++)); do
                (( i != selected )) || printf '\033[48;2;39;43;52m\033[38;2;99;197;248m'
                # Do not interpret terminal control sequences from names or paths.
                label=$(printf '%s' "${labels[i]}" | sed 's/[[:cntrl:]]/?/g')
                printf ' %s\033[K\033[0m\n' "$label"
            done
        fi
        if [[ $searching == true ]]; then
            if (( cols < 80 )); then label=$(tr_ui ' 输入筛选  Enter 进入  Esc 清除')
            else label=$(tr_ui ' 输入筛选  ↑↓ 选择  Enter 进入  Backspace 删除  Esc 清除'); fi
        else
            if (( cols < 80 )); then label=$(tr_ui ' / 搜索  Enter 进入  d 预览  q 返回')
            else label=$(tr_ui ' / 搜索  ↑↓ 选择  ←→ 展开  Enter 进入  d 预览  p 置顶  n 新建  x 关闭  q 返回'); fi
        fi
        printf '\033[%s;1H\033[38;2;255;175;95m%s\033[0m' "$((rows > 3 ? rows - 2 : 1))" "$label"
        if (( cols < 80 )); then label=$(tr_ui ' 点击进入  滚轮翻动')
        else label=$(tr_ui ' 点击进入  点箭头展开/收起  滚轮翻动'); fi
        printf '\n\033[38;2;156;163;175m%s\033[0m' "$label"
        [[ -z $error ]] || printf '\n %s' "$error"
        error=''
        key=''
        resized=false
        read_ui_key || { [[ $resized == true ]] && continue; return; }
        key=$PIMUX_KEY
        navigation=false
        [[ $key != ignored ]] || continue
        if [[ $key == mouse ]]; then
            if (( PIMUX_MOUSE_BUTTON == 0 && PIMUX_MOUSE_Y == 3 )); then
                for nav_index in "${!nav_starts[@]}"; do
                    if (( PIMUX_MOUSE_X >= nav_starts[nav_index] && PIMUX_MOUSE_X <= nav_ends[nav_index] )); then
                        key=${nav_keys[nav_index]}; navigation=true
                        break
                    fi
                done
                [[ $navigation == true ]] || continue
            else
                (( PIMUX_MOUSE_Y >= 4 && PIMUX_MOUSE_Y < 4 + visible )) || continue
                case $PIMUX_MOUSE_BUTTON in
                    64|65)
                        if (( PIMUX_MOUSE_BUTTON == 64 )); then offset=$((offset > 3 ? offset - 3 : 0))
                        else offset=$((offset + 3)); fi
                        i=$((count > visible ? count - visible : 0))
                        (( offset <= i )) || offset=$i
                        (( selected >= offset )) || selected=$offset
                        (( selected < offset + visible )) || selected=$((offset + visible - 1))
                        continue ;;
                    0)
                        i=$((offset + PIMUX_MOUSE_Y - 4))
                        (( i < count )) || continue
                        selected=$i
                        if [[ -z ${windows[i]} ]] && (( PIMUX_MOUSE_X <= 3 )); then
                            sid=${roots[i]}
                            if [[ ${expanded[$sid]:-} == 1 ]]; then expanded[$sid]=0
                            else expanded[$sid]=1; fi
                            continue
                        fi
                        key='' ;;
                    *) continue ;;
                esac
            fi
        fi
        if [[ $searching == true && $navigation != true ]]; then
            case $key in
                $'\177'|$'\b') query=${query%?}; selected=0; offset=0; continue ;;
                $'\e') query=''; searching=false; selected=0; offset=0; continue ;;
                ''|$'\e[A'|$'\eOA'|$'\e[B'|$'\eOB') ;;
                *)
                    [[ $key =~ [[:cntrl:]] ]] || query+=$key
                    selected=0; offset=0; continue ;;
            esac
        fi
        case $key in
            /) searching=true; selected=0; offset=0 ;;
            q|$'\e') return ;;
            e|o)
                local -a context=()
                if [[ -n $client ]]; then
                    sid=$(client_session "$client")
                    context=("${PIMUX_COMMAND[0]}" "$PIMUX_TARGET_SOCKET" "$(tmux display-message -p -t "$sid:" '#{pane_id}')")
                fi
                if [[ $key == e ]]; then manager_view environment_ui "${context[@]}"
                else manager_view proxy_ui "${context[@]}"; fi
                ;;
            g) manager_view gpu ;;
            t) manager_view ports ;;
            '?') manager_view utility_ui help "${PIMUX_COMMAND[0]}" "$PIMUX_TARGET_SOCKET" ;;
            $'\e[A'|$'\eOA'|k) (( selected == 0 )) || selected=$((selected - 1)) ;;
            $'\e[B'|$'\eOB'|j) (( selected + 1 >= count )) || selected=$((selected + 1)) ;;
            $'\e[C'|$'\eOC'|l) (( count == 0 )) || expanded[${roots[selected]}]=1 ;;
            $'\e[D'|$'\eOD'|h)
                if (( count > 0 )); then current=${roots[selected]}; expanded[$current]=0; fi
                ;;
            p)
                (( count > 0 )) || continue
                if toggle_session_pin "${roots[selected]}"; then
                    current=${roots[selected]}; current_window=${windows[selected]}
                else error=$(tr_ui '无法保存置顶设置。'); fi
                ;;
            d)
                (( count > 0 )) || continue
                current=${roots[selected]}; current_window=${windows[selected]}
                preview_target="$current:$current_window"
                if [[ -z $current_window && -n $client ]]; then
                    sid=$(client_session "$client")
                    [[ $(logical_session "$sid") != "$current" ]] || preview_target="$sid:"
                fi
                manager_view window_details "${PIMUX_COMMAND[0]}" "$PIMUX_TARGET_SOCKET" "$preview_target"
                ;;
            n)
                printf '\033[?1000l\033[?1006l\033[%s;1H\033[2K\033[?25h' "$rows"
                suggestion=$(printf '%s' "${PWD##*/}" | sed 's/[.:$#{}[:cntrl:]]/-/g; s/^-*//')
                name=''; IFS= read -er -i "${suggestion:-work}" \
                    -p "$(tr_ui ' 会话名称（Enter 确认，清空取消）：')" name || name=''
                printf '\033[?25l\033[?1000h\033[?1006h'
                [[ -n $name ]] || continue
                if root=$(ensure_session "$name" 2>&1); then
                    restore_manager; trap - EXIT
                    connect_session "$root" '' "$client"
                    return
                fi
                error=$root
                ;;
            '')
                (( count > 0 )) || continue
                restore_manager; trap - EXIT
                connect_session "${roots[selected]}" "${windows[selected]}" "$client"
                return
                ;;
            x)
                (( count > 0 )) || continue
                sid=${roots[selected]}; wid=${windows[selected]}
                printf '\033[%s;1H\033[2K' "$rows"
                if [[ -z $wid ]]; then
                    name=$(tmux display-message -p -t "$sid:" '#{session_name}')
                    printf_ui ' 关闭会话 %s 及其全部窗口，影响所有连接？[y/N] ' "$name"
                else
                    name=$(tmux display-message -p -t "$sid:$wid" '#{window_name}')
                    printf_ui ' 关闭窗口 %s，影响所有连接？[y/N] ' "$name"
                fi
                answer=''; read_ui_key && answer=$PIMUX_KEY
                [[ $answer == y ]] || continue
                if [[ -z $wid ]]; then
                    close_session "$sid" || error=$(tr_ui '会话已关闭或不存在。')
                else
                    tmux kill-window -t "$sid:$wid" || error=$(tr_ui '窗口已关闭或不存在。')
                fi
                ;;
        esac
    done
)
