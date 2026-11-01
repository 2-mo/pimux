# piux-managed: interactive manager, sourced by the standalone Bash launcher.
# Run outside application panes; inside tmux this lives in a client-local popup.
manager() (
    local client=${1:-} expand_current=${2:-} selected=0 offset=0 rows cols visible
    local sid wid label key suffix answer name current='' error='' i count root resized=false
    local -a roots=() windows=() labels=()
    local -A expanded=()
    if [[ -n $client ]]; then
        current=$(logical_session "$(client_session "$client")")
        [[ $expand_current != windows ]] || expanded[$current]=1
    fi
    restore_manager() { printf '\033[0m\033[?7h\033[?25h\033[?1049l'; }
    trap restore_manager EXIT
    trap 'exit 130' INT TERM HUP
    trap 'resized=true' WINCH
    printf '\033[?1049h\033[?25l\033[?7l'
    while :; do
        load_language
        roots=(); windows=(); labels=()
        while read -r sid; do
            [[ -n $sid ]] || continue
            label=$(tmux display-message -p -t "$sid:" "#{session_name}  (#{session_windows} $(tr_ui '窗口'))") || continue
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
        visible=$((rows > 7 ? rows - 7 : 1))
        (( selected >= offset )) || offset=$selected
        (( selected < offset + visible )) || offset=$((selected - visible + 1))
        printf '\033[H\033[2J\033[38;2;183;161;232m piux · %s\033[0m\n\n' "$(tr_ui '会话管理')"
        if (( count == 0 )); then
            printf_ui ' 暂无会话。按 n 新建，或 q 返回后运行 piux -n NAME。\n'
        else
            for ((i=offset; i<count && i<offset+visible; i++)); do
                (( i != selected )) || printf '\033[48;2;39;43;52m\033[38;2;99;197;248m'
                # Do not interpret terminal control sequences from names or paths.
                label=$(printf '%s' "${labels[i]}" | sed 's/[[:cntrl:]]/?/g')
                printf ' %s\033[0m\n' "$label"
            done
        fi
        printf '\033[%s;1H\033[38;2;255;175;95m%s\033[0m' "$((rows > 3 ? rows - 2 : 1))" "$(tr_ui ' ↑↓ 选择  ←→ 展开/收起  Enter 进入  n 新建  x 关闭  r 刷新  q 返回')"
        [[ -z $error ]] || printf '\n %s' "$error"
        error=''
        key=''
        resized=false
        IFS= read -rsn1 key || { [[ $resized == true ]] && continue; return; }
        if [[ $key == $'\e' ]]; then
            suffix=''; IFS= read -rsn2 -t 0.1 suffix || true
            key+=$suffix
        fi
        case $key in
            q|$'\e') return ;;
            $'\e[A'|$'\eOA'|k) (( selected == 0 )) || selected=$((selected - 1)) ;;
            $'\e[B'|$'\eOB'|j) (( selected + 1 >= count )) || selected=$((selected + 1)) ;;
            $'\e[C'|$'\eOC'|l) (( count == 0 )) || expanded[${roots[selected]}]=1 ;;
            $'\e[D'|$'\eOD'|h)
                if (( count > 0 )); then current=${roots[selected]}; expanded[$current]=0; fi
                ;;
            n)
                printf '\033[%s;1H\033[2K\033[?25h' "$rows"
                name=''; IFS= read -er -p "$(tr_ui ' 会话名称（空白取消）：')" name || true
                printf '\033[?25l'
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
                answer=''; IFS= read -rsn1 answer || true
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
