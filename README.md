# PiMux

A tmux workspace for research and project development.

[简体中文](docs/README.zh-CN.md)

![PiMux workspace: training, logs and a styled shell in split panes, with prefix-key hints and GPU activity](docs/screenshots/workspace.png)

## Install · Linux

```bash
curl -fsSL https://raw.githubusercontent.com/2-mo/pimux/main/install.sh | bash && export PATH="$HOME/.local/bin:$PATH"
```

On Debian/Ubuntu, missing tmux and terminal dependencies are installed automatically.

## Use

```bash
pimux
```

- Press `n` to create a session; select one and press Enter to open it.
- Use the grouped menu for **GPU, IP, ports, proxy and settings**. `Tab` switches to it; `q` returns.
- Inside a session: press and release `Ctrl-a`, then `h` for the menu or `d` to detach and keep tasks running.

## Update

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
