# Changelog

## 0.11.0

- Keep the normal footer focused on the current directory and `Ctrl-a → d detach`; reveal other shortcuts after pressing Ctrl-a. Copy and manager modes retain their contextual hints.
- Cover quiet/prefix/cancel/detach transitions and long directory paths in both languages and narrow/wide terminals, plus background capture without changing the session's selected window, pane or mode.
- Hand native tmux commands directly to the configured client so cancellation signals reach it, while preserving literal arguments, byte streams, exit status and server selection.

- Preserve tab/newline-containing paths, pane IDs and exit status in window previews and manager search; prefer tmux's native foreground working directory.
- Check the actual configured tmux before changing packages. Offer an APT upgrade only for an unchanged package-owned binary with a sufficient candidate, and require an explicit terminal `y` after showing the command and any sudo use. Keep the tmux minimum at 3.2.
- Reload only the installer's verified server; leave older, replaced or unqueryable servers running unchanged. Protect custom binaries, unrelated clients and existing pane programs.

## 0.10.1

- Accept both ASCII `|` and fullwidth `｜` for left/right splits after Ctrl-a and inside the action menu; keep `v` as the primary shortcut.
- Preserve each alias's original behavior outside PiMux on shared servers, and align fullwidth keys in keyboard help.

## 0.10.0

- Add `pimux tmux COMMAND ...` for background terminal management without an interactive terminal. Preserve native arguments, output and exit status.
- Route backend commands to the configured PiMux server, the current managed workspace or the explicitly selected system server.
- Document agent-directed window creation, naming, splits, output inspection, retained exit state, reuse and cleanup by exact window/pane IDs.

## 0.9.2

- Show new-window, rename and close-pane shortcuts in the normal footer on wide terminals and prioritize them while Ctrl-a is active. Fit prefix hints to the available width and reserve path space from the rendered labels.
- Open the action menu with Workspace expanded so common operations are immediately visible.
- Keep new-session and close hints visible in the manager, including narrow terminals. Name the selected session, window or pane as the close target and show that confirmation is required.
- Update help and screenshots to distinguish closing a pane from detaching and keeping tasks running.

## 0.9.1

- Add Ctrl-a v for left/right splits without Shift; keep the pipe shortcut and show the letter key in the action menu and prefix hints.
- Install both split directions on shared tmux servers while preserving each key's original behavior outside PiMux.
- Reload bindings on the primary PiMux server even when updating from a shared system server; visit each server once.
- Verify mixed nested splits through shortcuts and the action menu, including the geometry of splitting an existing lower pane.

## 0.9.0

- Search all panes by project, window, program or working directory and jump directly to a selected split. Keep window selection independent across clients.
- Add Arrange panes to the home and action menus: equal columns/rows, tiling, swaps and continuous keyboard resizing, with explicit target panes and shared-layout feedback.
- Edit the home search at the cursor with arrows, Home/End, Delete and Ctrl-U. Keep input in character mode between redraws and restore terminal settings when leaving.
- Preserve selected panes when returning from tools, and close only the selected pane after confirmation when acting on pane results.

## 0.8.1

- Make a window's number bold and inverted when a PiMux Bash foreground command exits unsuccessfully. Ctrl-C is treated as cancellation.
- Track exit status per pane: success clears only that pane, and closed panes stop contributing. Shared clients and other splits retain their own reports.
- Show the last command exit code in window previews. Existing Bash shells need a new window after upgrading to load the prompt integration.

## 0.8.0

- Unify the home screen and Ctrl-a h around a navigation tree: Workspace, Resources, Network and Settings, with built-in symbols and existing action keys.
- Show menu and sessions side by side on wide screens; use Tab to switch areas on narrow screens. Support keyboard expansion and mouse selection.
- Select IPs, gateways, CIDRs and MagicDNS names, then copy with y / Enter; Y copies an IP's subnet. Preserve scoped IPv6 addresses and target only the requesting terminal's clipboard.
- Update home screenshots and help for tree navigation; show the default directory footer in the workspace preview.

## 0.7.0

- Add IP and network inspection to the main interface, action menu and optional `pimux ip` shortcut.
- Show IPv4/IPv6 addresses, multiple CIDR subnets and routes across routing tables, with optional Tailscale self addresses and MagicDNS names.
- Keep common interfaces readable; toggle all interfaces with a and query direct public egress only on p. Refreshing local information never polls the public service.
- Fit all six main navigation entries in 40 columns in both languages and preserve the session selection when returning.

## 0.6.5

- Detect external dependency executables even after the launcher defines its `tmux` function, so a missing tmux triggers automatic installation on Debian/Ubuntu.
- Align the fallback proxy glyph with the GPU circles in the README captures using shared font metrics.

## 0.6.4

- Show split workspaces, GPU details, environment defaults and proxy settings alongside the session manager in the README gallery.
- Move the launcher to `bin/`, local installation to `scripts/`, and translated quick start and changelog to `docs/`.
- Keep the public install URL and installed `pimux` command unchanged.

## 0.6.3

- Show an actual main-interface capture in both quick-start READMEs.
- Group runtime modules in `lib/`, theme files in `config/` and maintenance scripts in `scripts/`; update source loading, installation and release packaging together.

## 0.6.2

- Give the main interface distinct colors for sessions, programs, directories, shortcuts and feedback, with a cyan marker and background for the selected row.
- Align window names, running programs and directories in columns; keep the end of long paths visible and show the selected directory in narrow terminals.
- Style the main navigation as clickable buttons and share search fields and bottom action bars with the other PiMux pages.

## 0.6.1

- Put Environment, Proxy, GPU, Ports and Help directly in the main `pimux` interface, with clickable entries and visible action keys.
- Return from each page to the same session selection and search, including when an entry is clicked while searching.
- Keep `pimux env`, `pimux proxy`, `pimux gpu`, `pimux ports` and `pimux help` as optional shortcuts.

## 0.6.0

- Run CI once on main or a pull request; skip tag and documentation-only pushes, cancel superseded runs, and remove brittle layout assertions.
- Add `pimux env` for searchable environment defaults: edit literal values, enable/disable variables, restore inheritance, and open proxy settings from the same page.
- Apply defaults in PiMux Bash shells while preserving startup values, export flags, manual overrides and running programs. Store settings atomically with owner-only access; mask sensitive values by default.
- Replace raw keyboard help with a searchable popup using actual bindings, and display full directory paths in a client-local view.
- Align page titles, popup sizes, bottom action bars and editing controls; support wide-character input and suppress manual-refresh shortcuts while typing.
- Expose closing the selected pane in the menu and help, with Ctrl-a x confirmation that targets the original pane.

## 0.5.1

- Restore the proxy icon in older panes that have no PiMux shell report by inspecting the foreground process's startup environment.
- Keep shell reports authoritative and keep the icon hidden when no proxy is detected or process information is unavailable.
- Show the same detected state in the proxy panel, identifying when it comes from a foreground process.

## 0.5.0

- Add a searchable TCP port inspector with process commands and working directories, available from the menu and `pimux ports [PORT]`.
- Preview window state, retained exit codes and recent output with `d` in the manager, keeping client selection and running panes intact.
- Redesign proxy settings with separate saved and reported states, focused keyboard/mouse actions, inline validation and cancellable address editing.
- Open the proxy panel with `pimux proxy`; retain explicit text output through `pimux proxy show` and noninteractive calls.
- Reuse the private Python runtime for all views and prepare iproute2 automatically when needed.

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
