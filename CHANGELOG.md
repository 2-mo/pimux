# Changelog

## 0.4.1

- Preserve full GPU process paths and show visible launch commands and working directories so Python tasks can be identified.
- Wrap long details and scroll the complete process list with the mouse wheel or Page Up/Down; keep arrow keys for GPU selection.
- Tolerate processes exiting or denying access without interrupting GPU monitoring.

## 0.4.0

- Bundle a standalone version of the pi gpu dashboard: compact GPU cards, utilization curves, memory bars and optional temperature, power and process details.
- Refresh GPU details every second; retain lightweight five-second status circles.
- Select cards with arrows or mouse clicks, navigate with the wheel or Page Up/Down, and press d for details or q/Esc to return.
- Automatically prepare a private, locked Python environment with uv; no RIPO installation or project-environment changes are needed.
- Follow PiMux's English/Chinese preference and restore terminal input, cursor and mouse state when the dashboard closes.

## 0.3.2

- Stabilize isolated keyboard checks by using an outer terminal environment and waiting for the prefix key to be ready.

## 0.3.1

- Copy literal directory paths correctly on tmux versions that escape display output, including directory names containing `$`.

## 0.3.0

- Copy the current directory from the action menu or Ctrl-a y, targeting the requesting terminal's clipboard and tmux buffer.
- Pin/unpin sessions from the menu or with p in the manager. Pins persist by server and session name, and sorting keeps the selected item stable.
- Show a compact connection icon before the GPU circles only when the active pane's shell reports a configured proxy; otherwise hide it without reserving space.
- View and configure proxies through the action menu or `pimux proxy`; enable, disable or restore inherited settings without rewriting system configuration.
- Integrate proxy preferences into PiMux Bash shells, preserving existing prompt hooks, manual exports, bypass lists and running programs.
- Mask proxy credentials in status output and save proxy preferences with owner-only permissions.

## 0.2.1

- Prefill new session names from the current directory; accept with Enter, edit, or clear to cancel.
- Show and search the active pane's foreground program in window listings.
- Highlight the entire selected row and show the selection position and list size.
- Use shorter keyboard and mouse hints in narrow manager windows.

## 0.2.0

- Show a high-contrast prefix badge and common actions while Ctrl-a waits for the next key; Esc cancels.
- Click manager entries to open them, click arrows to expand or collapse sessions, and scroll with the mouse wheel.
- Scroll GPU details with the mouse wheel; restore terminal mouse reporting when a view closes.
- Enable mouse support in managed views on shared tmux servers as well as fresh installations.
- Update with `pimux update` or the action menu, using the existing checksum-verified installer and live reload.

## 0.1.1

- Use `pimux` directly after installation; configure the command path for future Bash and existing Zsh terminals with backups.
- Reuse the current PiMux server automatically when running the short command inside a workspace.
- Refresh helper shortcuts on shared system servers while preserving ordinary sessions and their original key actions.
- Apply reloads to managed sessions without restarting their tasks.

## 0.1.0

Initial standalone release of PiMux — Personal Interactive MUltipleXer.

- Complete purple/cyan tmux theme and styled Starship shell prompt, enabled by default.
- Isolated tmux server, with optional access to existing system sessions.
- Independent window selection for terminals sharing a session.
- Live, literal search across session names, window names and directories.
- Compact grouped GPU utilization circles and a live GPU/process popup on Ctrl-a g.
- English and Simplified Chinese UI.
- Consistent command and keyboard reloads, version reporting, managed-file backups and a scoped uninstaller.
- Checksum-verified release installer and standalone Linux archives.
