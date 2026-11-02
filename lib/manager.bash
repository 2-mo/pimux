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
    local sid wid key answer name current='' error='' i count root resized=false
    local query='' searching=false suggestion current_window='' preview_target window_count
    local navigation=false button column width nav_index
    local -a roots=() windows=() titles=() programs=() paths=() counts=() pinned_ids=() other_ids=()
    local -a nav_keys=(e o g t i '?') nav_labels=('环境' '代理' '显卡' '端口' 'IP' '帮助') nav_starts=() nav_ends=()
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
    manager_windows() {
        local target=$1 wid title program path candidate
        while IFS=$'\t' read -r wid title program path; do
            candidate="${names[$target]} / $title  $program  $path"
            [[ -z $query || ${candidate,,} == *"${query,,}"* ]] || continue
            roots+=("$target"); windows+=("$wid"); titles+=("$title")
            programs+=("$program"); paths+=("$path"); counts+=('')
        done < <(tmux list-windows -t "$target" -F $'#{window_id}\t#{window_index}:#{window_name}\t[#{pane_current_command}]\t#{pane_current_path}')
    }
    manager_render() {
        local index finish search_mode chosen pin expand row_sid row_name
        nav_starts=(); nav_ends=(); column=2
        for nav_index in "${!nav_keys[@]}"; do
            button=$(tr_ui "${nav_labels[nav_index]}")
            if [[ $PIMUX_LANGUAGE == zh && $button != IP ]]; then width=6
            else width=$((2 + ${#button})); fi
            (( column + width - 1 <= cols )) || break
            nav_starts+=("$column"); nav_ends+=("$((column + width - 1))")
            column=$((column + width + 1))
        done
        finish=$((offset + visible))
        (( finish <= count )) || finish=$count
        search_mode=0; [[ $searching != true ]] || search_mode=1
        {
            printf '%s\0' "$cols" "$rows" "$selected" "$count" "$search_mode" "$query" "$error" "${#nav_starts[@]}"
            for index in "${!nav_starts[@]}"; do
                printf '%s\0' "${nav_keys[index]}" "$(tr_ui "${nav_labels[index]}")"
            done
            printf '%s\0' "$((finish - offset))"
            for ((index=offset; index<finish; index++)); do
                row_sid=${roots[index]}; row_name=${names[$row_sid]}
                chosen=0; pin=0; expand=0
                (( index != selected )) || chosen=1
                [[ ${pinned[$row_name]:-} != 1 ]] || pin=1
                [[ ${expanded[$row_sid]:-} != 1 ]] || expand=1
                printf '%s\0' "$row_name" "${titles[index]}" "${programs[index]}" \
                    "${paths[index]}" "${counts[index]}" "$expand" "$pin" "$chosen"
            done
        } | (python_view manager_ui)
    }
    load_gpu
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
        roots=(); windows=(); titles=(); programs=(); paths=(); counts=()
        for sid in "${pinned_ids[@]}" "${other_ids[@]}"; do
            if [[ -n $query ]]; then
                manager_windows "$sid"
                continue
            fi
            window_count=$(tmux display-message -p -t "$sid:" '#{session_windows}') || continue
            roots+=("$sid"); windows+=(''); titles+=(''); programs+=(''); paths+=(''); counts+=("$window_count")
            [[ ${expanded[$sid]:-} != 1 ]] || manager_windows "$sid"
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
        manager_render
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
            e|o|i)
                local -a context=()
                if [[ -n $client ]]; then
                    sid=$(client_session "$client")
                    context=("${PIMUX_COMMAND[0]}" "$PIMUX_TARGET_SOCKET" "$(tmux display-message -p -t "$sid:" '#{pane_id}')")
                fi
                if [[ $key == i ]]; then manager_view network "${context[@]}"
                elif [[ $key == e ]]; then manager_view environment_ui "${context[@]}"
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
                    -p $'\001\033[38;2;99;197;248m\002'"$(tr_ui ' 会话名称（Enter 确认，清空取消）：')"$'\001\033[0m\002' name || name=''
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
                printf '\033[%s;1H\033[2K\033[38;2;255;175;95m' "$rows"
                if [[ -z $wid ]]; then
                    name=$(tmux display-message -p -t "$sid:" '#{session_name}')
                    printf_ui ' 关闭会话 %s 及其全部窗口，影响所有连接？[y/N] ' "$name"
                else
                    name=$(tmux display-message -p -t "$sid:$wid" '#{window_name}')
                    printf_ui ' 关闭窗口 %s，影响所有连接？[y/N] ' "$name"
                fi
                printf '\033[0m'
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
