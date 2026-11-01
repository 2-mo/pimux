# PiMux

**Personal Interactive MUltipleXer** — your personal terminal workspace, ready to use. Built on tmux.

[简体中文](README.zh-CN.md) · [Download](https://github.com/2-mo/pimux/releases/latest) · [Changelog](CHANGELOG.md)

![PiMux workspace illustration](docs/preview.svg)

A coordinated purple/cyan theme, a useful shell prompt, searchable sessions and compact GPU indicators — installed together. No Python runtime, dotfile editing or special fonts required.

## Install

On Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/2-mo/pimux/main/install.sh | bash
```

The installer verifies the release checksum, installs missing system dependencies through apt on Debian/Ubuntu, installs or reuses [Starship](https://starship.rs/), and sets up the complete workspace in your home directory. Administrator access is only needed when system packages are missing. NVIDIA drivers are optional and are never installed by PiMux.

Open the installed workspace:

```bash
~/.local/bin/pimux
```

Inside PiMux, `pimux` is on PATH automatically. Outside PiMux, use the full path if your shell does not already include `~/.local/bin`.

Alternatively, download and extract `pimux-linux.tar.gz` from [Releases](https://github.com/2-mo/pimux/releases/latest), then run `bash pimux/setup-tmux.sh`. The same installer updates an existing installation and backs up changed managed files.

## Your workspace

- **Ready-made styling.** The tmux theme and Starship prompt are enabled together. The prompt shows the current directory, Git branch, Python environment, time and slow command duration.
- **Independent window selection.** Two terminals can view different windows in the same session while sharing the running programs.
- **Search, then jump.** Open the manager, press `/`, and type a session name, window name or directory. Matches update as you type. Arrows select, Enter opens, Backspace edits, and Esc clears the search. Search is literal and case-insensitive.
- **GPU activity at a glance.** Bold circles show approximate utilization, with four GPUs per group. Press `Ctrl-a g` for live utilization, memory and process details in a popup.
- **English and Chinese.** Open `Ctrl-a h`, choose `Language / 语言`, then select a language. The preference is saved automatically.
- **An isolated tmux server.** Fresh installations use their own `pimux` socket. Your normal tmux configuration and Bash dotfiles are not rewritten. Styled shells load your existing Bash setup, then apply PiMux's prompt inside the workspace.

PiMux is a workspace inside your existing terminal or SSH connection; it is not a terminal emulator. It runs ordinary shell commands and keeps tasks alive when you detach. Closing a shared window or session ends its tasks for every connected terminal; the manager asks before doing so. Server reboots do not preserve running processes.

## Everyday commands

```bash
pimux                 # Session manager; never creates a session implicitly
pimux -n work         # Create or enter a named session
pimux ls              # List sessions, windows and directories
pimux ls project      # Filter the listing
pimux gpu             # Live GPU details
pimux doctor          # Version, tmux, color and clipboard diagnostics
pimux reload          # Reload without restarting tasks
pimux --version
```

Press `Ctrl-a`, release it, then press the action key:

| Key | Action |
|---|---|
| `h` | Action menu |
| `s` / `w` | Session manager / current session's windows |
| `g` | GPU details; `q` or Esc returns |
| `c` / `,` | New window / rename window |
| `1`–`9` / `0` | Select a numbered window |
| `p` / `n` / `l` | Previous / next / last window |
| `L` | Previous session |
| `\|` / `-` | Split left/right / top/bottom |
| Arrow keys | Select a pane |
| `z` | Zoom or restore the pane |
| `[` / `]` | Copy mode / paste tmux's buffer |
| `P` | Full directory path |
| `/` | Keyboard help |
| `r` / `d` | Reload / detach and leave tasks running |

In the manager, `n` creates a session, `x` closes the selected item after confirmation, and `q` returns. The GPU popup refreshes every five seconds; arrows and Page Up/Down scroll, and `r` refreshes immediately. Both popups belong to the current client and do not replace another terminal's application pane.

## GPU circles

`○ ◔ ◑ ◕  ● ○ ◑ ●`

From left to right, circles follow the machine's physical GPU order in `nvidia-smi`. They represent whole-GPU activity, not just your processes. The five fill levels represent utilization below 10%, 10–34%, 35–64%, 65–89%, and 90–100%.

- Gray: low activity and less than 256 MiB of used memory — approximately idle.
- Cyan: computation is active.
- Orange: memory is occupied but computation is low, or a query is unavailable (`?`). Waiting for data can also cause low utilization; this is not a process-health diagnosis.

The status bar refreshes on a five-second timer; window changes and other redraws may update it sooner. Without `nvidia-smi`, the circles disappear automatically. GPU details use the driver's own report, including its process visibility and permissions.

## Compatibility and existing tmux sessions

This release supports Linux with Bash 4+, tmux 3.2+, coreutils, grep, sed, util-linux and the `tmux-256color` terminfo entry. The installer handles dependencies on Debian/Ubuntu. On other Linux distributions, install those prerequisites using your system package manager. macOS and native Windows are not currently supported; Windows users can use a Linux environment through WSL or SSH.

For an existing system tmux session, `pimux --system ls` lists it and `pimux --system -n NAME` enters it. Detach first when switching between tmux servers. Normal PiMux installation does not reload or restyle unmarked sessions on the system server. Explicitly running `pimux --system reload` applies PiMux's theme and bindings to that server.

An optional `~/.config/pimux/runtime.conf` can select an already-installed tmux binary and a different socket. Its three lines are the primary binary's absolute path, the primary socket name, and the system binary's absolute path. This is only needed for an existing parallel tmux installation; fresh installs need no runtime file.

Clipboard transfer uses OSC 52 and depends on the outer terminal. Use `pimux doctor --clipboard`, then paste into a local editor to verify. In VS Code, the terminal's normal right-click menu remains available; PiMux's menu is on `Ctrl-a h`.

## Update and uninstall

Run the install command again to update. It preserves language/runtime preferences and backs up changed managed files. `pimux reload` and `Ctrl-a r` use the same reload path, including local status overrides in connected PiMux views.

```bash
pimux uninstall
```

Uninstall removes only the managed launcher. Your configuration, backups, shared Starship installation and running tasks remain. Management shortcuts need the launcher, so keep it installed while you still need those shortcuts. No personal `.bashrc` or `.tmux.conf` changes need undoing.

## Development

The runtime is Bash. Python and pytest are development tools only, managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m pytest tests/test_pimux.py
bash scripts/package.sh
```

Tests use isolated tmux sockets. Release archives contain only the listed runtime assets and documentation. The theme and shell prompt are shipped alongside the launcher; there is no dependency on a parent project.

Licensed under [Apache-2.0](LICENSE). tmux and Starship are installed separately and retain their own licenses.
