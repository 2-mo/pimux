# pimux-managed: report completed Bash commands to this pane's window indicator.
pimux_command_status_prompt() {
    local PIMUX_EXIT_CODE=$?
    if [[ -z ${TMUX:-} || -z ${TMUX_PANE:-} ]] || (( PIMUX_EXIT_CODE == 130 )); then
        return "$PIMUX_EXIT_CODE"
    fi
    local PIMUX_EXIT_SIGNATURE="${TMUX%%,*}|$TMUX_PANE|$PIMUX_EXIT_CODE"
    if [[ ${PIMUX_EXIT_REPORTED:-} != "$PIMUX_EXIT_SIGNATURE" ]]; then
        if command "${PIMUX_TMUX:-tmux}" -S "${TMUX%%,*}" set-option -p -t "$TMUX_PANE" \
                @pimux_command_status "$PIMUX_EXIT_CODE" 2>/dev/null; then
            PIMUX_EXIT_REPORTED=$PIMUX_EXIT_SIGNATURE
        fi
    fi
    return "$PIMUX_EXIT_CODE"
}

pimux_command_status_init() {
    [[ ${PIMUX_EXIT_SHELL_PID:-} != "$BASHPID" ]] || return 0
    PIMUX_EXIT_SHELL_PID=$BASHPID
    unset PIMUX_EXIT_REPORTED
    PROMPT_COMMAND+=(pimux_command_status_prompt)
}
