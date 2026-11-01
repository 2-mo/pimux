# pimux-managed: launch the bundled GPU dashboard in its private Python environment.
gpu_view() {
    local directory="$(dirname -- "$PIMUX_LAUNCHER")"
    local python="$HOME/.local/share/pimux/venv/bin/python"
    if [[ -f $directory/gpu.py ]]; then
        # Source checkouts use the development environment managed by uv.
        [[ ! -x $directory/.venv/bin/python ]] || python="$directory/.venv/bin/python"
    else
        directory="$HOME/.config/pimux"
    fi
    if [[ ! -x $python ]]; then
        printf '%s\n' "$(tr_ui '显卡界面的运行环境未就绪，请运行 pimux update 完成安装。')" >&2
        return 1
    fi
    export PIMUX_LANGUAGE
    exec "$python" "$directory/gpu.py"
}
