# PiMux

面向科研与项目开发的 tmux 工作台。

[English](README.md)

## 安装 · Linux

```bash
curl -fsSL https://raw.githubusercontent.com/2-mo/pimux/main/install.sh | bash && export PATH="$HOME/.local/bin:$PATH"
```

## 使用

```bash
pimux
```

- 按 `n` 新建会话，选中后按 Enter 进入。
- 顶部点击 **环境 / 代理 / 显卡 / 端口 / 帮助**，按 `q` 返回。
- 进入会话后，先按并松开 `Ctrl-a`，再按 `h` 打开菜单、`d` 离开并保留任务。

## 更新

```bash
pimux update
```

[完整说明](https://github.com/2-mo/pimux/blob/main/docs/guide.zh-CN.md) · [更新记录](CHANGELOG.md) · [Apache-2.0](LICENSE)
