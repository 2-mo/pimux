# Background terminal management

[简体中文](agents.zh-CN.md) · [Quick start](../README.md)

Codex, Claude, DeepSeek or any other agent that can run shell commands can use `pimux tmux COMMAND ...` to manage experiment terminals. The agent chooses sessions, window names, layouts, commands, reuse and cleanup. PiMux runs the native tmux commands on the selected workspace server; the same terminals are visible in the PiMux interface.

No interactive terminal or model-specific setup is required. Arguments, standard input/output/error and the native command's exit status are preserved. The launcher hands control directly to the native tmux client, so cancellation signals reach that client rather than leaving it waiting behind a wrapper. `-F` controls the output format; `pimux tmux list-commands` lists available commands.

## Find or create a workspace

Run commands on the machine and user account where PiMux is installed. Outside a workspace, the configured PiMux server is selected. Inside a PiMux terminal, its current server is selected. `pimux --system tmux COMMAND ...` explicitly selects the system tmux server. IDs belong to that server; keep the same server context throughout a task.

```bash
pimux ls
pimux tmux list-sessions -F '#{session_id} #{session_name}'

# Create only when the agent needs a new session; otherwise use an existing ID.
session_id=$(pimux tmux new-session -d -s vision-lab -c "$PWD" -P -F '#{session_id}')
pimux tmux list-windows -t "$session_id" -F '#{window_id} #{window_name} #{window_panes}'
```

Names and organization below are examples. Use returned session (`$…`), window (`@…`) and pane (`%…`) IDs for later actions; quote them as shell arguments. `-d` creates a terminal without changing the user's active window or pane.

## Read panes without taking over

Use native formats for a machine-readable inventory and capture a specific pane without attaching, switching focus, entering copy mode or injecting keys:

```bash
pimux tmux list-panes -a \
    -F '#{session_id} #{window_id} #{pane_id} active=#{pane_active} dead=#{pane_dead}'
pimux tmux capture-pane -p -J -t "$pane_id" -S -100
```

The inventory above uses IDs and numeric flags. `active` is tmux's selection state, not ownership or command completion. Names, commands and paths are free text; if adding them with `-F`, choose a format your parser handles without splitting on arbitrary whitespace. Independent PiMux views can link the same window, so an all-session listing may repeat pane IDs. Keep the session/window associations, but deduplicate by pane ID before acting once per underlying pane.

`-J` joins wrapped lines. A capture is a snapshot of the pane and available scrollback, not a durable log or proof that its command finished. Use the program's exit state and its own outputs when checking completion. Cancelling a reading/waiting tmux client does not cancel a program running inside a pane.

## Start, inspect and organize experiments

To retain an experiment's output and exit status, first create its own placeholder window, enable `remain-on-exit` for that window, then replace the placeholder with the actual command:

```bash
project_dir="$PWD"
window_id=$(pimux tmux new-window -d -t "$session_id:" -n baseline \
    -c "$project_dir" -P -F '#{window_id}' sleep infinity)
pane_id=$(pimux tmux display-message -p -t "$window_id" '#{pane_id}')
pimux tmux set-option -w -t "$window_id" remain-on-exit on
pimux tmux respawn-pane -k -t "$pane_id" -c "$project_dir" python train.py

# Inspect without attaching or sending keys to the experiment.
pimux tmux capture-pane -p -t "$pane_id" -S -100
pimux tmux list-panes -s -t "$session_id" \
    -F '#{window_id} #{pane_id} #{pane_current_command} dead=#{pane_dead} exit=#{pane_dead_status}'

# Names, splits and layouts remain the agent's choices.
pimux tmux rename-window -t "$window_id" baseline-v2
pimux tmux split-window -h -d -t "$pane_id" -c "$project_dir" -P -F '#{pane_id}'
pimux tmux select-layout -t "$window_id" tiled
```

`pane_dead=1` means the retained pane's process has exited; `pane_dead_status` is its exit code when tmux provides it. Experiment success still comes from the command's exit status and the agent's checks of logs and results. An idle shell or an unused GPU alone does not establish completion.

Use `respawn-pane -k` above only for the newly created placeholder. To reuse a retained, exited pane, run `respawn-pane -t "$pane_id" -c "$project_dir" python next_experiment.py` without `-k`; tmux refuses to replace a live pane. To send a command to an existing idle shell, send the text with `send-keys -l -t "$pane_id" 'command text'`, then send `Enter` in a separate call.

## Close windows when the task is done

Keep IDs for the windows created for the task. Once the agent has checked completion and saved useful output, it can close precisely those windows:

```bash
mkdir -p results
pimux tmux capture-pane -p -t "$pane_id" -S - > results/baseline-terminal.log
pimux tmux kill-window -t "$window_id"
pimux tmux list-windows -t "$session_id" -F '#{window_id} #{window_name}'
```

Closing a window terminates all its panes and affects every client sharing it. `kill-pane -t "$pane_id"` closes just one pane; closing the last pane also closes the window. The agent chooses what to retain, reuse or close, targeting its own or explicitly assigned IDs. PiMux does not schedule experiments or automatically clean up idle terminals.

## Instructions you can give your agent

> Use `pimux tmux` to manage this project's experiment terminals. Choose the window organization yourself, check existing windows before creating more, and keep the exact IDs returned. Inspect output and process exit status to track progress. Reuse completed terminals where useful; after saving results, close task windows that are no longer needed so they do not accumulate. Keep other projects' terminals intact.
