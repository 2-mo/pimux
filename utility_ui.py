# pimux-managed: help and full paths use the same view as other PiMux details.
"""Readable help from actual bindings, displayed in a client-local popup."""

import argparse
import os
from pathlib import Path
import subprocess

from gpu_ui import MUTED_STYLE, tr
from inspect_ui import Document, text


def key_notes(binary, socket):
    launcher = os.environ.get("PIMUX_LAUNCHER", str(Path(__file__).with_name("pimux")))
    result = subprocess.run(["bash", "-c", 'source "$1"; PIMUX_COMMAND=("$2" -S "$3"); shortcut_help',
                             "help", launcher, binary, socket], capture_output=True, text=True, timeout=3)
    if result.returncode:
        raise RuntimeError(tr("Could not read keyboard help.", "无法读取快捷键帮助。"))
    return [line.split("\t", 1) for line in result.stdout.splitlines() if "\t" in line]


def help_blocks(binary, socket):
    bindings = []
    for key, description in key_notes(binary, socket):
        line = text(f"  {key:<9}", "color(215)")
        line.append(description)
        bindings.append(line)
    return [
        [text(tr("Getting started", "开始使用"), "bold #63c5f8"),
         text(tr("Press Ctrl-a, release it, then press an action key.", "先按 Ctrl-a 并松开，再按操作键。")),
         text(tr("h opens the menu · / opens this page · x closes the selected pane after confirmation.",
                 "h 打开菜单 · / 查看帮助 · x 确认后关闭选中的分屏。"))],
        [text(tr("Keyboard shortcuts", "快捷键"), "bold #63c5f8"), *bindings],
        [text(tr("Inside the manager", "管理列表内"), "bold #63c5f8"),
         text(tr("/ search · arrows select · Enter opens · d previews · n creates · x closes after confirmation.",
                 "/ 搜索 · 方向键选择 · Enter 进入 · d 预览 · n 新建 · x 确认关闭。"))],
        [text(tr("Main interface", "主界面"), "bold #63c5f8"),
         text(tr("Open pimux, then choose Env, Proxy, GPU, Ports or Help from the top row.",
                 "打开 pimux，在顶部选择环境、代理、显卡、端口或帮助。")),
         text(tr("Click an entry or press e / o / g / t / ?. q returns to your session selection.",
                 "可点击入口，也可按 e / o / g / t / ?；q 返回原会话选择。")),
         text(tr("pimux env / proxy / gpu / ports / help remain optional shortcuts.",
                 "pimux env / proxy / gpu / ports / help 都是可选的快捷入口。"), MUTED_STYLE),
         text("pimux update    " + tr("Update PiMux; also available in Ctrl-a h", "更新 PiMux，也可通过 Ctrl-a h 菜单操作"))],
        [text(tr("Inside environment settings", "环境变量页内"), "bold #63c5f8"),
         text(tr("Enter views/edits · n adds · Space enables/disables · i restores inheritance.",
                 "Enter 查看／修改 · n 新增 · Space 启停 · i 恢复继承。")),
         text(tr("F2 reveals or masks the value while editing. Shell-maintained variables are read only.",
                 "编辑时 F2 显示／隐藏变量值；shell 维护的变量只读。"), MUTED_STYLE)],
        [text(tr("Within a page", "页面内操作"), "bold #63c5f8"),
         text(tr("q / Esc returns · wheel or PgUp/PgDn scrolls · / searches where available.",
                 "q / Esc 返回 · 滚轮或 PgUp/PgDn 滚动 · 带搜索栏的页面可按 / 搜索。")),
         text(tr("While editing, Enter saves and Esc cancels. A search is cleared before leaving the page.",
                 "编辑时 Enter 保存、Esc 取消；搜索状态先清空搜索，再返回。"), MUTED_STYLE)],
    ]


def path_blocks(binary, socket, pane):
    result = subprocess.run([binary, "-S", socket, "display-message", "-p", "-t", pane, "#{pane_pid}"],
                            capture_output=True, text=True, timeout=3)
    if result.returncode:
        raise RuntimeError(tr("The pane has closed.", "分屏已经关闭。"))
    try:
        path = str(Path(f"/proc/{int(result.stdout.strip())}/cwd").readlink())
    except (OSError, ValueError):
        raise RuntimeError(tr("The working directory is not visible.", "当前工作目录不可见。")) from None
    return [[text(path, "#63c5f8")], [text(tr("Return, then press Ctrl-a y to copy this path.",
                                                            "返回后按 Ctrl-a y 可复制这个路径。"), MUTED_STYLE)]]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("view", choices=["help", "path"])
    parser.add_argument("binary")
    parser.add_argument("socket")
    parser.add_argument("pane", nargs="?")
    args = parser.parse_args(argv)
    if args.view == "path":
        if not args.pane:
            parser.error("Path view needs a pane")
        document = Document(tr("Full directory path", "完整目录路径"),
                            lambda: path_blocks(args.binary, args.socket, args.pane))
    else:
        document = Document(tr("Help", "使用帮助"), lambda: help_blocks(args.binary, args.socket), searchable=True)
    return document.run()


if __name__ == "__main__":
    raise SystemExit(main())
