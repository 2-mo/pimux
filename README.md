# PiMux

A tmux workspace for research and project development.

[简体中文](docs/README.zh-CN.md)

![PiMux workspace: training, logs and a styled shell in split panes, with the current directory, proxy status and GPU activity](docs/screenshots/workspace.png)

## Install · Linux

```bash
curl -fsSL https://raw.githubusercontent.com/2-mo/pimux/main/install.sh | bash && export PATH="$HOME/.local/bin:$PATH"
```

On Debian/Ubuntu, missing tmux and terminal dependencies are installed automatically.

The separate [macOS major-version track](docs/macos.md) provides a native local terminal, one-shot [multi-server CLI snapshots](docs/hosts.md), and explicitly confirmed public-key setup. It reuses discovered VS Code/OpenSSH aliases. There is no unified remote-server TUI, remote session attachment/management, or published Mac installer. Use a reviewed source checkout for this preview; the Linux download command above does not install it.

## Use

```bash
pimux
```

- Press `n` to create a session; `/` searches projects, programs and paths, and Enter jumps to the selected pane.
- Use the grouped menu for **GPU, IP, ports, proxy and settings**. `Tab` switches to it; `q` returns.
- Inside a session: press and release `Ctrl-a`, then `-` / `v` to split top/bottom or left/right, `h` for the menu, or `d` to detach and keep tasks running.
- Let your agent organize experiment terminals with `pimux tmux`: [background management](docs/agents.md).

## Update · Linux

For the Mac source preview, reinstall from the chosen checkout as described in [the Mac guide](docs/macos.md); `pimux update` does not download a Mac release.

```bash
pimux update
```

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
