# macOS major-version track

PiMux's Mac direction is one Mac managing several servers: host identity, connection state, terminal sessions and host resources. It is server management, not experiment management. This track is independent of the Linux 0.10.x fixes. This foundation does not bump the release version or publish a Mac archive.

## Milestone 1: native read-only host inspectors

The Python inspection views now select a native macOS adapter for local TCP listeners, process command display and working directories, interface addresses, and IPv4/IPv6 routes. The adapter uses `/usr/sbin/lsof`, `/bin/ps`, `/sbin/ifconfig` and `/usr/sbin/netstat`. Queries use argument arrays, a fixed locale, and a three-second timeout per command. They do not request administrator privileges or change services, interfaces, routes or configuration.

Use an existing Python 3.10+ and uv in a source checkout:

```sh
uv run --locked python lib/ports.py --once
uv run --locked python lib/ports.py 8888 --once
uv run --locked python lib/network.py --once
uv run --locked python lib/gpu.py --once
```

These are development entry points. Use the network snapshot (`--once`); its existing interactive proxy editor still depends on the unsupported Bash launcher. Missing NVIDIA tools produce an explicit unavailable-telemetry message, not a claim that the Mac has no GPU. Apple GPU telemetry is not implemented. The GPU command returns a nonzero status for unavailable telemetry.

Port discovery is limited to processes visible to the current user. An empty lsof selection is distinct from a failed query; diagnostic warnings fail visibly rather than showing an incomplete snapshot as complete. Process command text from `ps` is for display, not a lossless argument list. A process that exits or becomes inaccessible has unavailable command/directory data. Route snapshots retain separate defaults and scoped IPv6 gateways; host, rejected, blackhole, loopback, link-local and multicast routes are omitted by the existing view's subnet model. macOS uses the `system` routing-table label, without claiming Linux policy-routing tables or route priorities.

The lsof adapter decodes UTF-8 byte escapes, escaped backslashes and C whitespace once. Ambiguous caret notation for other control characters remains a display representation; working-directory text is not used to execute commands or select targets.

The Linux providers retain `ss`, `ip -j` and `/proc`. The native adapter emits the existing inspector records; this is a small platform boundary, not a rewrite of the terminal/session engine. The installer copies the new module for Linux installations too, so these imports also work after installation.

## Explicit limits

The native Mac terminal is **not supported yet**. `install.sh` and direct `scripts/setup-tmux.sh` execution reject macOS before downloads or home-directory writes. Apple Bash 3.2 gets an actionable runtime error before loading libraries. A newer Bash alone does not make the launcher compatible.

Remaining dependencies are substantive:

| Area | Current requirement / next work |
| --- | --- |
| Shell runtime | Associative arrays, `mapfile`, lowercase expansion and `declare -gA` require Bash >=4.2. Select and pin an explicit modern Bash runtime for the launcher, tmux helpers and child shells. Do not silently use Apple Bash. |
| Paths and utilities | `readlink -m`, GNU checksum/archive flags and `timeout` need tested replacements or explicit GNU dependencies. Recent macOS `readlink -f` availability does not cover all uses. |
| Locking | Shell `flock` calls need an owned, consistently used implementation; Python already uses `fcntl.flock`. Do not replace advisory locks with unsafe lock-file existence checks. |
| tmux and installation | Validate the selected native tmux runtime and terminfo, shell startup behavior, configuration preservation, installation/update/uninstall and isolated sockets. No native tmux executable was available during this milestone. |
| Process environment | Linux `/proc` foreground-environment inference has no macOS implementation; report unknown rather than infer proxy state. |
| GPU | NVIDIA-only collection, with explicit unavailability on this Mac; Apple GPU metrics are out of scope. |
| Servers | No host inventory, SSH transport abstraction, remote snapshot protocol or cross-server aggregation yet. An SSH shell into a server is not multi-server management. |

The proposed runtime direction is a modern Bash dependency with narrow platform adapters, preserving the established Linux shell/session engine. A Bash 3.2 rewrite would touch most stateful shell code and does not belong in this bounded milestone. GNU tools should be added only for remaining gaps, not to emulate Linux process/network tools on macOS. No global tools were installed for this change.

## Next milestones and acceptance gates

1. **Local terminal runtime:** explicitly choose modern Bash/tmux and locking/path helpers; validate install/update/uninstall under an isolated HOME, detached sessions, split windows, keyboard/mouse actions, multi-client targeting and native passthrough on macOS. Retain Ubuntu 24.04/tmux 3.4 regressions. This is the next prerequisite for an end-user Mac build.
2. **Host inventory and read-only aggregation:** add explicit host IDs and opt-in server entries, reuse system SSH configuration/agent without copying private keys, verify host keys, report connection state/timeouts per host, and introduce versioned structured snapshots with capability flags. Aggregate at least two isolated test servers on one Mac, including unavailable-host handling and duplicate session names. Keep local and remote identities visible.
3. **Targeted server actions:** route session/window actions by `(host_id, server/socket, session/window/pane_id)`; prove that actions cannot cross hosts, that reconnects recover safely, and that network failures do not destroy background work. Use disposable fixtures before opt-in real-server validation.
4. **Major-version release readiness:** finalize packaging and support versions; run independent Linux and macOS CI plus two-server integration gates, preserve upgrade/rollback paths, and document actual limits before choosing the major version and publishing.

Product decisions before milestones 2–3: initial remote OS support (proposal: Linux servers first), whether server discovery stays manual/imported from SSH configuration, and which management actions beyond terminal/session lifecycle belong in the first major release. No decision here blocks the read-only foundation.

## Verification

`tests/test_macos.py` includes BSD output fixtures, permission/failure handling, bounded subprocess calls, installer side-effect checks and real macOS listener/process/network probes. Its three native-only tests must skip on Linux; fixture tests on Linux are not evidence of native Mac support. Existing network keyboard, mouse, clipboard targeting and document rendering regressions also run in the Mac CI job. The Linux CI job retains the full original suite and adds the new fixture/guard tests.

Before pushing, run explicit affected tests through the repository's required environment:

```sh
bash scripts/check.sh tests/test_macos.py tests/test_views.py tests/test_gpu.py \
  tests/test_pimux.py::test_installer_checks_external_tmux_before_installing_dependencies \
  tests/test_pimux.py::test_install_exposes_short_command_and_preserves_user_settings \
  tests/test_pimux.py::test_install_refuses_unrelated_launcher_and_keeps_symlink \
  tests/test_pimux.py::test_installed_config_loads_and_reload_does_not_duplicate_features \
  tests/test_pimux.py::test_background_tmux_manages_exact_windows_without_a_terminal \
  tests/test_pimux.py::test_window_preview_reports_exit_code_and_preserves_panes -q
```

Run the Mac CI command from `.github/workflows/check.yml` on a real Mac as well. This validates the inspector milestone; it does not validate native tmux, proxy saving, installation or a Mac release. The existing full `tests/test_views.py` suite includes proxy persistence through the Bash launcher and still fails that test under Apple Bash 3.2; do not treat the smaller inspector target set as whole-application support.
