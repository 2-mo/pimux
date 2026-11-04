# pimux-managed: help and full paths use the same view as other PiMux details.
"""Readable help from actual bindings, displayed in a client-local popup."""

import argparse
import os
from pathlib import Path
import subprocess

from gpu_ui import MUTED_STYLE, tr
from inspect_ui import Document, text
from host_runtime import process_cwd


def key_notes(binary, socket):
    launcher = os.environ.get("PIMUX_LAUNCHER", str(Path(__file__).resolve().parents[1] / "bin/pimux"))
    result = subprocess.run([launcher, "__key-notes", binary, socket], capture_output=True, text=True, timeout=3)
    if result.returncode:
        raise RuntimeError(tr("Could not read keyboard help.", "无法读取快捷键帮助。"))
    return [line.split("\t", 1) for line in result.stdout.splitlines() if "\t" in line]


def help_blocks(binary, socket):
    bindings = []
    for key, description in key_notes(binary, socket):
        line = text("  " + key, "color(215)")
        line.pad_right(max(0, 11 - line.cell_len))
        line.append(description)
        bindings.append(line)
    return [
        [text(tr("Getting started", "开始使用"), "bold #63c5f8"),
         text(tr("Press Ctrl-a, release it, then press an action key.", "先按 Ctrl-a 并松开，再按操作键。")),
         text(tr("c creates a window · , renames it · x closes the current pane after confirmation.",
                 "c 新建窗口 · , 重命名窗口 · x 确认后关闭当前分屏。")),
         text(tr("d detaches and keeps tasks running · h opens the menu · / opens this page.",
                 "d 离开并保留任务 · h 打开菜单 · / 查看帮助。"), MUTED_STYLE)],
        [text(tr("Nested splits", "连续分屏"), "bold #63c5f8"),
         text(tr("After Ctrl-a, - splits top/bottom and v splits left/right. Repeat inside any selected pane.",
                 "Ctrl-a 后按 - 上下分、v 左右分，可在选中的分屏里继续分割。"))],
        [text(tr("Window attention", "窗口异常提示"), "bold #63c5f8"),
         text(tr("A bold, inverted number marks a failed command. The next success in that pane clears it.",
                 "编号加粗反色表示命令失败；同一分屏后续命令成功后恢复。")),
         text(tr("Other panes keep their own reports. In the manager, d shows the last exit codes.",
                 "其他分屏的错误分别保留；管理列表中按 d 查看各分屏的上次退出码。"))],
        [text(tr("Keyboard shortcuts", "快捷键"), "bold #63c5f8"), *bindings],
        [text(tr("Inside the manager", "管理列表内"), "bold #63c5f8"),
         text(tr("/ searches panes · arrows select · Enter opens · d previews · n creates a session.",
                 "/ 搜索分屏 · 方向键选择 · Enter 直达 · d 预览 · n 新建会话。")),
         text(tr("x closes the selected session, window or pane after confirmation; the action bar names the target.",
                 "x 确认后关闭选中的会话、窗口或分屏；底部提示会标明对象。"))],
        [text(tr("Main interface", "主界面"), "bold #63c5f8"),
         text(tr("Open pimux; the tree groups Workspace, Resources, Network and Settings.",
                 "打开 pimux，树形菜单按工作区、资源、网络、设置分组。")),
         text(tr("Click an entry or press e / o / g / t / i / ?. q returns to your session selection.",
                 "可点击入口，也可按 e / o / g / t / i / ?；q 返回原会话选择。")),
         text(tr("pimux env / proxy / gpu / ports / ip / help remain optional shortcuts.",
                 "pimux env / proxy / gpu / ports / ip / help 都是可选的快捷入口。"), MUTED_STYLE),
         text("pimux update    " + tr("Linux release update; Mac: follow the installation source", "Linux 更新发布版；Mac 请按安装来源更新"))],
        [text(tr("Inside environment settings", "环境变量页内"), "bold #63c5f8"),
         text(tr("Enter views/edits · n adds · Space enables/disables · i restores inheritance.",
                 "Enter 查看／修改 · n 新增 · Space 启停 · i 恢复继承。")),
         text(tr("F2 reveals or masks the value while editing. Shell-maintained variables are read only.",
                 "编辑时 F2 显示／隐藏变量值；shell 维护的变量只读。"), MUTED_STYLE)],
        [text(tr("Finding panes", "查找分屏"), "bold #63c5f8"),
         text(tr("Search projects, windows, programs or paths; 2.1 means window 2, pane 1.",
                 "按项目、窗口、程序或目录搜索；2.1 表示窗口 2、分屏 1。")),
         text(tr("Left/Right and Home/End move the cursor; Backspace/Delete edits; Ctrl-U clears.",
                 "←/→、Home/End 移动光标，Backspace/Delete 删除，Ctrl-U 清空。"))],
        [text(tr("Arranging panes", "调整分屏"), "bold #63c5f8"),
         text(tr("Workspace → Arrange panes offers equal rows/columns, tiling and swaps.",
                 "工作区 → 调整分屏，集中提供均分、平铺和换位。")),
         text(tr("Choose Adjust size, then use arrows continuously; Enter/Esc finishes, Tab changes pane.",
                 "选择调整大小后，方向键可连续操作；Enter/Esc 完成，Tab 切换分屏。"))],
        [text(tr("Tree navigation", "树形菜单"), "bold #63c5f8"),
         text(tr("Tab switches menu/sessions on the home screen; arrows select/expand, Enter opens.",
                 "首页 Tab 切换菜单／会话；方向键选择、展开或收起，Enter 进入。")),
         text(tr("Ctrl-a h uses the same groups. Action keys also work inside collapsed groups.",
                 "Ctrl-a h 使用同样的分组；分组收起时也可直接按操作键。"))],
        [text(tr("IP copying", "IP 复制"), "bold #63c5f8"),
         text(tr("Select an address with arrows or a click; y / Enter copies the IP, Y copies its CIDR subnet.",
                 "方向键或鼠标选中地址，y / Enter 复制 IP，Y 复制对应的 CIDR 子网。"))],
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
        path = process_cwd(result.stdout.strip())
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
