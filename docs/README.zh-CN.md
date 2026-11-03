# PiMux

面向科研与项目开发的 tmux 工作台。

[English](../README.md)

![PiMux 工作区：训练、日志与终端分屏，底部显示当前目录、代理状态和显卡活动](screenshots/workspace.png)

## 安装 · Linux

```bash
curl -fsSL https://raw.githubusercontent.com/2-mo/pimux/main/install.sh | bash && export PATH="$HOME/.local/bin:$PATH"
```

Debian/Ubuntu 会自动补齐 tmux 等终端依赖。

## 使用

```bash
pimux
```

- 按 `n` 新建会话；`/` 按项目、程序或目录搜索分屏，Enter 直达。
- 通过树形菜单找到**显卡、IP、端口、代理和设置**；`Tab` 切换区域，`q` 返回。
- 进入会话后，先按并松开 `Ctrl-a`，再按 `-` 上下分屏、`v` 左右分屏、`h` 打开菜单、`d` 离开并保留任务。

## 更新

```bash
pimux update
```

## 看看怎么用

演示工作区与示例显卡数据。

**按项目、程序或目录找窗口，常用工具集中在树形菜单。**

![会话管理：搜索会话、运行程序与项目目录](screenshots/manager.png)

**快速找空卡，查看显存与完整进程命令。**

![显卡详情：利用率、显存、变化趋势和进程命令](screenshots/gpu.png)

**统一设置环境变量，敏感值默认遮蔽。**

![环境管理：默认值、继承值和遮蔽的令牌](screenshots/environment.png)

**在一个页面开启、关闭或修改代理。**

![代理管理：保存的地址、当前终端状态与操作入口](screenshots/proxy.png)

[完整说明](guide.zh-CN.md) · [更新记录](CHANGELOG.md) · [Apache-2.0](../LICENSE)
