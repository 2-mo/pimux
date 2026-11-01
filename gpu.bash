# pimux-managed: launch bundled views in the private Python environment.
python_view() {
    local view=$1
    shift
    local directory="$(dirname -- "$PIMUX_LAUNCHER")"
    local python="$HOME/.local/share/pimux/venv/bin/python"
    if [[ -f $directory/$view.py ]]; then
        # Source checkouts use the development environment managed by uv.
        [[ ! -x $directory/.venv/bin/python ]] || python="$directory/.venv/bin/python"
    else
        directory="$HOME/.config/pimux"
    fi
    if [[ ! -x $python ]]; then
        printf '%s\n' "$(tr_ui '界面的运行环境未就绪，请运行 pimux update 完成安装。')" >&2
        return 1
    fi
    export PIMUX_LANGUAGE PIMUX_LAUNCHER
    exec "$python" "$directory/$view.py" "$@"
}
