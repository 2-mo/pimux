# PiMux

**Personal Interactive MUltipleXer · 个人交互式终端复用器**

开箱即用的个人终端工作空间，基于 tmux。

[English](README.md) · [下载](https://github.com/2-mo/pimux/releases/latest) · [更新记录](CHANGELOG.md)

![PiMux 工作空间示意](docs/preview.svg)

柔紫与青蓝的终端主题、完整目录和 Git 提示符、可搜索的会话管理、轻巧的显卡圆圈，一次安装全部配好。运行时不需要 Python，也不用手改 dotfiles 或安装特殊字体。

## 一次安装

在 Linux 服务器或终端执行：

```bash
curl -fsSL https://raw.githubusercontent.com/2-mo/pimux/main/install.sh | bash
```

安装器下载并校验发布包，在 Debian/Ubuntu 上通过 apt 补齐缺失的系统依赖，安装或复用 Starship，并将整套工具放入用户目录。仅当系统依赖缺失时需要管理员权限；不会安装显卡驱动。

安装后进入：

```bash
~/.local/bin/pimux
```

PiMux 内会自动将命令加入 PATH。外部 shell 如果尚未包含 `~/.local/bin`，用上面的完整路径即可，无需修改设置。

也可以从 [Releases](https://github.com/2-mo/pimux/releases/latest) 下载并解压 `pimux-linux.tar.gz`，运行 `bash pimux/setup-tmux.sh`。更新时重新运行相同安装命令，已有的受管文件发生变化时先备份。

## 默认就有

- **统一外观**：终端栏和 Starship 提示符一起启用，展示目录、Git 分支、Python 环境、时间与慢命令耗时。
- **独立切换窗口**：两个终端可以进入同一会话的不同窗口，共享运行中的程序，不互相抢当前窗口。
- **会话搜索**：管理列表按 `/`，按名称或目录实时筛选。方向键选择、Enter 直接进入、Backspace 删除输入、Esc 清空。搜索不区分大小写，按字面匹配。
- **显卡概况与详情**：圆圈表示大概利用率，每四张卡一组；`Ctrl-a g` 打开实时利用率、显存和占用进程详情，`q` 返回。
- **中英切换**：`Ctrl-a h` 打开菜单，选择 `Language / 语言`。偏好会自动保存。
- **独立工作空间**：首次安装默认使用自己的 tmux 服务，不改写原有 `.tmux.conf` 或 `.bashrc`。PiMux 内的 Bash 会加载用户原设置，然后应用自带提示符。

PiMux 在现有终端或 SSH 连接中工作，不是终端模拟器。离开连接会保留任务；关闭共享窗口或会话会影响所有连接，管理列表会要求确认。机器重启后不能恢复原进程。

## 日常使用

```bash
pimux                 # 管理列表，不自动新建会话
pimux -n work         # 创建或进入命名会话
pimux ls              # 列出会话、窗口和目录
pimux ls project      # 筛选列表
pimux gpu             # 显卡详情
pimux doctor          # 版本、颜色、剪贴板诊断
pimux reload          # 热重载，不重启任务
pimux --version
```

先按 `Ctrl-a` 并松开，再按操作键：

| 键 | 操作 |
|---|---|
| `h` | 操作菜单 |
| `s` / `w` | 管理列表 / 当前会话窗口列表 |
| `g` | 显卡详情，`q` 或 Esc 返回 |
| `c` / `,` | 新建窗口 / 重命名 |
| `1`–`9` / `0` | 选择窗口 |
| `p` / `n` / `l` | 上一个 / 下一个 / 上次使用的窗口 |
| `L` | 上次使用的会话 |
| `\|` / `-` | 左右 / 上下分屏 |
| 方向键 | 选择 pane |
| `z` | 放大 / 恢复 pane |
| `[` / `]` | 复制模式 / 粘贴 tmux 缓冲区 |
| `P` / `/` | 完整路径 / 快捷键帮助 |
| `r` / `d` | 重载 / 离开并保留任务 |

管理列表中按 `n` 新建，`x` 关闭选中项（需确认），`q` 返回。显卡弹窗每五秒刷新，方向键和 Page Up/Down 滚动，`r` 立即刷新。管理列表和显卡详情只在当前客户端弹出，不占用其他终端的应用 pane。

## 显卡圆圈

`○ ◔ ◑ ◕  ● ○ ◑ ●`

从左到右对应 `nvidia-smi` 的物理卡顺序，反映整张卡的负载。填充程度依次表示 `<10%`、`10–34%`、`35–64%`、`65–89%`、`90–100%` 利用率。

- 灰色：计算很低且显存使用低于 256 MiB，大致空闲。
- 青色：正在计算。
- 橙色：显存已占用但计算很低；读取不可用时显示 `?`。

等待数据也可能使利用率很低，圆圈不能单独判断程序故障。状态栏每五秒定时刷新，切换窗口等重绘也可能提前更新。没有 `nvidia-smi` 时自动隐藏圆圈；详情使用驱动提供的报告，进程可见范围由驱动和权限决定。

## 环境和已有会话

支持 Linux，要求 Bash 4+、tmux 3.2+、coreutils、grep、sed、util-linux，以及 `tmux-256color` terminfo。Debian/Ubuntu 上由安装器补齐；其他 Linux 发行版通过系统包管理器安装这些依赖。暂不支持 macOS 或原生 Windows；Windows 可通过 WSL 的 Linux 环境或 SSH 使用。

`pimux --system ls` 查看系统 tmux 会话，`pimux --system -n NAME` 进入已有会话。跨服务切换前先离开当前连接。普通安装不会重载系统服务中未标记为 PiMux 的会话；显式运行 `pimux --system reload` 会将主题和绑定应用到该服务。

已有并行 tmux 安装可以在 `~/.config/pimux/runtime.conf` 指定主程序绝对路径、主 socket 名称、系统程序绝对路径，每项一行。首次安装不需要这个文件。

剪贴板采用 OSC 52，实际支持取决于外层终端。用 `pimux doctor --clipboard` 后在本地编辑器粘贴验证。VS Code 原有的右键菜单保留，PiMux 菜单用 `Ctrl-a h` 打开。

## 更新与卸载

更新时重新运行安装命令。语言和运行配置会保留，变化的受管文件会先备份。`pimux reload` 与 `Ctrl-a r` 使用相同的重载路径，也会更新已连接视图中的局部状态栏配置。

```bash
pimux uninstall
```

卸载只移除受管的命令入口，保留设置、备份、共用的 Starship 安装和正在运行的任务。管理快捷键依赖命令入口，仍需要这些快捷键时请保留安装。由于没有改写个人 `.bashrc` 或 `.tmux.conf`，无需手动撤销配置引用。

## 开发

运行时为 Bash，Python/pytest 只用于开发检查，使用 uv 管理：

```bash
uv sync
uv run python -m pytest tests/test_pimux.py
bash scripts/package.sh
```

测试使用隔离的 tmux socket。发布包只包含明确列出的运行文件与文档，不依赖其他项目。

采用 [Apache-2.0](LICENSE) 许可证；tmux 和 Starship 独立安装，保留各自的许可证。
