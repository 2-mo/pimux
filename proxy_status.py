# pimux-managed: read-only proxy detection for panes without a shell report.
"""Read the foreground process's startup environment without printing addresses."""

import sys
from pathlib import Path

PROXY_KEYS = {b"http_proxy", b"https_proxy", b"all_proxy", b"HTTP_PROXY", b"HTTPS_PROXY", b"ALL_PROXY"}


def process_proxy_state(pane_pid):
    try:
        pid = int(pane_pid)
        if pid <= 0:
            return ""
        pane = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        foreground = int(pane[5])
        if foreground <= 0 or pane[4] == "0":
            return ""
        directory = Path(f"/proc/{foreground}")
        process = (directory / "stat").read_text().rsplit(")", 1)[1].split()
        # The group must still belong to this pane's session and terminal.
        if process[2] != str(foreground) or process[3:5] != pane[3:5] or process[0] == "Z":
            return ""
        environment = (directory / "environ").read_bytes()
    except (OSError, ValueError, IndexError):
        return ""
    for entry in environment.split(b"\0"):
        key, separator, value = entry.partition(b"=")
        if separator and key in PROXY_KEYS and value:
            return "on"
    return "off"


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        return 2
    if process_proxy_state(args[0]) == "on":
        print("#[fg=#63c5f8]#[bold]⛓︎#[default] ", end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
