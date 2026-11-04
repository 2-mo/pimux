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
    pimux_lock 9
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
    local query='' query_cursor=0 searching=false suggestion current_window='' current_pane='' preview_target window_count pane
    local navigation=false nav_index nav_position=0 nav_id=manager nav_focus=false nav_offset=0 sidebar_width=0 local_x
    local nav_identity nav_parent nav_key
    local -a roots=() windows=() titles=() programs=() paths=() counts=() panes=() pane_indices=() pinned_ids=() other_ids=()
    local -a nav_ids=() nav_parents=() nav_keys=() nav_visible=()
    local -A nav_expanded=([workspace]=1 [resources]=1 [network]=1 [settings]=1)
    local -A expanded=() pinned=() names=()
    if [[ -n $client ]]; then
        current=$(logical_session "$(client_session "$client")")
        [[ $expand_current != windows ]] || expanded[$current]=1
    fi
    local terminal_mode
    terminal_mode=$(stty -g)
    restore_manager() {
        stty "$terminal_mode"
        printf '\033[?1000l\033[?1006l\033[0m\033[?7h\033[?25h\033[?1049l'
    }
    enter_manager() {
        stty -icanon -echo min 1 time 0
        printf '\033[?1049h\033[?25l\033[?7l\033[?1000h\033[?1006h'
    }
    manager_view() {
        current=${roots[selected]:-}; current_window=${windows[selected]:-}; current_pane=${panes[selected]:-}
        restore_manager
        load_gpu
        if [[ $1 == __update ]]; then ("$PIMUX_LAUNCHER" "$@") || true
        else (python_view "$@") || true; fi
        enter_manager
    }
    manager_windows() {
        local target=$1 wid title program path
        # Sanitize C0/DEL before emitting records; ':' in POSIX classes is a tmux modifier separator.
        while IFS=$'\t' read -r wid title program path; do
            roots+=("$target"); windows+=("$wid"); titles+=("$title")
            programs+=("$program"); paths+=("$path"); counts+=(''); panes+=(''); pane_indices+=('')
        done < <(tmux list-windows -t "$target" -F $'#{window_id}\t#{window_index}:#{s/[\001-\037\177]/ /:window_name}\t[#{s/[\001-\037\177]/ /:pane_current_command}]\t#{s/[\001-\037\177]/ /:pane_current_path}')
    }
    manager_panes() {
        local target=$1 wid title pane index program path candidate
        while IFS=$'\t' read -r wid title pane index program path; do
            candidate="${names[$target]} / $title / $index  $program  $path"
            [[ -z $query || ${candidate,,} == *"${query,,}"* ]] || continue
            roots+=("$target"); windows+=("$wid"); titles+=("$title")
            panes+=("$pane"); pane_indices+=("$index")
            programs+=("$program"); paths+=("$path"); counts+=('')
        done < <(tmux list-panes -s -t "$target" -F $'#{window_id}\t#{window_index}:#{s/[\001-\037\177]/ /:window_name}\t#{pane_id}\t#{pane_index}\t[#{s/[\001-\037\177]/ /:pane_current_command}]\t#{s/[\001-\037\177]/ /:pane_current_path}')
    }
    manager_navigation() {
        nav_visible=()
        for nav_index in "${!nav_ids[@]}"; do
            nav_parent=${nav_parents[nav_index]}
            if [[ -z $nav_parent || ${nav_expanded[$nav_parent]:-0} == 1 ]]; then
                [[ ${nav_ids[nav_index]} != "$nav_id" ]] || nav_position=${#nav_visible[@]}
                nav_visible+=("$nav_index")
            fi
        done
        (( nav_position < ${#nav_visible[@]} )) || nav_position=0
        nav_id=${nav_ids[${nav_visible[nav_position]}]}
        (( nav_position >= nav_offset )) || nav_offset=$nav_position
        (( nav_position < nav_offset + visible )) || nav_offset=$((nav_position - visible + 1))
        i=$((${#nav_visible[@]} > visible ? ${#nav_visible[@]} - visible : 0))
        (( nav_offset <= i )) || nav_offset=$i
    }
    manager_render() {
        local index finish search_mode chosen pin expand row_sid row_name focus_mode
        finish=$((offset + visible))
        (( finish <= count )) || finish=$count
        search_mode=0; [[ $searching != true ]] || search_mode=1
        focus_mode=0; [[ $nav_focus != true ]] || focus_mode=1
        {
            printf '%s\0' "$cols" "$rows" "$selected" "$count" "$search_mode" "$query" "$error" "$query_cursor" \
                "$sidebar_width" "$focus_mode" "$nav_id" "$nav_offset" "${#nav_visible[@]}"
            for index in "${nav_visible[@]}"; do
                printf '%s\0' "${nav_ids[index]}" "${nav_expanded[${nav_ids[index]}]:-0}"
            done
            printf '%s\0' "$((finish - offset))"
            for ((index=offset; index<finish; index++)); do
                row_sid=${roots[index]}; row_name=${names[$row_sid]}
                chosen=0; pin=0; expand=0
                (( index != selected )) || chosen=1
                [[ ${pinned[$row_name]:-} != 1 ]] || pin=1
                [[ ${expanded[$row_sid]:-} != 1 ]] || expand=1
                printf '%s\0' "$row_name" "${titles[index]}" "${programs[index]}" \
                    "${paths[index]}" "${counts[index]}" "${panes[index]}" "${pane_indices[index]}" "$expand" "$pin" "$chosen"
            done
        } | (python_view manager_ui)
    }
    load_gpu
    while IFS= read -r -d '' nav_identity && IFS= read -r -d '' nav_parent && IFS= read -r -d '' nav_key; do
        nav_ids+=("$nav_identity"); nav_parents+=("$nav_parent"); nav_keys+=("$nav_key")
    done < <(python_view navigation --dump home)
    trap restore_manager EXIT
    trap 'exit 130' INT TERM HUP
    trap 'resized=true' WINCH
    enter_manager
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
        roots=(); windows=(); titles=(); programs=(); paths=(); counts=(); panes=(); pane_indices=()
        for sid in "${pinned_ids[@]}" "${other_ids[@]}"; do
            if [[ $searching == true || -n $query ]]; then
                manager_panes "$sid"
                continue
            fi
            window_count=$(tmux display-message -p -t "$sid:" '#{session_windows}') || continue
            roots+=("$sid"); windows+=(''); titles+=(''); programs+=(''); paths+=(''); counts+=("$window_count"); panes+=(''); pane_indices+=('')
            [[ ${expanded[$sid]:-} != 1 ]] || manager_windows "$sid"
        done
        count=${#roots[@]}
        if [[ -n $current ]]; then
            for ((i=0; i<count; i++)); do
                if [[ ${roots[i]} == "$current" && ${windows[i]} == "$current_window" && ${panes[i]} == "$current_pane" ]]; then selected=$i; break; fi
            done
            current=''; current_window=''; current_pane=''
        fi
        (( selected < count )) || selected=$((count > 0 ? count - 1 : 0))
        read -r rows cols < <(stty size)
        visible=$((rows > 8 ? rows - 8 : 1))
        sidebar_width=0; (( cols < 80 )) || sidebar_width=24
        manager_navigation
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
        if [[ $key == $'\t' ]]; then
            if [[ $nav_focus == true ]]; then nav_focus=false; else nav_focus=true; fi
            searching=false
            continue
        fi
        if [[ $key == mouse ]]; then
            if (( PIMUX_MOUSE_BUTTON == 0 && PIMUX_MOUSE_Y == 3 )); then
                if (( sidebar_width )); then
                    if (( PIMUX_MOUSE_X <= sidebar_width )); then nav_focus=true; else nav_focus=false; fi
                elif [[ $nav_focus == true ]]; then nav_focus=false
                else nav_focus=true; fi
                searching=false
                continue
            fi
            (( PIMUX_MOUSE_Y >= 4 && PIMUX_MOUSE_Y < 4 + visible )) || continue
            if (( sidebar_width > 0 && PIMUX_MOUSE_X <= sidebar_width )) ||
               [[ $sidebar_width == 0 && $nav_focus == true ]]; then
                nav_focus=true; searching=false
                case $PIMUX_MOUSE_BUTTON in
                    64|65)
                        if (( PIMUX_MOUSE_BUTTON == 64 )); then nav_position=$((nav_position > 3 ? nav_position - 3 : 0))
                        else nav_position=$((nav_position + 3)); fi
                        (( nav_position < ${#nav_visible[@]} )) || nav_position=$((${#nav_visible[@]} - 1))
                        nav_id=${nav_ids[${nav_visible[nav_position]}]}
                        continue ;;
                    0)
                        nav_position=$((nav_offset + PIMUX_MOUSE_Y - 4))
                        (( nav_position < ${#nav_visible[@]} )) || continue
                        nav_id=${nav_ids[${nav_visible[nav_position]}]}
                        key=''; navigation=true ;;
                    *) continue ;;
                esac
            else
                nav_focus=false
                local_x=$PIMUX_MOUSE_X
                (( sidebar_width == 0 )) || local_x=$((local_x - sidebar_width - 2))
                (( local_x > 0 )) || continue
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
                        if [[ -z ${windows[i]} ]] && (( local_x <= 3 )); then
                            sid=${roots[i]}
                            if [[ ${expanded[$sid]:-} == 1 ]]; then expanded[$sid]=0
                            else expanded[$sid]=1; fi
                            continue
                        fi
                        key=''; navigation=true ;;
                    *) continue ;;
                esac
            fi
        fi
        if [[ $nav_focus == true ]]; then
            nav_index=${nav_visible[nav_position]}
            case $key in
                $'\e[A'|$'\eOA'|k) (( nav_position == 0 )) || nav_position=$((nav_position - 1)) ;;
                $'\e[B'|$'\eOB'|j) (( nav_position + 1 >= ${#nav_visible[@]} )) || nav_position=$((nav_position + 1)) ;;
                $'\e[D'|$'\eOD'|h)
                    if [[ -n ${nav_parents[nav_index]} ]]; then nav_id=${nav_parents[nav_index]}
                    else nav_expanded[$nav_id]=0; fi
                    continue ;;
                $'\e[C'|$'\eOC'|l)
                    [[ -n ${nav_parents[nav_index]} ]] || nav_expanded[$nav_id]=1
                    continue ;;
                '')
                    if [[ -z ${nav_parents[nav_index]} ]]; then
                        nav_expanded[$nav_id]=$((1 - ${nav_expanded[$nav_id]:-0}))
                        continue
                    fi
                    key=${nav_keys[nav_index]}; navigation=true ;;
            esac
            case $key in
                $'\e[A'|$'\eOA'|k|$'\e[B'|$'\eOB'|j)
                    nav_id=${nav_ids[${nav_visible[nav_position]}]}; continue ;;
            esac
        fi
        if [[ $searching == true && $navigation != true ]]; then
            case $key in
                $'\e[D'|$'\eOD'|$'\002') (( query_cursor == 0 )) || query_cursor=$((query_cursor - 1)); continue ;;
                $'\e[C'|$'\eOC'|$'\006') (( query_cursor == ${#query} )) || query_cursor=$((query_cursor + 1)); continue ;;
                $'\e[H'|$'\eOH'|$'\e[1~'|$'\e[7~'|$'\001') query_cursor=0; continue ;;
                $'\e[F'|$'\eOF'|$'\e[4~'|$'\e[8~'|$'\005') query_cursor=${#query}; continue ;;
                $'\177'|$'\b')
                    if (( query_cursor > 0 )); then
                        query="${query:0:query_cursor-1}${query:query_cursor}"; query_cursor=$((query_cursor - 1))
                    fi ;;
                $'\e[3~') query="${query:0:query_cursor}${query:query_cursor+1}" ;;
                $'\025') query=''; query_cursor=0 ;;
                $'\013') query="${query:0:query_cursor}" ;;
                $'\e') query=''; query_cursor=0; searching=false; selected=0; offset=0; continue ;;
                ''|$'\e[A'|$'\eOA'|$'\e[B'|$'\eOB') ;;
                *)
                    if [[ ! $key =~ [[:cntrl:]] ]]; then
                        query="${query:0:query_cursor}$key${query:query_cursor}"; query_cursor=$((query_cursor + ${#key}))
                    fi ;;
            esac
            case $key in
                ''|$'\e[A'|$'\eOA'|$'\e[B'|$'\eOB') ;;
                *) selected=0; offset=0; continue ;;
            esac
        fi
        case $key in
            /) nav_focus=false; searching=true; query_cursor=${#query}; selected=0; offset=0 ;;
            s) nav_focus=false ;;
            u) manager_view __update ;;
            q|$'\e') return ;;
            e|o|i)
                local -a context=()
                if [[ -n $client ]]; then
                    sid=$(client_session "$client")
                    context=("${PIMUX_COMMAND[0]}" "$PIMUX_TARGET_SOCKET" "$(tmux display-message -p -t "$sid:" '#{pane_id}')")
                fi
                if [[ $key == i ]]; then manager_view network --client "$client" "${context[@]}"
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
                    current=${roots[selected]}; current_window=${windows[selected]}; current_pane=${panes[selected]}
                else error=$(tr_ui '无法保存置顶设置。'); fi
                ;;
            a|d)
                if (( count == 0 )); then error=$(tr_ui '请先选择一个窗口或分屏。'); continue; fi
                current=${roots[selected]}; current_window=${windows[selected]}; current_pane=${panes[selected]}
                preview_target="$current:$current_window"
                if [[ -z $current_window && -n $client ]]; then
                    sid=$(client_session "$client")
                    [[ $(logical_session "$sid") != "$current" ]] || preview_target="$sid:"
                fi
                if [[ $key == d ]]; then
                    manager_view window_details "${PIMUX_COMMAND[0]}" "$PIMUX_TARGET_SOCKET" "$preview_target"
                else
                    pane=${panes[selected]}
                    [[ -n $pane ]] || pane=$(tmux display-message -p -t "$preview_target" '#{pane_id}')
                    manager_view layout_ui "${PIMUX_COMMAND[0]}" "$PIMUX_TARGET_SOCKET" "$pane"
                fi
                ;;
            n)
                printf '\033[?1000l\033[?1006l\033[%s;1H\033[2K\033[?25h' "$rows"
                stty "$terminal_mode"
                suggestion=$(printf '%s' "${PWD##*/}" | sed 's/[.:$#{}[:cntrl:]]/-/g; s/^-*//')
                name=''; IFS= read -er -i "${suggestion:-work}" \
                    -p $'\001\033[38;2;99;197;248m\002'"$(tr_ui ' 会话名称（Enter 确认，清空取消）：')"$'\001\033[0m\002' name || name=''
                stty -icanon -echo min 1 time 0
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
                pane=${panes[selected]}
                if [[ -n $pane ]] && [[ $(tmux display-message -p -t "$pane" '#{window_id}' 2>/dev/null) != "${windows[selected]}" ]]; then
                    error=$(tr_ui '分屏已关闭或移出，请重新选择。'); continue
                fi
                restore_manager; trap - EXIT
                connect_session "${roots[selected]}" "${windows[selected]}" "$client" "${panes[selected]}"
                return
                ;;
            x)
                (( count > 0 )) || continue
                sid=${roots[selected]}; wid=${windows[selected]}
                printf '\033[%s;1H\033[2K\033[38;2;255;175;95m' "$rows"
                pane=${panes[selected]}
                if [[ -n $pane ]]; then
                    printf_ui ' 关闭分屏 %s 及其中的程序，影响所有连接？[y/N] ' "${pane_indices[selected]}"
                elif [[ -z $wid ]]; then
                    name=$(tmux display-message -p -t "$sid:" '#{session_name}')
                    printf_ui ' 关闭会话 %s 及其全部窗口，影响所有连接？[y/N] ' "$name"
                else
                    name=$(tmux display-message -p -t "$sid:$wid" '#{window_name}')
                    printf_ui ' 关闭窗口 %s，影响所有连接？[y/N] ' "$name"
                fi
                printf '\033[0m'
                answer=''; read_ui_key && answer=$PIMUX_KEY
                [[ $answer == y ]] || continue
                if [[ -n $pane ]]; then
                    tmux kill-pane -t "$pane" || error=$(tr_ui '分屏已关闭或不存在。')
                elif [[ -z $wid ]]; then
                    close_session "$sid" || error=$(tr_ui '会话已关闭或不存在。')
                else
                    tmux kill-window -t "$sid:$wid" || error=$(tr_ui '窗口已关闭或不存在。')
                fi
                ;;
        esac
    done
)
