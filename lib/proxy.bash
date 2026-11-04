# pimux-managed: proxy preferences and integration for PiMux's Bash shells.
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.bash"
pimux_proxy_read() {
    local file=${PIMUX_PROXY_FILE:-$HOME/.config/pimux/proxy} mode url
    PIMUX_PROXY_MODE=inherit
    PIMUX_PROXY_URL=''
    [[ -f $file ]] || return 0
    { IFS= read -r mode; IFS= read -r url || true; } < "$file"
    case $mode in on|off|inherit) ;; *) return 1 ;; esac
    if [[ -n $url ]] && ! pimux_proxy_valid_url "$url"; then return 1; fi
    [[ $mode != on || -n $url ]] || return 1
    PIMUX_PROXY_MODE=$mode
    PIMUX_PROXY_URL=$url
}

pimux_proxy_valid_url() {
    [[ $1 =~ ^(https?|socks5h?)://[^[:space:][:cntrl:]/\?\#]+/?$ ]]
}

pimux_proxy_environment_url() {
    printf '%s' "${https_proxy:-${HTTPS_PROXY:-${http_proxy:-${HTTP_PROXY:-${all_proxy:-${ALL_PROXY:-}}}}}}"
}

pimux_proxy_mask_url() {
    local url=$1 prefix
    if [[ $url == *@* ]]; then
        prefix=''
        [[ $url != *://* ]] || prefix="${url%%://*}://"
        url="$prefix***@${url##*@}"
    fi
    printf '%s' "$url" | sed 's/[[:cntrl:]]/?/g'
}

pimux_proxy_save() (
    local mode=$1 url=$2 file=${PIMUX_PROXY_FILE:-$HOME/.config/pimux/proxy} temporary
    case $mode in on|off|inherit) ;; *) return 2 ;; esac
    if [[ -n $url ]] && ! pimux_proxy_valid_url "$url"; then
        printf '%s\n' "$(tr_ui '代理地址需以 http://、https://、socks5:// 或 socks5h:// 开头，且不能含空白。')" >&2
        return 2
    fi
    if [[ $mode == on && -z $url ]]; then
        printf '%s\n' "$(tr_ui '请先设置代理地址。')" >&2
        return 2
    fi
    umask 077
    mkdir -p -- "$(dirname -- "$file")"
    exec 9>"${file}.lock"
    pimux_lock 9
    temporary=$(mktemp "${file}.new.XXXXXX")
    trap 'rm -f -- "$temporary"' EXIT
    printf '%s\n%s\n' "$mode" "$url" > "$temporary"
    mv -- "$temporary" "$file"
)

pimux_proxy_show() {
    local environment=${1:-true} mode key value
    pimux_proxy_read || { printf '%s\n' "$(tr_ui '代理配置无效，请重新设置。')" >&2; return 1; }
    case $PIMUX_PROXY_MODE in on) mode='启用' ;; off) mode='停用' ;; *) mode='继承启动环境' ;; esac
    printf 'PiMux · %s: %s\n' "$(tr_ui '网络代理')" "$(tr_ui "$mode")"
    [[ -z $PIMUX_PROXY_URL ]] || printf '%s: %s\n' "$(tr_ui '地址')" "$(pimux_proxy_mask_url "$PIMUX_PROXY_URL")"
    if [[ $environment == true ]]; then
        printf '\n%s\n' "$(tr_ui '当前终端传入的环境：')"
        for key in http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY no_proxy NO_PROXY; do
            value=${!key:-}
            [[ -z $value ]] || printf '  %s=%s\n' "$key" "$(pimux_proxy_mask_url "$value")"
        done
    fi
}

pimux_proxy_command() {
    local action=${1:-show} url=${2:-}
    pimux_proxy_read || { PIMUX_PROXY_MODE=inherit; PIMUX_PROXY_URL=''; }
    case $action in
        show) [[ $# -le 1 ]] || return 2; pimux_proxy_show; return ;;
        set) [[ $# == 2 ]] || return 2; pimux_proxy_save on "$url" || return ;;
        on) [[ $# == 1 ]] || return 2; pimux_proxy_save on "${PIMUX_PROXY_URL:-$(pimux_proxy_environment_url)}" || return ;;
        off|reset)
            [[ $# == 1 ]] || return 2
            [[ $action != reset ]] || action=inherit
            pimux_proxy_save "$action" "$PIMUX_PROXY_URL" || return ;;
        *) printf 'pimux proxy [set URL | on | off | reset]\n' >&2; return 2 ;;
    esac
    pimux_proxy_show false
    printf '%s\n' "$(tr_ui '已保存；新终端自动应用，已集成的 PiMux shell 在下次提示符应用。')"
}

pimux_apply_proxy() {
    local key saved present exported state
    pimux_proxy_read || return 0
    state="$PIMUX_PROXY_MODE"$'\n'"$PIMUX_PROXY_URL"
    if [[ ${1:-} != force && ${PIMUX_PROXY_APPLIED_STATE:-} == "$state" ]]; then return 0; fi
    # Inherit leaves manual exports alone until switching back from a managed mode.
    if [[ $PIMUX_PROXY_MODE == inherit && ${PIMUX_PROXY_APPLIED_MODE:-inherit} == inherit ]]; then
        PIMUX_PROXY_APPLIED_STATE=$state
        return 0
    fi
    for key in http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY; do
        case $PIMUX_PROXY_MODE in
            on) export "$key=$PIMUX_PROXY_URL" ;;
            off) unset "$key" ;;
            inherit)
                saved="PIMUX_PROXY_ORIGINAL_$key"; present="${saved}_SET"; exported="${saved}_EXPORTED"
                if [[ ${!present:-} == yes ]]; then
                    printf -v "$key" '%s' "${!saved}"
                    if [[ ${!exported:-} == yes ]]; then export "$key"; else export -n "$key"; fi
                else unset "$key"; fi ;;
        esac
    done
    PIMUX_PROXY_APPLIED_STATE=$state
    PIMUX_PROXY_APPLIED_MODE=$PIMUX_PROXY_MODE
}

pimux_report_proxy() {
    [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]] || return 0
    local state=off key signature
    for key in http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY; do
        [[ -z ${!key:-} ]] || state=on
    done
    signature="${TMUX%%,*}|$TMUX_PANE|$state"
    [[ ${PIMUX_PROXY_REPORTED:-} != "$signature" ]] || return 0
    if command "${PIMUX_TMUX:-tmux}" -S "${TMUX%%,*}" set-option -p -t "$TMUX_PANE" @pimux_proxy_status "$state" 2>/dev/null; then
        PIMUX_PROXY_REPORTED=$signature
    fi
    return 0
}

pimux_proxy_prompt() {
    local status=$?
    pimux_apply_proxy
    pimux_report_proxy
    return "$status"
}

pimux_proxy_shell_init() {
    local key attributes
    if [[ ${PIMUX_PROXY_SHELL_PID:-} == "$BASHPID" ]]; then pimux_apply_proxy; return; fi
    PIMUX_PROXY_SHELL_PID=$BASHPID
    unset PIMUX_PROXY_APPLIED_STATE PIMUX_PROXY_APPLIED_MODE PIMUX_PROXY_REPORTED
    for key in http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY; do
        printf -v "PIMUX_PROXY_ORIGINAL_$key" '%s' "${!key:-}"
        if [[ -v $key ]]; then printf -v "PIMUX_PROXY_ORIGINAL_${key}_SET" yes
        else printf -v "PIMUX_PROXY_ORIGINAL_${key}_SET" no; fi
        attributes=$(declare -p "$key" 2>/dev/null) || attributes=''
        if [[ $attributes =~ ^declare\ -[^[:space:]]*x ]]; then
            printf -v "PIMUX_PROXY_ORIGINAL_${key}_EXPORTED" yes
        else printf -v "PIMUX_PROXY_ORIGINAL_${key}_EXPORTED" no; fi
    done
    PROMPT_COMMAND+=(pimux_proxy_prompt)
    pimux() {
        local PIMUX_COMMAND_STATUS=0
        command pimux "$@" || PIMUX_COMMAND_STATUS=$?
        if (( PIMUX_COMMAND_STATUS == 0 )) && [[ ${1:-} == proxy ]]; then
            case ${2:-} in set|on|off|reset) pimux_apply_proxy force ;; *) pimux_apply_proxy ;; esac
            pimux_report_proxy
        fi
        if (( PIMUX_COMMAND_STATUS == 0 )) && [[ ${1:-} == env ]] && declare -F pimux_apply_environment >/dev/null; then
            case ${2:-} in set|on|off|reset) pimux_apply_environment force "${3:-}" ;; *) pimux_apply_environment ;; esac
        fi
        return "$PIMUX_COMMAND_STATUS"
    }
    pimux_apply_proxy
    pimux_report_proxy
}
