# pimux-managed: live GPU details in a client-local popup.
gpu_view() (
    local snapshot='' key rows cols height offset=0 last=-5 refresh=true i
    local -a lines=()
    [[ -t 0 && -t 1 ]] || return 1
    trap "printf '\033[?1000l\033[?1006l\033[0m\033[?7h\033[?25h\033[?1049l'" EXIT
    trap 'exit 130' INT TERM HUP
    trap ':' WINCH
    printf '\033[?1049h\033[?25l\033[?7l\033[?1000h\033[?1006h'
    while :; do
        if [[ $refresh == true ]] || (( SECONDS - last >= 5 )); then
            if ! command -v nvidia-smi >/dev/null 2>&1; then
                snapshot=$(tr_ui '未找到 nvidia-smi；显卡详情需要 NVIDIA 驱动。')
            elif ! snapshot=$(timeout -k 1 3 nvidia-smi 2>/dev/null); then
                snapshot=$(tr_ui '显卡查询失败或超时；按 r 重试。')
            fi
            mapfile -t lines < <(printf '%s\n' "$snapshot" | sed 's/[[:cntrl:]]/?/g')
            last=$SECONDS; refresh=false
        fi
        read -r rows cols < <(stty size)
        height=$((rows > 5 ? rows - 5 : 1))
        (( offset + height <= ${#lines[@]} )) || offset=$((${#lines[@]} > height ? ${#lines[@]} - height : 0))
        printf '\033[H\033[2J\033[38;2;183;161;232m pimux · %s\033[0m\n\n' "$(tr_ui '显卡详情')"
        for ((i=offset; i<offset+height && i<${#lines[@]}; i++)); do
            printf '%s\n' "${lines[i]}"
        done
        printf '\033[%s;1H\033[38;2;255;175;95m%s\033[0m' "$((rows > 1 ? rows - 1 : 1))" \
            "$(tr_ui '每 5 秒刷新  滚轮 / ↑↓ / PgUp / PgDn 滚动  r 刷新  q / Esc 返回')"
        key=''
        read_ui_key 1 || continue
        key=$PIMUX_KEY
        case $key in
            mouse)
                case $PIMUX_MOUSE_BUTTON in
                    64) offset=$((offset > 3 ? offset - 3 : 0)) ;;
                    65) offset=$((offset + 3)) ;;
                esac ;;
            q|$'\e') return ;;
            r) refresh=true ;;
            j|$'\e[B'|$'\eOB') offset=$((offset + 1)) ;;
            k|$'\e[A'|$'\eOA') (( offset == 0 )) || offset=$((offset - 1)) ;;
            $'\e[6~') offset=$((offset + height)) ;;
            $'\e[5~') offset=$((offset > height ? offset - height : 0)) ;;
        esac
    done
)
