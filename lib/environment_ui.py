# pimux-managed: one place for environment defaults and the proxy shortcut.
"""Browse inherited values and edit literal PiMux defaults."""

import argparse
import os
import subprocess

from rich.console import Group
from rich.text import Text

from environment import change, display_value, editable, read_settings, secret, validate_name
from gpu_ui import MUTED_STYLE, TITLE_STYLE, edit_line, input_field, key_hints, run_screen, screen, tr
from inspect_ui import text
from proxy_status import foreground_environment
from proxy_ui import ProxyPanel, masked

PROXY = "·proxy"


class EnvironmentPanel:
    def __init__(self, context=()):
        self.context = context
        self.proxy = ProxyPanel(context)
        self.proxy_active = False
        self.settings = {}
        self.inherited = {}
        self.snapshot = False
        self.integrated = not bool(context)
        self.selected = PROXY
        self.offset = 0
        self.page_size = 1
        self.query = ""
        self.searching = False
        self.editing = False
        self.readonly = False
        self.original = None
        self.fields = ["", ""]
        self.cursors = [0, 0]
        self.focus = 0
        self.reveal = False
        self.error = self.notice = ""

    def refresh(self):
        if self.proxy_active:
            self.proxy.refresh()
            return
        try:
            self.settings = read_settings()
        except (OSError, RuntimeError) as error:
            self.error = str(error)
        self.inherited = dict(os.environ)
        self.snapshot = False
        if self.context:
            self.inherited = {}
            self.snapshot = True
            self.integrated = False
            binary, socket, pane = self.context
            try:
                result = subprocess.run([binary, "-S", socket, "display-message", "-p", "-t", pane,
                                         "#{pane_pid}\t#{@pimux_environment_ready}"], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    pid, _, ready = result.stdout.rstrip("\n").partition("\t")
                    self.inherited = foreground_environment(pid) or {}
                    self.integrated = ready == "on"
                    self.snapshot = True
            except (OSError, subprocess.TimeoutExpired):
                self.inherited = {}
                self.snapshot = True

    def items(self):
        names = sorted(set(self.inherited) | set(self.settings), key=lambda key: (key not in self.settings, key))
        query = self.query.casefold()
        rows = [PROXY] if not query or query in "proxy 网络代理 http https socks" else []
        rows += [name for name in names if query in name.casefold()]
        return rows

    def begin_edit(self, name=None):
        self.original = name
        self.readonly = name is not None and not editable(name)
        value = self.settings.get(name, {}).get("value", self.inherited.get(name, "")) if name else ""
        self.fields = [name or "", value]
        self.cursors = [len(self.fields[0]), len(value)]
        self.focus = 1 if name else 0
        self.editing, self.reveal = True, False
        self.error = self.notice = ""

    def mutate(self, action, value=None):
        try:
            change(self.selected, action, value)
            self.error = ""
            self.notice = self.saved_notice()
            self.refresh()
        except (OSError, RuntimeError, ValueError) as error:
            self.error = str(error)

    def saved_notice(self):
        if not self.integrated:
            return tr("Saved · this older window needs a new shell. Return, then Ctrl-a c opens one.",
                      "已保存 · 这个旧窗口需要新 shell，返回后用 Ctrl-a c 新开窗口即可应用。")
        return tr("Saved · new windows apply automatically; integrated shells apply at the next prompt.",
                  "已保存 · 新窗口自动应用，已集成的 shell 在下次提示符应用。")

    def on_key(self, key):
        if self.proxy_active:
            if self.proxy.on_key(key):
                self.proxy_active = False
                self.refresh()
            return False
        name = getattr(key, "name", None) or key
        if not isinstance(name, str):
            return False
        if self.editing:
            if name == "KEY_ESCAPE" or (self.readonly and name == "KEY_ENTER"):
                self.editing = False
                self.error = ""
            elif name == "KEY_F2":
                self.reveal = not self.reveal
            elif name == "KEY_ENTER":
                try:
                    validate_name(self.fields[0])
                    if self.focus == 0:
                        self.focus = 1
                    else:
                        change(self.fields[0], "set", self.fields[1])
                        self.selected = self.fields[0]
                        self.editing = False
                        self.error = ""
                        self.notice = self.saved_notice()
                        self.refresh()
                except (OSError, RuntimeError, ValueError) as error:
                    self.error = str(error)
            elif name in {"KEY_TAB", "\t"} and not self.original:
                self.focus = 1 - self.focus
            elif not self.readonly or name in {"KEY_LEFT", "KEY_RIGHT", "KEY_HOME", "KEY_END", "\x01", "\x05"}:
                index = self.focus
                self.fields[index], self.cursors[index] = edit_line(self.fields[index], self.cursors[index], name)
            return False
        if self.searching:
            if name == "KEY_ESCAPE":
                self.query, self.searching = "", False
            elif name == "KEY_ENTER":
                self.searching = False
            elif name in {"KEY_BACKSPACE", "\x7f", "\x08"}:
                self.query = self.query[:-1]
            elif len(name) == 1 and name.isprintable():
                self.query += name
            self.offset = 0
            rows = self.items()
            self.selected = rows[0] if rows else ""
            return False
        rows = self.items()
        index = rows.index(self.selected) if self.selected in rows else 0
        if name == "KEY_ESCAPE" and self.query:
            self.query, self.offset = "", 0
        elif name in {"q", "KEY_ESCAPE"}:
            return True
        elif name == "/":
            self.searching = True
        elif name == "n":
            self.begin_edit()
        elif name in {"KEY_UP", "KEY_DOWN", "MOUSE_SCROLL_UP", "MOUSE_SCROLL_DOWN", "KEY_PGUP", "KEY_PGDOWN"}:
            step = {"KEY_UP": -1, "KEY_DOWN": 1, "MOUSE_SCROLL_UP": -3, "MOUSE_SCROLL_DOWN": 3,
                    "KEY_PGUP": -self.page_size, "KEY_PGDOWN": self.page_size}[name]
            if rows:
                self.selected = rows[max(0, min(len(rows) - 1, index + step))]
        elif name == "MOUSE_LEFT":
            _, y = key.mouse_xy
            if 4 <= y < 4 + self.page_size and self.offset + y - 4 < len(rows):
                self.selected = rows[self.offset + y - 4]
                return self.on_key("KEY_ENTER")
        elif name in {"e", "KEY_ENTER"} and rows:
            if self.selected == PROXY:
                self.proxy_active = True
                self.proxy.refresh()
            else:
                self.begin_edit(self.selected)
        elif name == " " and rows:
            if self.selected == PROXY:
                self.proxy_active = True
                self.proxy.refresh()
            elif self.selected in self.settings:
                self.mutate("off" if self.settings[self.selected]["enabled"] else "on")
            else:
                self.mutate("off", self.inherited.get(self.selected, ""))
        elif name == "i" and self.selected in self.settings:
            self.mutate("reset")
        return False

    def render(self, width, height):
        if self.proxy_active:
            return self.proxy.render(width, height)
        heading = text(tr("PiMux · Environment", "PiMux · 环境变量"), TITLE_STYLE)
        subtitle = text(tr("PiMux defaults · changes apply to new commands in integrated shells",
                           "PiMux 默认设置 · 应用于已集成 shell 后续启动的命令"), MUTED_STYLE)
        subtitle.no_wrap, subtitle.overflow = True, "ellipsis"
        body = [heading, subtitle]
        if self.editing:
            body.append(Text(""))
            value_label = tr("Value", "变量值") if self.readonly else tr("Default value", "默认值")
            for index, label in enumerate((tr("Name", "变量名"), value_label)):
                body.append(text(label, "bold #63c5f8" if self.focus == index else MUTED_STYLE))
                value = self.fields[index]
                if index == 1 and not self.reveal and not secret(self.fields[0]):
                    value = masked(value, editing=True) if "://" in value else value
                if self.focus == index:
                    body.append(input_field(value, self.cursors[index], width,
                                            hidden=index == 1 and secret(self.fields[0]) and not self.reveal))
                else:
                    line = text(display_value(self.fields[0], value) if index == 1 else value)
                    line.no_wrap, line.overflow = True, "ellipsis"
                    body.append(line)
                body.append(Text(""))
            if not self.readonly:
                name = self.fields[0]
                current = display_value(name, self.inherited[name], reveal=self.reveal) if name in self.inherited else tr("not set", "未设置")
                body.append(text(tr("Current process: ", "当前进程：") + current, MUTED_STYLE))
            body.append(text(tr("Read only · maintained by the shell or environment tools", "只读 · 由 shell 或环境工具维护") if self.readonly else
                             tr("Values are literal text. Empty values are allowed.", "值按原样保存，不执行 shell 表达式；允许空值。"), MUTED_STYLE))
            hints = [("←→", tr("view", "查看")), ("Esc", tr("back", "返回"))] if self.readonly else [
                ("Enter", tr("next", "下一项") if self.focus == 0 else tr("save", "保存")),
                ("Esc", tr("cancel", "取消"))]
            if self.focus == 1:
                hints.append(("F2", tr("reveal", "显隐")))
        else:
            body.extend([text(tr("Search: ", "搜索：") + self.query + ("▏" if self.searching else "")), Text("")])
            rows = self.items()
            if self.selected not in rows and rows:
                self.selected = rows[0]
            index = rows.index(self.selected) if self.selected in rows else 0
            self.page_size = max(1, height - 7)
            self.offset = max(0, min(self.offset, index))
            if index >= self.offset + self.page_size:
                self.offset = index - self.page_size + 1
            for name in rows[self.offset:self.offset + self.page_size]:
                if name == PROXY:
                    label = tr("Network proxy · open settings", "网络代理 · 打开设置")
                else:
                    record = self.settings.get(name)
                    state = tr("set", "设置") if record and record["enabled"] else tr("off", "停用") if record else tr("inherit", "继承")
                    value = record["value"] if record else self.inherited.get(name, "")
                    label = f"{name}  [{state}]  {display_value(name, value)}"
                line = text((" › " if name == self.selected else "   ") + label)
                line.no_wrap, line.overflow = True, "ellipsis"
                if name == self.selected:
                    line.stylize("bold #63c5f8 on #272b34")
                    line.pad_right(max(0, width - line.cell_len))
                body.append(line)
            if not rows:
                body.append(text(tr("No matching variables", "没有匹配的变量"), MUTED_STYLE))
            hints = [("Enter", tr("done", "完成")), ("Esc", tr("clear", "清除"))] if self.searching else [
                ("/", tr("search", "搜索")), ("Enter", tr("edit", "查看／编辑")), ("n", tr("new", "新增")),
                ("Space", tr("on/off", "启停")), ("i", tr("inherit", "恢复继承")), ("q", tr("back", "返回"))]
            if width < 65 and not self.searching:
                hints = [("/", ""), ("Enter", tr("edit", "编辑")), ("n", "+"), ("Space", ""), ("i", ""), ("q", tr("back", "返回"))]
        explanation = tr("Inherited values: foreground process startup environment.", "继承值来自前台进程的启动环境。") if self.snapshot else tr(
            "Inherited values: environment received by this command.", "继承值来自当前命令收到的环境。")
        message = text(self.error or self.notice or explanation, "red" if self.error else "green" if self.notice else MUTED_STYLE)
        return screen(Group(*body), key_hints(hints), width, height, message=message)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pimux env")
    parser.add_argument("context", nargs="*")
    args = parser.parse_args(argv)
    if len(args.context) not in {0, 3}:
        parser.error("Expected tmux binary, socket and pane")
    view = EnvironmentPanel(args.context)
    return run_screen(view.render, view.on_key, view.refresh, interval=3,
                      can_refresh=lambda: not (view.proxy.editing if view.proxy_active else view.editing or view.searching))


if __name__ == "__main__":
    raise SystemExit(main())
