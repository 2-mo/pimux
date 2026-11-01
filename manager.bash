# pimux-managed: interactive manager, sourced by the standalone Bash launcher.
# Run outside application panes; inside tmux this lives in a client-local popup.
manager() (
    local client=${1:-} expand_current=${2:-} selected=0 offset=0 rows cols visible
    local sid wid label key answer name current='' error='' i count root resized=false
    local query='' searching=false candidate
    local -a roots=() windows=() labels=()
    local -A expanded=()
    if [[ -n $client ]]; then
        current=$(logical_session "$(client_session "$client")")
        [[ $expand_current != windows ]] || expanded[$current]=1
    fi
    restore_manager() { printf '\033[?1000l\033[?1006l\033[0m\033[?7h\033[?25h\033[?1049l'; }
    trap restore_manager EXIT
    trap 'exit 130' INT TERM HUP
    trap 'resized=true' WINCH
    printf '\033[?1049h\033[?25l\033[?7l\033[?1000h\033[?1006h'
    while :; do
        load_language
        roots=(); windows=(); labels=()
        while read -r sid; do
            [[ -n $sid ]] || continue
            label=$(tmux display-message -p -t "$sid:" "#{session_name}  (#{session_windows} $(tr_ui '窗口'))") || continue
            if [[ -n $query ]]; then
                name=$(tmux display-message -p -t "$sid:" '#{session_name}')
                while IFS=$'\t' read -r wid label; do
                    candidate="$name / $label"
                    [[ ${candidate,,} == *"${query,,}"* ]] || continue
                    roots+=("$sid"); windows+=("$wid"); labels+=("$candidate")
                done < <(tmux list-windows -t "$sid" -F $'#{window_id}\t#{window_index}:#{window_name}  #{pane_current_path}')
                continue
            fi
            roots+=("$sid"); windows+=('')
            if [[ ${expanded[$sid]:-} == 1 ]]; then
                labels+=("v $label")
                while IFS=$'\t' read -r wid label; do
                    roots+=("$sid"); windows+=("$wid"); labels+=("    $label")
                done < <(tmux list-windows -t "$sid" -F $'#{window_id}\t#{window_index}:#{window_name}  #{pane_current_path}')
            else
                labels+=("> $label")
            fi
        done < <(logical_sessions)
        count=${#roots[@]}
        if [[ -n $current ]]; then
            for ((i=0; i<count; i++)); do
                if [[ ${roots[i]} == "$current" ]]; then selected=$i; break; fi
            done
            current=''
        fi
        (( selected < count )) || selected=$((count > 0 ? count - 1 : 0))
        read -r rows cols < <(stty size)
        visible=$((rows > 8 ? rows - 8 : 1))
        (( selected >= offset )) || offset=$selected
        (( selected < offset + visible )) || offset=$((selected - visible + 1))
        printf '\033[H\033[2J\033[38;2;183;161;232m pimux · %s\033[0m\n' "$(tr_ui '会话管理')"
        printf_ui ' 搜索：%s\n\n' "$query"
        if (( count == 0 )); then
            if [[ -n $query ]]; then printf_ui ' 没有匹配的窗口，Esc 清除搜索。\n'
            else printf_ui ' 暂无会话。按 n 新建，或 q 返回后运行 pimux -n NAME。\n'
            fi
        else
            for ((i=offset; i<count && i<offset+visible; i++)); do
                (( i != selected )) || printf '\033[48;2;39;43;52m\033[38;2;99;197;248m'
                # Do not interpret terminal control sequences from names or paths.
                label=$(printf '%s' "${labels[i]}" | sed 's/[[:cntrl:]]/?/g')
                printf ' %s\033[0m\n' "$label"
            done
        fi
        if [[ $searching == true ]]; then
            label=$(tr_ui ' 输入筛选  ↑↓ 选择  Enter 进入  Backspace 删除  Esc 清除')
        else
            label=$(tr_ui ' / 搜索  ↑↓ 选择  ←→ 展开  Enter 进入  n 新建  x 关闭  q 返回')
        fi
        printf '\033[%s;1H\033[38;2;255;175;95m%s\033[0m' "$((rows > 3 ? rows - 2 : 1))" "$label"
        printf '\n\033[38;2;156;163;175m%s\033[0m' "$(tr_ui ' 点击进入  点箭头展开/收起  滚轮翻动')"
        [[ -z $error ]] || printf '\n %s' "$error"
        error=''
        key=''
        resized=false
        read_ui_key || { [[ $resized == true ]] && continue; return; }
        key=$PIMUX_KEY
        [[ $key != ignored ]] || continue
        if [[ $key == mouse ]]; then
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
        if [[ $searching == true ]]; then
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
            $'\e[A'|$'\eOA'|k) (( selected == 0 )) || selected=$((selected - 1)) ;;
            $'\e[B'|$'\eOB'|j) (( selected + 1 >= count )) || selected=$((selected + 1)) ;;
            $'\e[C'|$'\eOC'|l) (( count == 0 )) || expanded[${roots[selected]}]=1 ;;
            $'\e[D'|$'\eOD'|h)
                if (( count > 0 )); then current=${roots[selected]}; expanded[$current]=0; fi
                ;;
            n)
                printf '\033[?1000l\033[?1006l\033[%s;1H\033[2K\033[?25h' "$rows"
                name=''; IFS= read -er -p "$(tr_ui ' 会话名称（空白取消）：')" name || true
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
