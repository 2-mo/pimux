# 后台终端管理

[English](agents.md) · [快速开始](README.zh-CN.md)

Codex、Claude、DeepSeek 等能执行 shell 命令的 agent，都可以通过 `pimux tmux 命令 ...` 管理实验终端。会话、窗口名、布局、启动命令、复用和清理由 agent 自行规划；PiMux 在选定的工作空间服务上执行原生 tmux 命令，这些终端也会出现在 PiMux 界面里。

无需交互终端或针对某个模型的额外设置。参数、标准输出、标准错误和原生命令的退出码原样保留。用 `-F` 指定输出格式，`pimux tmux list-commands` 可查看可用命令。

## 查找或创建工作空间

在安装 PiMux 的机器、同一用户下执行。在工作空间之外，默认选择配置的 PiMux 服务；在 PiMux 终端内，使用该终端当前所在的服务。`pimux --system tmux 命令 ...` 明确选择系统 tmux 服务。ID 属于各自的服务，同一任务中的调用应保持服务上下文一致。

```bash
pimux ls
pimux tmux list-sessions -F '#{session_id} #{session_name}'

# 需要新会话时才创建；也可以直接使用已有会话的 ID。
session_id=$(pimux tmux new-session -d -s vision-lab -c "$PWD" -P -F '#{session_id}')
pimux tmux list-windows -t "$session_id" -F '#{window_id} #{window_name} #{window_panes}'
```

下面的名称和组织方式仅作示例。后续操作使用返回的会话（`$…`）、窗口（`@…`）、分屏（`%…`）ID，并在 shell 参数中加引号。`-d` 表示后台创建，不切换用户当前正在看的窗口或分屏。

## 启动、查看与组织实验

需要在实验结束后保留终端输出和退出码时，先为该实验创建占位窗口，单独开启 `remain-on-exit`，再把占位进程替换成实际命令：

```bash
project_dir="$PWD"
window_id=$(pimux tmux new-window -d -t "$session_id:" -n baseline \
    -c "$project_dir" -P -F '#{window_id}' sleep infinity)
pane_id=$(pimux tmux display-message -p -t "$window_id" '#{pane_id}')
pimux tmux set-option -w -t "$window_id" remain-on-exit on
pimux tmux respawn-pane -k -t "$pane_id" -c "$project_dir" python train.py

# 查看输出与状态，无需进入终端或向实验发送按键。
pimux tmux capture-pane -p -t "$pane_id" -S -100
pimux tmux list-panes -s -t "$session_id" \
    -F '#{window_id} #{pane_id} #{pane_current_command} dead=#{pane_dead} exit=#{pane_dead_status}'

# 名称、分屏和布局都由 agent 自行选择。
pimux tmux rename-window -t "$window_id" baseline-v2
pimux tmux split-window -h -d -t "$pane_id" -c "$project_dir" -P -F '#{pane_id}'
pimux tmux select-layout -t "$window_id" tiled
```

`pane_dead=1` 表示保留的分屏进程已退出；tmux 提供退出码时，可从 `pane_dead_status` 读取。实验是否成功仍需要结合命令退出状态、日志和结果判断；shell 空闲或显卡空闲本身不能证明实验完成。

上面的 `respawn-pane -k` 只用于替换刚创建的占位进程。复用已退出的分屏时，使用不带 `-k` 的 `respawn-pane -t "$pane_id" -c "$project_dir" python next_experiment.py`，tmux 会拒绝替换仍在运行的分屏。向已有的空闲 shell 输入命令时，可先用 `send-keys -l -t "$pane_id" '命令文本'` 输入，再单独调用一次 `send-keys -t "$pane_id" Enter`。

## 任务结束后清理

记录本任务创建的窗口 ID。检查实验已完成并保存有用的输出后，agent 可以关闭这些确切的窗口：

```bash
mkdir -p results
pimux tmux capture-pane -p -t "$pane_id" -S - > results/baseline-terminal.log
pimux tmux kill-window -t "$window_id"
pimux tmux list-windows -t "$session_id" -F '#{window_id} #{window_name}'
```

关闭窗口会结束其中所有分屏，并影响共享该窗口的连接。`kill-pane -t "$pane_id"` 只关闭一个分屏，最后一个分屏关闭后窗口也会关闭。保留、复用或清理哪些终端，由 agent 根据任务决定，操作范围是它自己创建或用户指定的 ID。PiMux 不调度实验，也不自动清理空闲终端。

## 可以直接交给 agent 的说明

> 使用 `pimux tmux` 管理这个项目的实验终端。窗口组织方式由你决定；新建前先查看已有窗口，并记录返回的确切 ID。通过终端输出和进程退出状态跟踪实验。适合复用的终端继续使用；结果保存后，关闭本任务中不再需要的窗口，避免越积越多。保留其他项目的终端。
