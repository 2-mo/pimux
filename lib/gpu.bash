# pimux-managed: launch bundled views in the private Python environment.
python_view() {
    local view=$1
    shift
    local directory=$PIMUX_UI_DIR
    local development="$(dirname -- "$PIMUX_LAUNCHER")/.venv/bin/python"
    local python="$HOME/.local/share/pimux/venv/bin/python"
    # Source checkouts use the development environment managed by uv.
    [[ ! -x $development ]] || python=$development
    if [[ ! -x $python ]]; then
        printf '%s\n' "$(tr_ui '界面的运行环境未就绪，请运行 pimux update 完成安装。')" >&2
        return 1
    fi
    export PIMUX_LANGUAGE PIMUX_LAUNCHER
    exec "$python" -E "$directory/$view.py" "$@"
}
