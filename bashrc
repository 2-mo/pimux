# piux-managed: shared Bash prompt for tmux and ordinary terminals.
case $- in
    *i*) ;;
    *) return ;;
esac

case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac

if command -v starship >/dev/null 2>&1; then
    export STARSHIP_CONFIG="$HOME/.config/piux/starship.toml"
    # STARSHIP_SHELL is inherited by tmux and nested shells; functions are not.
    if ! declare -F starship_precmd >/dev/null; then
        eval "$(starship init bash)"
    fi
fi
