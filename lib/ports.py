# pimux-managed: standalone port inspection adapted from RIPO pi host (Apache-2.0).
"""Inspect TCP listeners without changing services or requiring a project."""

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import subprocess
import sys

import macos

from gpu_ui import MUTED_STYLE, tr
from inspect_ui import Document, text


@dataclass(frozen=True)
class Listener:
    address: str
    port: int
    owners: tuple[tuple[int, str], ...]


def parse_listeners(output):
    listeners = []
    for line in output.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) < 5:
            continue
        _, separator, port = fields[3].rpartition(":")
        if not separator or not port.isdecimal():
            continue
        owners = re.findall(r'\("([^\"]+)",pid=(\d+)', fields[5] if len(fields) > 5 else "")
        listeners.append(Listener(fields[3], int(port), tuple((int(pid), name) for name, pid in owners)))
    return sorted(listeners, key=lambda row: (row.port, row.address))


def list_listeners():
    if sys.platform == "darwin":
        return [Listener(*row) for row in macos.read_listeners()]
    try:
        result = subprocess.run(["ss", "-H", "-ltnp"], capture_output=True, text=True, errors="replace", timeout=3)
    except FileNotFoundError:
        raise RuntimeError(tr("Port inspection needs ss (iproute2). Run pimux update.",
                              "端口查看需要 ss（iproute2），请运行 pimux update。")) from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(tr("Port query timed out; press r to retry.", "端口查询超时，按 r 重试。")) from None
    if result.returncode:
        raise RuntimeError(tr("Could not read listening ports.", "无法读取监听端口。"))
    return parse_listeners(result.stdout)


def process_info(pid):
    if sys.platform == "darwin":
        return macos.process_info(pid)
    directory = Path(f"/proc/{pid}")
    try:
        argv = (directory / "cmdline").read_bytes().removesuffix(b"\0").split(b"\0")
        command = shlex.join(arg.decode(errors="replace") for arg in argv) if any(argv) else ""
    except OSError:
        command = ""
    try:
        cwd = str((directory / "cwd").readlink())
    except OSError:
        cwd = ""
    return command, cwd


def port_blocks(port=None):
    listeners = [row for row in list_listeners() if port is None or row.port == port]
    if not listeners:
        label = tr("No visible TCP listeners", "没有可见的 TCP 监听") if sys.platform == "darwin" else tr("No TCP listeners", "没有 TCP 监听")
        return [[text(label + (f" · {port}" if port else ""), MUTED_STYLE)]]
    blocks, processes = [], {}
    if sys.platform == "darwin":
        blocks.append([text(tr("Only listeners visible to this user are shown.", "仅显示当前用户有权限查看的监听端口。"), MUTED_STYLE)])
    for row in listeners:
        lines = [text(f"⛓  {row.address}", "bold #63c5f8")]
        if not row.owners:
            lines.append(text(tr("  Process ownership is not visible to this user.", "  当前权限无法查看进程归属。"), MUTED_STYLE))
        for pid, name in row.owners:
            if pid not in processes:
                processes[pid] = process_info(pid)
            command, cwd = processes[pid]
            lines.append(text(f"  PID {pid} · {name}"))
            lines.append(text(tr("  Command: ", "  命令：") + (command or tr("exited or unavailable", "已退出或不可见")), MUTED_STYLE))
            lines.append(text(tr("  Cwd: ", "  目录：") + (cwd or tr("unavailable", "不可见")), MUTED_STYLE))
        blocks.append(lines)
    return blocks


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pimux ports", description=tr("Inspect local TCP listeners", "查看本机 TCP 监听端口"))
    parser.add_argument("port", nargs="?", type=int)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error(tr("Port must be between 1 and 65535", "端口应在 1–65535 之间"))
    return Document(tr("TCP ports", "TCP 端口"), lambda: port_blocks(args.port), searchable=True).run(once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
