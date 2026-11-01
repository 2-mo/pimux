# Changelog

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
