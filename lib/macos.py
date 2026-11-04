# pimux-managed: bounded, read-only native macOS host inspection.
"""Adapt BSD command output to the existing inspector records.

No shell, elevated privileges, environment inspection, or remote connections.
Process commands from ps are display strings, not lossless argv arrays.
"""

import ipaddress
import re
import subprocess

from gpu_ui import tr


def _read(command, *, empty_status=False):
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                errors="replace", timeout=3, env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(tr("macOS host query failed or timed out: ", "macOS 主机查询失败或超时：") + command[0]) from None
    # lsof returns 1 with no output for an empty selection. Diagnostics, including
    # partial visibility warnings, must never be misreported as an empty result.
    if result.stderr.strip() or (result.returncode and not (
            empty_status and result.returncode == 1 and not result.stdout)):
        raise RuntimeError(tr("macOS host information unavailable: ", "macOS 主机信息不可见：") + command[0])
    return result.stdout


def _lsof_text(value):
    # lsof's field output still escapes backslashes, C whitespace and bytes
    # outside the C locale. Decode exactly once; never interpret a literal
    # backslash sequence twice or treat the result as shell input.
    escapes = {b"\\\\": b"\\", b"\\b": b"\b", b"\\f": b"\f", b"\\r": b"\r", b"\\n": b"\n", b"\\t": b"\t"}
    def decode(match):
        token = match[0]
        return bytes([int(token[2:], 16)]) if token.startswith(b"\\x") else escapes[token]
    return re.sub(rb"\\(?:[\\bfrnt]|x[0-9a-fA-F]{2})", decode, value.encode()).decode(errors="replace")


def _fields(output):
    for field in output.split("\0"):
        # lsof separates process/file records with a newline outside the NUL
        # fields; do not strip whitespace inside a path or process name.
        field = field.lstrip("\n")
        if field:
            yield field[0], _lsof_text(field[1:]) if field[0] in {"c", "n"} else field[1:]


def parse_listeners(output):
    owners = {}
    pid, command = None, ""
    for key, value in _fields(output):
        if key == "p":
            pid = int(value) if value.isdecimal() else None
            command = ""
        elif key == "c":
            command = value
        elif key == "n" and pid is not None:
            _, separator, port = value.rpartition(":")
            if separator and port.isdecimal() and 1 <= int(port) <= 65535:
                owners.setdefault((value, int(port)), set()).add((pid, command))
    return [(address, port, tuple(sorted(pids)))
            for (address, port), pids in sorted(owners.items(), key=lambda item: (item[0][1], item[0][0]))]


def read_listeners():
    return parse_listeners(_read(["/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-F0pcftn"], empty_status=True))


def process_info(pid):
    if not str(pid).isdecimal() or int(pid) <= 0:
        return "", ""
    command, cwd = "", ""
    try:
        command = _read(["/bin/ps", "-p", str(pid), "-o", "command="]).strip()
    except RuntimeError:
        pass  # The process may have exited, or belong to another user.
    try:
        output = _read(["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-F0n"], empty_status=True)
        cwd = next((value for key, value in _fields(output) if key == "n"), "")
    except RuntimeError:
        pass
    return command, cwd


def parse_interfaces(output):
    rows, row = [], None
    for line in output.splitlines():
        header = re.match(r"^(\S+): flags=\w+<([^>]+)>", line)
        if header:
            flags = header[2].split(",")
            row = {"ifname": header[1], "flags": flags, "addr_info": [],
                   "link_type": "loopback" if "LOOPBACK" in flags else ""}
            rows.append(row)
            continue
        parts = line.split()
        if row is None or len(parts) < 4 or parts[0] not in {"inet", "inet6"}:
            continue
        try:
            address = ipaddress.ip_address(parts[1].split("%", 1)[0])
            if parts[0] == "inet":
                mask = parts[parts.index("netmask") + 1]
                if mask.startswith("0x"):
                    mask = str(ipaddress.IPv4Address(int(mask, 16)))
                prefix = ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
            else:
                prefix = int(parts[parts.index("prefixlen") + 1])
            normalized = ipaddress.ip_interface(f"{address}/{prefix}")
        except (ValueError, IndexError):
            continue
        row["addr_info"].append({"family": parts[0], "local": str(normalized.ip), "prefixlen": normalized.network.prefixlen})
    return rows


def read_interfaces():
    return parse_interfaces(_read(["/sbin/ifconfig", "-a"]))


def parse_routes(output, version):
    rows, columns = [], []
    for line in output.splitlines():
        fields = line.split()
        if fields[:2] == ["Destination", "Gateway"]:
            columns = fields
            continue
        if not columns or len(fields) < 4:
            continue
        row = dict(zip(columns, fields))
        flags, device = row.get("Flags", ""), row.get("Netif", "")
        if "U" not in flags or any(flag in flags for flag in "HRB") or not device:
            continue  # Omit host, reject and blackhole routes, as on Linux.
        destination = row["Destination"]
        if destination == "default":
            destination = "0.0.0.0/0" if version == 4 else "::/0"
        try:
            address, slash, prefix = destination.partition("/")
            address = address.split("%", 1)[0]
            if version == 4:
                parts = address.split(".")
                if not slash:
                    prefix = str(len(parts) * 8)
                address = ".".join(parts + ["0"] * (4 - len(parts)))
            elif not slash:
                prefix = "128"
            subnet = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
            if subnet.version != version:
                continue
        except ValueError:
            continue
        gateway = row.get("Gateway", "") if "G" in flags else ""
        rows.append({"dst": str(subnet), "dev": device, "gateway": gateway, "table": "system"})
    return rows


def read_routes(version):
    if version not in (4, 6):
        raise ValueError("IP version must be 4 or 6")
    return parse_routes(_read(["/usr/sbin/netstat", "-rn", "-f", "inet" if version == 4 else "inet6"]), version)
