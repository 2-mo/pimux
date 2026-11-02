# PiMux

A tmux workspace for research and project development.

[简体中文](README.zh-CN.md)

![PiMux session manager: sessions, running programs and directories](docs/screenshots/manager.png)

## Install · Linux

```bash
curl -fsSL https://raw.githubusercontent.com/2-mo/pimux/main/install.sh | bash && export PATH="$HOME/.local/bin:$PATH"
```

## Use

```bash
pimux
```

- Press `n` to create a session; select one and press Enter to open it.
- Click **Env / Proxy / GPU / Ports / Help** at the top. `q` returns.
- Inside a session: press and release `Ctrl-a`, then `h` for the menu or `d` to detach and keep tasks running.

## Update

```bash
pimux update
```

[Full guide](https://github.com/2-mo/pimux/blob/main/docs/guide.md) · [Changelog](CHANGELOG.md) · [Apache-2.0](LICENSE)
