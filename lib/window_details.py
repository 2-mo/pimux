# pimux-managed: read-only window state and recent output, independent of RIPO.
"""Preview all panes of an exact tmux window without changing client selection."""

import argparse
from pathlib import Path
import subprocess

from gpu_ui import MUTED_STYLE, tr
from inspect_ui import Document, text


def window_blocks(binary, socket, target):
    def tmux(*args):
        try:
            result = subprocess.run([binary, "-S", socket, *args], capture_output=True, timeout=3)
        except subprocess.TimeoutExpired:
            raise RuntimeError(tr("Window query timed out.", "窗口查询超时。")) from None
        if result.returncode:
            raise RuntimeError(tr("Window or pane has closed or is unavailable.", "窗口或 pane 已关闭或不可见。"))
        # Text mode would normalize carriage returns that belong to metadata.
        return result.stdout.decode("utf-8", errors="replace")

    def field(pane, name):
        # One value per query: only the final LF belongs to tmux's output record.
        return tmux("display-message", "-p", "-t", pane, "#{" + name + "}").removesuffix("\n")

    fields = "\t".join("#{" + name + "}" for name in (
        "pane_id", "pane_pid", "pane_dead", "pane_dead_status"))
    rows = tmux("list-panes", "-t", target, "-F", fields)
    blocks = []
    for row in rows.splitlines():
        pane, pid, dead, code = row.split("\t", 3)
        program = field(pane, "pane_current_command")
        cwd = field(pane, "pane_current_path")
        command_status = field(pane, "@pimux_command_status")
        if dead == "1":
            state = tr("Exited", "已退出") + f" · exit {code or '?'}"
            style = "green" if code == "0" else "red"
        else:
            idle = program in {"bash", "zsh", "fish", "sh", "dash", "ksh"}
            state = tr("Shell idle", "shell 空闲") if idle else tr("Process alive", "进程存活")
            style = MUTED_STYLE if idle else "green"
            if command_status.isascii() and command_status.isdigit() and command_status.strip("0"):
                state += tr(" · last command exit ", " · 上次命令退出码 ") + command_status
                style = "yellow"
            if not cwd:
                try:
                    cwd = str(Path(f"/proc/{pid}/cwd").readlink())
                except OSError:
                    pass
        lines = [text(f"{pane} · PID {pid} · {program}", "bold #63c5f8"), text(state, style),
                 text(tr("Cwd: ", "目录：") + (cwd or tr("unavailable", "不可见")), MUTED_STYLE),
                 text(tr("Recent output", "最近输出"), "bold")]
        try:
            output = tmux("capture-pane", "-p", "-t", pane, "-S", "-60")
            lines.extend(text(line) for line in output.rstrip("\n").splitlines()[-60:])
        except RuntimeError as error:
            lines.append(text(error, MUTED_STYLE))
        blocks.append(lines)
    return blocks


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("binary")
    parser.add_argument("socket")
    parser.add_argument("target")
    args = parser.parse_args(argv)
    return Document(tr("Window preview", "窗口预览"),
                    lambda: window_blocks(args.binary, args.socket, args.target)).run()


if __name__ == "__main__":
    raise SystemExit(main())
