# pimux-managed: local IP addresses, Tailscale and subnet routes.
"""Inspect local networking; public egress is queried only on request."""

import argparse
import base64
from dataclasses import dataclass
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys

from rich.console import Group
from rich.style import Style
from rich.text import Text

from gpu_ui import MUTED_STYLE, TITLE_STYLE, console, key_hints, screen, tr
from inspect_ui import Document, text
from proxy_ui import ProxyPanel


@dataclass(frozen=True)
class Interface:
    name: str
    up: bool
    kind: str
    addresses: tuple[ipaddress.IPv4Interface | ipaddress.IPv6Interface, ...]


@dataclass(frozen=True)
class Route:
    subnet: ipaddress.IPv4Network | ipaddress.IPv6Network
    device: str
    gateway: str
    table: str
    metric: int


def read_json(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=2)
    except FileNotFoundError:
        raise RuntimeError(tr("Network inspection needs ip (iproute2). Run pimux update.",
                              "网络查看需要 ip（iproute2），请运行 pimux update。")) from None
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(tr("Network query failed or timed out; press r to retry.",
                              "网络读取失败或超时，按 r 重试。")) from None
    try:
        if result.returncode:
            raise ValueError
        return json.loads(result.stdout)
    except ValueError:
        raise RuntimeError(tr("Could not read network information.", "无法读取网络信息。")) from None


def parse_interfaces(rows):
    if not isinstance(rows, list):
        raise RuntimeError(tr("Invalid interface information.", "网卡信息格式无效。"))
    interfaces = []
    for row in rows:
        addresses = []
        for item in row.get("addr_info", []):
            if item.get("family") not in {"inet", "inet6"}:
                continue
            try:
                address = ipaddress.ip_interface(f'{item["local"]}/{item["prefixlen"]}')
            except (KeyError, ValueError):
                continue
            if address not in addresses:
                addresses.append(address)
        if addresses:
            kind = row.get("linkinfo", {}).get("info_kind", row.get("link_type", ""))
            interfaces.append(Interface(row.get("ifname", "?"), "UP" in row.get("flags", []), kind,
                                        tuple(sorted(addresses, key=lambda value: (value.version, int(value.ip))))))
    return interfaces


def parse_routes(rows, version):
    if not isinstance(rows, list):
        raise RuntimeError(tr("Invalid route information.", "路由信息格式无效。"))
    routes = set()
    for row in rows:
        table = str(row.get("table", "main"))
        if row.get("type", "unicast") != "unicast" or table in {"local", "255"}:
            continue
        destination = row.get("dst", "default")
        try:
            subnet = ipaddress.ip_network(("0.0.0.0/0" if version == 4 else "::/0")
                                          if destination == "default" else destination, strict=False)
            metric = int(row.get("metric", 0))
        except ValueError:
            continue
        if subnet.is_loopback or subnet.is_link_local or subnet.is_multicast or subnet.prefixlen == subnet.max_prefixlen:
            continue
        for hop in row.get("nexthops") or [row]:
            device = hop.get("dev", row.get("dev", ""))
            if device:
                routes.add(Route(subnet, device, hop.get("gateway", row.get("gateway", "")), table, metric))
    return sorted(routes, key=lambda route: (route.subnet.prefixlen != 0, route.subnet.version,
                                            int(route.subnet.network_address), route.subnet.prefixlen,
                                            route.table, route.metric, route.device, route.gateway))


def read_local():
    interfaces = parse_interfaces(read_json(["ip", "-j", "-d", "address", "show"]))
    routes, errors = [], []
    for version in (4, 6):
        try:
            routes.extend(parse_routes(read_json(["ip", f"-{version}", "-j", "route", "show", "table", "all"]), version))
        except RuntimeError:
            errors.append(tr(f"IPv{version} routes unavailable", f"IPv{version} 路由不可见"))
    return interfaces, routes, errors


def read_tailscale():
    binary = shutil.which("tailscale")
    if not binary:
        return None
    try:
        status = read_json([binary, "status", "--json"])
    except RuntimeError:
        return None
    if not isinstance(status, dict):
        return None
    device = status.get("Self") or {}
    addresses = []
    for value in device.get("TailscaleIPs", status.get("TailscaleIPs", [])) or []:
        try:
            addresses.append(ipaddress.ip_address(value))
        except ValueError:
            continue
    return {"name": str(device.get("DNSName") or device.get("HostName") or "").rstrip("."),
            "state": status.get("BackendState", ""), "addresses": addresses}


def query_public_ip():
    try:
        result = subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", "--noproxy", "*",
             "--connect-timeout", "2", "--max-time", "3", "https://api64.ipify.org"],
            capture_output=True, text=True, timeout=4,
        )
        address = ipaddress.ip_address(result.stdout.strip())
        if result.returncode or not address.is_global:
            raise ValueError
        return str(address)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise RuntimeError(tr("Direct public-IP lookup failed; press p to retry.",
                              "直连公网 IP 查询失败，按 p 重试。")) from None


def copy_token(value, identity, *, display=None, subnet=None, kind="ip"):
    token = text(display or value)
    token.stylize(Style(meta={"copy_id": identity, "copy_value": value,
                             "copy_subnet": subnet or value, "copy_kind": kind}))
    return token


def copy_value(value, context=(), client=""):
    if not context:
        encoded = base64.b64encode(value.encode()).decode()
        sys.stdout.write(f"\033]52;c;{encoded}\a")
        sys.stdout.flush()
        return
    if not client:
        raise RuntimeError(tr("Open IP from the PiMux main interface to target this terminal's clipboard.",
                              "请从 PiMux 主界面打开 IP 页，以定位当前终端的剪贴板。"))
    binary, socket, _ = context
    try:
        result = subprocess.run([binary, "-S", socket, "set-buffer", "-w", "-t", client, "--", value],
                                capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(tr("Could not send the selected value to this terminal.", "无法将所选内容发送到当前终端。")) from None
    if result.returncode:
        raise RuntimeError(tr("The requesting terminal is no longer available.", "请求复制的终端已不可用。"))


class NetworkView(Document):
    def __init__(self, context=(), *, client=""):
        self.proxy = ProxyPanel(context)
        self.client = client
        self.show_all = False
        self.public = ""
        self.public_error = ""
        self.selected = ""
        self.targets = {}
        self.positions = {}
        self.mouse_rows = {}
        self.notice = ""
        self.copy_error = False
        super().__init__(tr("IP & network", "IP 与网络"), self.load_network, searchable=True)

    def load_network(self):
        interfaces, routes, errors = read_local()
        tailscale = read_tailscale()
        self.proxy.refresh()
        tail_addresses = set(tailscale["addresses"]) if tailscale else set()
        tail_names = {interface.name for interface in interfaces
                      if interface.name.startswith("tailscale") or any(value.ip in tail_addresses for value in interface.addresses)}
        default_devices = {route.device for route in routes if route.subnet.prefixlen == 0}
        interfaces.sort(key=lambda interface: (interface.name not in tail_names,
                                               interface.name not in default_devices, not interface.up, interface.name))
        if self.proxy.context:
            state = {"on": tr("configured", "已配置"), "off": tr("not configured", "未配置")}.get(
                self.proxy.observed, tr("not reported", "尚未报告"))
            proxy_label = tr("Foreground process proxy: ", "前台进程代理：") if self.proxy.inferred else tr("Terminal proxy: ", "终端代理：")
        else:
            state = tr("unavailable", "不可见") if self.proxy.error else {
                "on": tr("enabled", "启用"), "off": tr("disabled", "停用"),
                "inherit": tr("inherit startup environment", "继承启动环境")}[self.proxy.mode]
            proxy_label = tr("PiMux proxy preference: ", "PiMux 代理设置：")
        public = tr("Public egress · direct: ", "公网出口 · 直连：")
        public_line = text(public, "#9ccf9e" if self.public else MUTED_STYLE)
        if self.public:
            public_line.append_text(copy_token(self.public, "public"))
        else:
            public_line.append(self.public_error or tr("press p to query", "按 p 查询"),
                               style="red" if self.public_error else MUTED_STYLE)
        blocks = [[text(socket.gethostname(), "bold #63c5f8"), text(proxy_label + state, MUTED_STYLE),
                   public_line]]
        if tailscale:
            states = {"Running": tr("running", "运行中"), "Stopped": tr("stopped", "已停止"),
                      "NeedsLogin": tr("sign in required", "需要登录"),
                      "NeedsMachineAuth": tr("approval required", "等待授权"), "Starting": tr("starting", "启动中")}
            tail_state = states.get(tailscale["state"], tr("unavailable", "不可见"))
            lines = [text("Tailscale · " + tail_state, "bold #b7a1e8")]
            if tailscale["name"]:
                line = text("  ", "#63c5f8")
                line.append_text(copy_token(tailscale["name"], "tailscale-name", kind="name"))
                lines.append(line)
            if not tail_names:
                for address in sorted(tail_addresses, key=lambda value: (value.version, int(value))):
                    line = text("  ", "#d8dce4")
                    line.append_text(copy_token(str(address), f"tailscale:{address}"))
                    lines.append(line)
                blocks.append(lines)
        hidden = 0
        for interface in interfaces:
            addresses = list(interface.addresses)
            if not self.show_all and interface.name not in tail_names:
                if interface.kind in {"loopback", "veth", "dummy"}:
                    hidden += 1
                    continue
                addresses = [value for value in addresses if not value.ip.is_loopback and not value.ip.is_link_local]
            if not addresses:
                hidden += 1
                continue
            label = interface.name + (" · Tailscale" if interface.name in tail_names else "")
            label += " · " + (tr("up", "启用") if interface.up else tr("down", "停用"))
            lines = [text(label, "bold #b7a1e8" if interface.name in tail_names else "bold #63c5f8")]
            if tailscale and interface.name in tail_names:
                line = text("  ", MUTED_STYLE)
                if tailscale["name"]:
                    line.append_text(copy_token(tailscale["name"], f"name:{interface.name}", kind="name"))
                else:
                    line.append("Tailscale")
                line.append(" · " + tail_state)
                lines.append(line)
            for address in addresses:
                value = str(address)
                if address.version == 6 and address.ip.is_link_local:
                    value = f"{address.ip}%{interface.name}/{address.network.prefixlen}"
                plain = value.rsplit("/", 1)[0]
                line = text(f"  IPv{address.version}  ", "#d8dce4")
                line.append_text(copy_token(plain, f"address:{interface.name}:{address}",
                                            display=value, subnet=str(address.network)))
                if address.network.prefixlen != address.max_prefixlen and not address.ip.is_link_local and not address.ip.is_loopback:
                    line.append("  · " + tr("subnet ", "子网 ") + str(address.network), style=MUTED_STYLE)
                lines.append(line)
            blocks.append(lines)
        if hidden and not self.show_all:
            blocks.append([text(tr(f"a shows {hidden} more loopback / virtual / link-local interfaces",
                                   f"按 a 展开另外 {hidden} 张回环、虚拟或链路本网卡"), MUTED_STYLE)])
        for title, default in ((tr("Default routes", "默认路由"), True), (tr("Subnets & routes", "子网与路由"), False)):
            first = True
            for route in routes:
                if (route.subnet.prefixlen == 0) != default:
                    continue
                route_id = f"{route.subnet}:{route.device}:{route.gateway}:{route.table}:{route.metric}"
                line = text("  ", "#d8dce4")
                line.append_text(copy_token(str(route.subnet), f"subnet:{route_id}", kind="subnet"))
                line.append("  · " + route.device, style="#63c5f8")
                if route.gateway:
                    line.append("  · " + tr("via ", "经由 "), style=MUTED_STYLE)
                    line.append_text(copy_token(route.gateway, f"gateway:{route_id}", kind="gateway"))
                else:
                    line.append("  · " + tr("direct", "直连"), style=MUTED_STYLE)
                line.append("  · " + tr("table ", "路由表 ") + route.table, style=MUTED_STYLE)
                blocks.append(([text(title, "bold #63c5f8")] if first else []) + [line])
                first = False
            if first:
                blocks.append([text(title, "bold #63c5f8"), text(tr("  none", "  无"), MUTED_STYLE)])
        if errors:
            blocks.append([text(" · ".join(errors), "yellow")])
        return blocks

    def render(self, width, height):
        rows = [part for line in self.lines()
                for part in line.wrap(console, max(1, width - 1), overflow="fold", no_wrap=False)]
        self.targets, self.positions = {}, {}
        for index, row in enumerate(rows):
            for span in row.spans:
                data = span.style.meta if isinstance(span.style, Style) else {}
                if not data.get("copy_id"):
                    continue
                identity = data["copy_id"]
                self.targets.setdefault(identity, data)
                start = 1 + Text(row.plain[:span.start]).cell_len
                end = 1 + Text(row.plain[:span.end]).cell_len
                self.positions.setdefault(identity, []).append((index, start, end, span.start, span.end))
        if self.selected not in self.targets:
            self.selected = next((identity for identity, data in self.targets.items()
                                  if data["copy_kind"] == "ip"), next(iter(self.targets), ""))
            self.notice = ""
        identities = list(self.targets)
        selected_index = identities.index(self.selected) if self.selected else -1
        self.page_size = max(1, height - 5)
        self.total = len(rows)
        self.offset = max(0, min(self.offset, self.total - self.page_size))
        if self.selected:
            selected_row = self.positions[self.selected][0][0]
            if selected_row < self.offset:
                self.offset = selected_row
            elif selected_row >= self.offset + self.page_size:
                self.offset = selected_row - self.page_size + 1
        heading = text(f"PiMux · {self.title}  [{selected_index + 1}/{len(identities)}]", TITLE_STYLE)
        heading.no_wrap, heading.overflow = True, "ellipsis"
        search = text(tr("Search: ", "搜索：") + self.query + ("▏" if self.searching else ""))
        search.no_wrap, search.overflow = True, "ellipsis"
        body = [heading, search, Text("")]
        self.mouse_rows = {}
        for index in range(self.offset, min(self.total, self.offset + self.page_size)):
            row = rows[index].copy()
            hits = []
            chosen = False
            for identity, positions in self.positions.items():
                for row_index, start, end, first, last in positions:
                    if row_index != index:
                        continue
                    hits.append((start, end, identity))
                    if identity == self.selected:
                        row.stylize(Style(color="#63c5f8", bold=True, dim=False), first, last)
                        chosen = True
            line = text("▌" if chosen else " ", "#63c5f8")
            line.append_text(row)
            if chosen:
                line.pad_right(max(0, width - line.cell_len))
                line.stylize("on #303b4e")
            body.append(line)
            self.mouse_rows[3 + index - self.offset] = hits
        if self.searching:
            hints = [("Enter", tr("done", "完成")), ("Esc", tr("clear", "清除"))]
        elif width < 65:
            hints = [("↑↓", ""), ("y", tr("copy", "复制")), ("/", ""),
                     ("a", tr("all", "全部")), ("p", tr("public", "公网")), ("q", tr("back", "返回"))]
        else:
            hints = [("↑↓", tr("select", "选择")), ("y/Y", tr("copy/subnet", "复制/子网")),
                     ("/", tr("search", "搜索")), ("a", tr("all", "全部")),
                     ("p", tr("public", "公网")), ("r", tr("refresh", "刷新")), ("q", tr("back", "返回"))]
        selected = self.targets.get(self.selected)
        message = text(self.notice or (tr("Selected: ", "已选：") + selected["copy_value"] if selected else
                                      tr("No copyable address", "没有可复制的地址")),
                       "red" if self.notice and self.copy_error else "#9ccf9e" if self.notice else MUTED_STYLE)
        message.no_wrap, message.overflow = True, "ellipsis"
        return screen(Group(*body), key_hints(hints), width, height, message=message)

    def copy_selected(self, subnet=False):
        selected = self.targets.get(self.selected)
        if not selected:
            return
        value = selected["copy_subnet"] if subnet else selected["copy_value"]
        try:
            copy_value(value, self.proxy.context, self.client)
            self.notice = tr("Copied: ", "已复制：") + value
            self.copy_error = False
        except RuntimeError as error:
            self.notice, self.copy_error = str(error), True

    def on_key(self, key):
        name = getattr(key, "name", None) or key
        if not isinstance(name, str):
            return False
        if self.searching:
            return super().on_key(key)
        if name in {"y", "Y", "KEY_ENTER"}:
            self.copy_selected(subnet=name == "Y")
            return False
        identities = list(self.targets)
        if name in {"KEY_UP", "KEY_DOWN", "MOUSE_SCROLL_UP", "MOUSE_SCROLL_DOWN", "KEY_PGUP", "KEY_PGDOWN", "KEY_HOME", "KEY_END"}:
            if identities:
                index = identities.index(self.selected) if self.selected in identities else 0
                steps = {"KEY_UP": -1, "KEY_DOWN": 1, "MOUSE_SCROLL_UP": -3, "MOUSE_SCROLL_DOWN": 3}
                if name in steps:
                    index = max(0, min(len(identities) - 1, index + steps[name]))
                elif name == "KEY_HOME":
                    index = 0
                elif name == "KEY_END":
                    index = len(identities) - 1
                else:
                    current_row = self.positions[identities[index]][0][0]
                    goal = current_row + self.page_size * (-1 if name == "KEY_PGUP" else 1)
                    index = min(range(len(identities)), key=lambda i: abs(self.positions[identities[i]][0][0] - goal))
                self.selected = identities[index]
                self.notice = ""
            return False
        if name == "MOUSE_LEFT":
            x, y = key.mouse_xy
            hits = self.mouse_rows.get(y, [])
            if hits:
                self.selected = next((identity for start, end, identity in hits if start <= x < end), hits[0][2])
                self.notice = ""
            return False
        if not self.searching and name == "a":
            self.show_all = not self.show_all
            self.offset = 0
            self.notice = ""
            self.refresh()
            return False
        if not self.searching and name == "p":
            self.public = self.public_error = ""
            self.notice = ""
            try:
                self.public = query_public_ip()
                self.selected = "public"
            except RuntimeError as error:
                self.public_error = str(error)
            self.query, self.offset = "", 0
            self.refresh()
            return False
        return super().on_key(key)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pimux ip")
    parser.add_argument("context", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--client", default="", help=argparse.SUPPRESS)
    parser.add_argument("--all", action="store_true", help=tr("Include loopback, virtual and link-local interfaces", "包括回环、虚拟和链路本网卡"))
    args = parser.parse_args(argv)
    if len(args.context) not in {0, 3}:
        parser.error("Expected tmux binary, socket and pane")
    context = args.context
    if not context and os.environ.get("TMUX") and os.environ.get("TMUX_PANE") and shutil.which("tmux"):
        context = (shutil.which("tmux"), os.environ["TMUX"].split(",", 1)[0], os.environ["TMUX_PANE"])
    view = NetworkView(context, client=args.client)
    view.show_all = args.all
    return view.run(once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
