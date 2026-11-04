# pimux-managed: focused proxy settings, backed by the existing Bash preferences.
"""Keep saved preferences distinct from the active pane's reported environment."""

import argparse
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from gpu_ui import MUTED_STYLE, TITLE_STYLE, console, edit_line, input_field, key_hints, run_screen, screen, tr
from inspect_ui import text
from proxy_status import process_proxy_state


def backend(action, mode="", url=""):
    launcher = os.environ.get("PIMUX_LAUNCHER", str(Path(__file__).resolve().parents[1] / "bin/pimux"))
    command = [launcher, "__proxy-read"] if action == "read" else [launcher, "__proxy-save", mode]
    try:
        result = subprocess.run(command,
                                input=url + "\n", capture_output=True, text=True, timeout=3)
    except subprocess.TimeoutExpired:
        raise RuntimeError(tr("Settings could not be read or saved. Try again.", "设置读取或保存超时，请重试。")) from None
    if result.returncode:
        if action == "read":
            raise RuntimeError(tr("Settings could not be read. Edit the address to set them again.",
                                  "无法读取设置，可修改地址重新设置。"))
        raise RuntimeError(tr("Could not save settings. Check the configuration file permissions and retry.",
                              "无法保存设置，请检查配置文件权限后重试。"))
    return result.stdout


def masked(url, *, editing=False):
    if "@" not in url:
        return url
    start = url.find("://") + 3 if "://" in url else 0
    end = url.rfind("@")
    return url[:start] + ("•" * (end - start) if editing else "***") + url[end:]


def normalize_url(value):
    value = value.strip()
    if "://" not in value:
        value = "http://" + value
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https", "socks5", "socks5h"}
                or not parsed.hostname or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or any(char.isspace() or ord(char) < 32 for char in value)
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError()
    except ValueError:
        raise ValueError(tr("Use a proxy address such as http://127.0.0.1:7890.",
                            "请输入有效代理地址，例如 http://127.0.0.1:7890。")) from None
    return value


class ProxyPanel:
    def __init__(self, context=()):
        self.context = context
        self.mode, self.url = "inherit", ""
        self.observed = ""
        self.inferred = False
        self.selected = 0
        self.editing = False
        self.buffer = ""
        self.cursor = 0
        self.error = ""
        self.notice = ""
        self.action_rows = {}

    def refresh(self):
        try:
            mode, url = backend("read").splitlines()
            self.mode, self.url = mode, url
        except (OSError, RuntimeError, ValueError) as error:
            self.error = str(error)
        self.observed = ""
        self.inferred = False
        if self.context:
            binary, socket, pane = self.context
            try:
                result = subprocess.run([binary, "-S", socket, "display-message", "-p", "-t", pane,
                                         "#{@pimux_proxy_status}\t#{pane_pid}"], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    reported, _, pid = result.stdout.rstrip("\n").partition("\t")
                    self.observed = reported
                    if reported not in {"on", "off"}:
                        self.observed = process_proxy_state(pid)
                        self.inferred = bool(self.observed)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def edit(self):
        self.editing = True
        self.buffer, self.cursor = self.url, len(self.url)
        self.error = self.notice = ""

    def save(self, mode, url):
        try:
            backend("save", mode, url)
        except (OSError, RuntimeError) as error:
            self.error = str(error)
            return False
        self.mode, self.url = mode, url
        self.error = ""
        self.notice = tr("Saved · press Enter at a PiMux shell prompt to apply.", "已保存 · 回到 PiMux shell 后按 Enter 应用。")
        return True

    def activate(self, index):
        self.selected = index
        if index == 1 or (index == 0 and self.mode != "on" and not self.url):
            self.edit()
        elif index == 0:
            self.save("off" if self.mode == "on" else "on", self.url)
        else:
            self.save("inherit", self.url)

    def on_key(self, key):
        name = getattr(key, "name", None) or key
        if not isinstance(name, str):
            return False
        if self.editing:
            if name == "KEY_ESCAPE":
                self.editing = False
                self.error = ""
            elif name == "KEY_ENTER":
                try:
                    value = normalize_url(self.buffer)
                    if self.save("on", value):
                        self.editing = False
                except ValueError as error:
                    self.error = str(error)
            else:
                self.buffer, self.cursor = edit_line(self.buffer, self.cursor, name)
            return False
        if name == "MOUSE_LEFT":
            _, y = key.mouse_xy
            if y in self.action_rows:
                self.activate(self.action_rows[y])
        elif name in {"KEY_UP", "MOUSE_SCROLL_UP", "KEY_DOWN", "MOUSE_SCROLL_DOWN"}:
            self.selected = (self.selected + (-1 if name in {"KEY_UP", "MOUSE_SCROLL_UP"} else 1)) % 3
        elif name == "KEY_ENTER":
            self.activate(self.selected)
        elif name == "e":
            self.edit()
        elif name == "o":
            self.save("on", self.url) if self.url else self.edit()
        elif name == "d":
            self.save("off", self.url)
        elif name == "i":
            self.save("inherit", self.url)
        elif name in {"q", "KEY_ESCAPE"}:
            return True
        return False

    def render(self, width, height):
        options = console.options.update(width=max(1, width))
        compact = height < 24
        labels = {"on": tr("Enabled", "启用"), "off": tr("Disabled", "停用"),
                  "inherit": tr("Use startup environment", "使用启动环境")}
        observed = {"on": tr("Proxy configured", "已配置代理"), "off": tr("No proxy configured", "未配置代理")}.get(
            self.observed, tr("Not reported yet", "尚未报告"))
        settings = [text(tr("PiMux setting   ", "PiMux 设置   ") + labels[self.mode],
                         "bold #63c5f8" if self.mode == "on" else "bold"),
                    text((tr("Foreground process   ", "前台进程   ") if self.inferred else
                          tr("Current terminal   ", "当前终端   ")) + observed, MUTED_STYLE)]
        if not self.editing:
            address = text(tr("Address   ", "地址   ") + (masked(self.url) or tr("Not set", "尚未设置")))
            address.no_wrap, address.overflow = True, "ellipsis"
            settings.append(address)
        body = [text(tr("PiMux · Network proxy", "PiMux · 网络代理"), TITLE_STYLE)]
        if not compact:
            body.append(Text(""))
        body.append(Panel(Group(*settings), border_style="#454957", padding=(0, 1) if compact else (1, 2)))
        self.action_rows = {}
        if self.editing:
            field = input_field(masked(self.buffer, editing=True), self.cursor, width - 4)
            body.extend([text(tr("Proxy address", "代理地址"), "bold #63c5f8"), field,
                         text(tr("Example: 127.0.0.1:7890 · HTTP / HTTPS / SOCKS5", "例如 127.0.0.1:7890 · 支持 HTTP / HTTPS / SOCKS5"), MUTED_STYLE)])
        else:
            actions = [
                (tr("Disable proxy", "停用代理") if self.mode == "on" else
                 tr("Enable proxy", "启用代理") if self.url else tr("Set up a proxy", "设置代理"),
                 tr("Keep the address for next time", "保留地址，方便下次开启") if self.mode == "on" else
                 tr("Use this address in PiMux shells", "让 PiMux shell 使用这个地址")),
                (tr("Edit address", "修改地址"), tr("Save a new address and enable it", "保存新地址并启用")),
                (tr("Use startup environment", "使用启动环境"), tr("Restore the environment each shell started with", "恢复每个 shell 启动时继承的代理设置")),
            ]
            for index, (label, description) in enumerate(actions):
                row = text((" › " if index == self.selected else "   ") + label)
                if index == self.selected:
                    row.stylize("bold #63c5f8 on #272b34")
                    row.pad_right(max(0, width - row.cell_len))
                y = len(console.render_lines(Group(*body), options, pad=False))
                count = len(console.render_lines(row, options, pad=False))
                self.action_rows.update({line: index for line in range(y, y + count)})
                body.append(row)
                if not compact:
                    body.append(text("   " + description, MUTED_STYLE))
                    if index < 2:
                        body.append(Text(""))
        if not compact:
            body.append(text(tr("Settings apply at the next shell prompt; running programs keep their environment.",
                                "设置在 shell 下次提示符时应用；运行中的程序保持原环境。"), MUTED_STYLE))
        explanation = tr("Older pane · read from the foreground process's startup environment.",
                         "旧窗口 · 根据前台进程的启动环境识别。") if self.inferred else tr(
                             "⛓ appears when a proxy is detected in the terminal.", "终端中检测到代理配置时，状态栏显示 ⛓。")
        feedback = text(self.error or self.notice or explanation,
                        "red" if self.error else "green" if self.notice else MUTED_STYLE)
        hints = [("Enter", tr("save & enable", "保存并启用")), ("Esc", tr("cancel", "取消")), ("Ctrl-u", tr("clear", "清空"))] if self.editing else [
            ("↑↓", tr("select", "选择")), ("Enter", tr("apply", "确认")), ("e", tr("edit", "编辑")), ("q", tr("back", "返回"))]
        if width < 65:
            hints = hints[:2] if self.editing else [("↑↓ Enter", ""), ("e", tr("edit", "编辑")), ("q", tr("back", "返回"))]
        footer = key_hints(hints)
        footer.no_wrap, footer.overflow = True, "ellipsis"
        return screen(Group(*body), footer, width, height, message=feedback)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("context", nargs="*")
    args = parser.parse_args(argv)
    if len(args.context) not in {0, 3}:
        parser.error("Expected tmux binary, socket and pane")
    view = ProxyPanel(args.context)
    return run_screen(view.render, view.on_key, view.refresh, interval=1,
                      can_refresh=lambda: not view.editing)


if __name__ == "__main__":
    raise SystemExit(main())
