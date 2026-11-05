# PiMux

A tmux workspace for research and project development.

[简体中文](docs/README.zh-CN.md)

![PiMux workspace: training, logs and a styled shell in split panes, with the current directory, proxy status and GPU activity](docs/screenshots/workspace.png)

## Install · Linux

```bash
curl -fsSL https://raw.githubusercontent.com/2-mo/pimux/main/install.sh | bash && export PATH="$HOME/.local/bin:$PATH"
```

On Debian/Ubuntu, missing tmux and terminal dependencies are installed automatically.

## Install · macOS beta

PiMux **1.0.0-beta.1** is a prerelease for Apple silicon on macOS 15 or newer. Linux **v0.11.0** remains the stable/latest release; the Linux installer above does not install the Mac beta.

```sh
brew tap 2-mo/pimux https://github.com/2-mo/pimux
brew trust --formula 2-mo/pimux/pimux-preview
brew install 2-mo/pimux/pimux-preview
pimux
```

The [Mac beta](docs/macos.md) provides a native local terminal and local inspectors, plus experimental [multi-server CLI snapshots](docs/hosts.md) using discovered VS Code/OpenSSH aliases. Public-key setup requires explicit confirmation. A unified multi-server TUI and remote session attachment/management are deferred. Intel Macs are not validated.

## Use

```bash
pimux
```

- Press `n` to create a session; `/` searches projects, programs and paths, and Enter jumps to the selected pane.
- Use the grouped menu for **GPU, IP, ports, proxy and settings**. `Tab` switches to it; `q` returns.
- Inside a session: press and release `Ctrl-a`, then `-` / `v` to split top/bottom or left/right, `h` for the menu, or `d` to detach and keep tasks running.
- Let your agent organize experiment terminals with `pimux tmux`: [background management](docs/agents.md).

## Terminal contrast

PiMux uses your terminal’s normal foreground when its background is unknown, so light and dark profiles both stay readable. Outside tmux, `auto` also accepts a conventional `COLORFGBG` light/dark palette hint; this is not an exact background measurement. Inside tmux that hint is ignored because the server may have inherited it from a different client. No terminal queries are sent and no keyboard input is consumed.

- `pimux theme` shows the preference, resolved palette and source.
- `pimux theme light` or `pimux theme dark` saves an explicit palette; `pimux theme auto` restores automatic/default-foreground behavior.
- `PIMUX_THEME=light pimux` overrides the saved preference for that process (`auto` and `dark` also work).

Preferences are saved in `~/.config/pimux/theme`. Reopen the manager or popup to apply changes; sessions and running tasks are not restarted. All PiMux views share the palette. `NO_COLOR` keeps selection emphasis without colored text. The tmux status bar retains its paired dark background and readable foreground.

## Update

Linux:

```bash
pimux update
```

For the Mac beta, use `brew update && brew upgrade 2-mo/pimux/pimux-preview`; uninstall with `brew uninstall 2-mo/pimux/pimux-preview`. See the [Mac guide](docs/macos.md) for runtime and session caveats.

## See it in action

Demo workspace and sample GPU telemetry.

**Find windows by project, command or path; keep tools in one menu.**

![Session manager with searchable sessions, running programs and directories](docs/screenshots/manager.png)

**Spot free GPUs and inspect full process commands.**

![GPU utilization, memory, history and process command details](docs/screenshots/gpu.png)

**Save environment defaults; keep sensitive values masked.**

![Environment defaults, inherited values and a masked token](docs/screenshots/environment.png)

**Enable, disable or edit your proxy in one place.**

![Proxy settings showing the saved address, terminal state and available actions](docs/screenshots/proxy.png)

[Full guide](https://github.com/2-mo/pimux/blob/main/docs/guide.md) · [Changelog](docs/CHANGELOG.md) · [Apache-2.0](LICENSE)
