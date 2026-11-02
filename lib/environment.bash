# pimux-managed: apply literal environment defaults inside PiMux Bash shells.
pimux_environment_python() {
    local directory="$(dirname -- "${BASH_SOURCE[0]}")"
    local python="$HOME/.local/share/pimux/venv/bin/python"
    [[ ! -x $directory/../.venv/bin/python ]] || python="$directory/../.venv/bin/python"
    [[ -x $python ]] || return 1
    "$python" -E "$directory/environment.py" "$@"
}

pimux_apply_environment() {
    # Reserved local names keep user variables such as "key" and "value" global.
    local PIMUX_ENV_PATH=${PIMUX_ENV_FILE:-$HOME/.config/pimux/environment.json}
    local PIMUX_ENV_FILE_STATE PIMUX_ENV_RECORD PIMUX_ENV_KEY PIMUX_ENV_MODE PIMUX_ENV_VALUE PIMUX_ENV_ATTRIBUTES
    local -a PIMUX_ENV_RECORDS=()
    local -A PIMUX_ENV_PRESENT=()
    if [[ -f $PIMUX_ENV_PATH ]]; then PIMUX_ENV_FILE_STATE=$(stat -Lc '%i:%s:%y' -- "$PIMUX_ENV_PATH" 2>/dev/null) || return 0
    else PIMUX_ENV_FILE_STATE=absent; fi
    [[ ${1:-} == force || ${PIMUX_ENV_SIGNATURE:-} != "$PIMUX_ENV_FILE_STATE" ]] || return 0
    while IFS= read -r -d '' PIMUX_ENV_RECORD; do PIMUX_ENV_RECORDS+=("$PIMUX_ENV_RECORD"); done < <(pimux_environment_python __emit 2>/dev/null)
    [[ ${PIMUX_ENV_RECORDS[0]:-} == PIMUX_ENV_V1 ]] || return 0
    local PIMUX_ENV_INDEX
    for ((PIMUX_ENV_INDEX=1; PIMUX_ENV_INDEX+2<${#PIMUX_ENV_RECORDS[@]}; PIMUX_ENV_INDEX+=3)); do
        PIMUX_ENV_KEY=${PIMUX_ENV_RECORDS[PIMUX_ENV_INDEX]}
        PIMUX_ENV_MODE=${PIMUX_ENV_RECORDS[PIMUX_ENV_INDEX+1]}
        PIMUX_ENV_VALUE=${PIMUX_ENV_RECORDS[PIMUX_ENV_INDEX+2]}
        PIMUX_ENV_PRESENT[$PIMUX_ENV_KEY]=1
        PIMUX_ENV_ATTRIBUTES=$(declare -p "$PIMUX_ENV_KEY" 2>/dev/null) || PIMUX_ENV_ATTRIBUTES=''
        [[ ! $PIMUX_ENV_ATTRIBUTES =~ ^declare\ -[^[:space:]]*[raAinlu] ]] || continue
        PIMUX_ENV_RECORD="$PIMUX_ENV_MODE"$'\n'"$PIMUX_ENV_VALUE"
        if [[ ${PIMUX_ENV_APPLIED[$PIMUX_ENV_KEY]-} == "$PIMUX_ENV_RECORD" ]]; then
            [[ ${1:-} == force && ( -z ${2:-} || ${2:-} == "$PIMUX_ENV_KEY" ) ]] || continue
        fi
        if [[ ! -v PIMUX_ENV_ORIGINAL_SET[$PIMUX_ENV_KEY] ]]; then
            PIMUX_ENV_ORIGINAL_VALUE[$PIMUX_ENV_KEY]=${!PIMUX_ENV_KEY-}
            if [[ -v $PIMUX_ENV_KEY ]]; then PIMUX_ENV_ORIGINAL_SET[$PIMUX_ENV_KEY]=yes
            else PIMUX_ENV_ORIGINAL_SET[$PIMUX_ENV_KEY]=no; fi
            if [[ $PIMUX_ENV_ATTRIBUTES =~ ^declare\ -[^[:space:]]*x ]]; then PIMUX_ENV_ORIGINAL_EXPORT[$PIMUX_ENV_KEY]=yes
            else PIMUX_ENV_ORIGINAL_EXPORT[$PIMUX_ENV_KEY]=no; fi
        fi
        if [[ $PIMUX_ENV_MODE == on ]]; then export "$PIMUX_ENV_KEY=$PIMUX_ENV_VALUE"
        else unset "$PIMUX_ENV_KEY"; fi
        PIMUX_ENV_APPLIED[$PIMUX_ENV_KEY]=$PIMUX_ENV_RECORD
    done
    for PIMUX_ENV_KEY in "${!PIMUX_ENV_APPLIED[@]}"; do
        [[ ${PIMUX_ENV_PRESENT[$PIMUX_ENV_KEY]:-} != 1 ]] || continue
        PIMUX_ENV_ATTRIBUTES=$(declare -p "$PIMUX_ENV_KEY" 2>/dev/null) || PIMUX_ENV_ATTRIBUTES=''
        if [[ ! $PIMUX_ENV_ATTRIBUTES =~ ^declare\ -[^[:space:]]*[raAinlu] ]]; then
            if [[ ${PIMUX_ENV_ORIGINAL_SET[$PIMUX_ENV_KEY]} == yes ]]; then
                printf -v "$PIMUX_ENV_KEY" '%s' "${PIMUX_ENV_ORIGINAL_VALUE[$PIMUX_ENV_KEY]}"
                if [[ ${PIMUX_ENV_ORIGINAL_EXPORT[$PIMUX_ENV_KEY]} == yes ]]; then export "$PIMUX_ENV_KEY"
                else export -n "$PIMUX_ENV_KEY"; fi
            else unset "$PIMUX_ENV_KEY"; fi
        fi
        unset 'PIMUX_ENV_APPLIED[$PIMUX_ENV_KEY]' 'PIMUX_ENV_ORIGINAL_SET[$PIMUX_ENV_KEY]' \
              'PIMUX_ENV_ORIGINAL_VALUE[$PIMUX_ENV_KEY]' 'PIMUX_ENV_ORIGINAL_EXPORT[$PIMUX_ENV_KEY]'
    done
    PIMUX_ENV_SIGNATURE=$PIMUX_ENV_FILE_STATE
}

pimux_environment_prompt() {
    local PIMUX_ENV_RETURN_CODE=$?
    pimux_apply_environment
    return "$PIMUX_ENV_RETURN_CODE"
}

pimux_environment_shell_init() {
    if [[ ${PIMUX_ENV_SHELL_PID:-} == "$BASHPID" ]]; then pimux_apply_environment; return; fi
    PIMUX_ENV_SHELL_PID=$BASHPID
    unset PIMUX_ENV_SIGNATURE
    declare -gA PIMUX_ENV_ORIGINAL_VALUE=() PIMUX_ENV_ORIGINAL_SET=() PIMUX_ENV_ORIGINAL_EXPORT=() PIMUX_ENV_APPLIED=()
    PROMPT_COMMAND+=(pimux_environment_prompt)
    pimux_apply_environment
    if [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]]; then
        command tmux -S "${TMUX%%,*}" set-option -p -t "$TMUX_PANE" @pimux_environment_ready on 2>/dev/null || true
    fi
}
