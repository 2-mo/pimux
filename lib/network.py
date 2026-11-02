# pimux-managed: local IP addresses, Tailscale and subnet routes.
"""Inspect local networking; public egress is queried only on request."""

import argparse
from dataclasses import dataclass
import ipaddress
import json
import os
import shutil
import socket
import subprocess

from gpu_ui import MUTED_STYLE, tr
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


class NetworkView(Document):
    def __init__(self, context=()):
        self.proxy = ProxyPanel(context)
        self.show_all = False
        self.public = ""
        self.public_error = ""
        super().__init__(tr("IP & network", "IP 与网络"), self.load_network, searchable=True,
                         hints=[("a", tr("all", "全部")), ("p", tr("public", "公网"))])

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
        blocks = [[text(socket.gethostname(), "bold #63c5f8"), text(proxy_label + state, MUTED_STYLE),
                   text(public + (self.public_error or self.public or tr("press p to query", "按 p 查询")),
                        "red" if self.public_error else "#9ccf9e" if self.public else MUTED_STYLE)]]
        if tailscale:
            states = {"Running": tr("running", "运行中"), "Stopped": tr("stopped", "已停止"),
                      "NeedsLogin": tr("sign in required", "需要登录"),
                      "NeedsMachineAuth": tr("approval required", "等待授权"), "Starting": tr("starting", "启动中")}
            tail_state = states.get(tailscale["state"], tr("unavailable", "不可见"))
            lines = [text("Tailscale · " + tail_state, "bold #b7a1e8")]
            if tailscale["name"]:
                lines.append(text("  " + tailscale["name"], "#63c5f8"))
            if not tail_names:
                lines.extend(text("  " + str(address), "#d8dce4")
                             for address in sorted(tail_addresses, key=lambda value: (value.version, int(value))))
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
                lines.append(text("  " + (tailscale["name"] or "Tailscale") + " · " + tail_state, MUTED_STYLE))
            for address in addresses:
                value = str(address)
                if address.version == 6 and address.ip.is_link_local:
                    value = f"{address.ip}%{interface.name}/{address.network.prefixlen}"
                line = text(f"  IPv{address.version}  {value}", "#d8dce4")
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
                line = text("  " + str(route.subnet), "#d8dce4")
                line.append("  · " + route.device, style="#63c5f8")
                line.append("  · " + ((tr("via ", "经由 ") + route.gateway) if route.gateway else tr("direct", "直连")), style=MUTED_STYLE)
                line.append("  · " + tr("table ", "路由表 ") + route.table, style=MUTED_STYLE)
                blocks.append(([text(title, "bold #63c5f8")] if first else []) + [line])
                first = False
            if first:
                blocks.append([text(title, "bold #63c5f8"), text(tr("  none", "  无"), MUTED_STYLE)])
        if errors:
            blocks.append([text(" · ".join(errors), "yellow")])
        return blocks

    def on_key(self, key):
        name = getattr(key, "name", None) or key
        if not self.searching and name == "a":
            self.show_all = not self.show_all
            self.offset = 0
            self.refresh()
            return False
        if not self.searching and name == "p":
            self.public = self.public_error = ""
            try:
                self.public = query_public_ip()
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
    parser.add_argument("--all", action="store_true", help=tr("Include loopback, virtual and link-local interfaces", "包括回环、虚拟和链路本网卡"))
    args = parser.parse_args(argv)
    if len(args.context) not in {0, 3}:
        parser.error("Expected tmux binary, socket and pane")
    context = args.context
    if not context and os.environ.get("TMUX") and os.environ.get("TMUX_PANE") and shutil.which("tmux"):
        context = (shutil.which("tmux"), os.environ["TMUX"].split(",", 1)[0], os.environ["TMUX_PANE"])
    view = NetworkView(context)
    view.show_all = args.all
    return view.run(once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
