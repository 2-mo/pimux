# macOS major-version track

The Mac direction is one Mac managing several servers: host identity, connection state, terminal sessions and host resources. This is server management, not experiment management. This track is separate from Linux 0.10.x fixes. The source preview provides a **local terminal only**; SSH shells do not constitute multi-server management. There is no Mac release archive, version bump or published installer.

## Native local source preview

Mac preview requirements: Bash >=5.1, tmux >=3.2, Python >=3.10, uv, curl and `tmux-256color` terminfo. Apple Bash 3.2 can read the bootstrap and select modern Bash before loading application libraries. The Mac floor includes `PROMPT_COMMAND` array execution. Those hooks already existed before this change; they are not a reason to raise Linux's launcher minimum. Linux retains its existing Bash >=4.2 guard, and its complete interaction gate continues to use Ubuntu 24.04's Bash 5.2. This milestone does not newly certify every legacy Bash prompt behavior.

The pinned Bash 4.2.53 container passes the new Linux bootstrap and is rejected by the Mac version policy. A separate full-launch probe fails while parsing a translated associative-array key in `lib/ui.bash`; the exact unchanged PR #3 file reproduces that failure. The CI legacy check therefore covers only the new runtime guard, not a claim that the complete application works on Bash 4.2. Use the standard Bash 5.2 Linux environment for the verified interaction behavior.

Prefer existing dependencies. The optional developer build installs pinned upstream Bash 5.3.20 and tmux 3.8, with static libevent, utf8proc and jemalloc, entirely under a new removable directory:

```sh
python3 scripts/build-macos-runtime.py /tmp/pimux-native-runtime
export PIMUX_BASH=/tmp/pimux-native-runtime/prefix/bin/bash
export PATH="/tmp/pimux-native-runtime/prefix/bin:$PATH"
uv sync --locked
```

This requires Xcode command-line tools. Source URLs and SHA-256 values are in `scripts/macos-runtime-sources.json`. It never runs sudo, Homebrew or a package manager. The directory must be new and contain no whitespace or commas (upstream build constraints). Keep its prefix in a stable location for an installation; deleting it invalidates the runtime pin. Failed builds retain their sources for diagnosis.

The build uses libevent's pipe fallback because a newer SDK can weak-link `pipe2` absent from the running OS. Static jemalloc must retain its Darwin zone constructor to avoid mixing libc allocations with the wrong free routine; its C++ support uses the system library. A real server/split/cleanup smoke test follows compilation; `tmux -V` alone cannot detect these failures.

For an isolated trial, use a disposable shell, fresh HOME and short socket directory:

```sh
export HOME="$(mktemp -d /tmp/pimux-home.XXXXXX)"
export TMUX_TMPDIR="$(mktemp -d /tmp/pimux-sockets.XXXXXX)"
bash scripts/setup-tmux.sh
"$HOME/.local/bin/pimux" -n local
```

The source installer checks dependencies before writing assets. The Linux download entry point `install.sh` continues to reject macOS before downloads or writes. Mac `pimux update` explains the source-preview boundary without fetching a Linux installer; reinstall from the chosen checkout. Existing Starship is optional on Mac and is not downloaded automatically.

Python packages live in `~/.local/share/pimux/venv`. A literal Bash pin is saved in `~/.config/pimux/shell.conf`; a tmux selection is created only when no existing runtime configuration exists. `PIMUX_BASH` explicitly overrides Bash selection. Malformed configuration, unavailable executables and old Bash fail clearly. Logical sessions, client views, helpers and subsequent panes use the selected runtime, including when a login shell or tmux client resets PATH. Existing user settings are preserved.

Installation backs up changed files and appends only the command PATH line to supported shell startup files. Unrelated launcher/assets and existing configuration symlinks are refused. Reinstallation preserves saved proxy/environment/runtime settings and live panes. Uninstallation removes the managed launcher, retaining configuration and sessions.

## Platform boundary

`lib/runtime.bash` delegates macOS gaps to standard-library Python: paths with missing components, filesystem signatures, inherited-descriptor advisory locking, bounded command groups and exact process directories. Linux retains its established GNU/util-linux implementations. Timeout and cancellation terminate the command group, with a kill after the grace period for resistant processes. No lock-file existence approximation is used.

Darwin terminal directory actions use the public `proc_pidinfo` ABI via libproc, preserving Unicode, quotes, backslashes, newlines and controls. Display inspectors use `lsof`, `ps`, `ifconfig` and `netstat` through absolute system paths, bounded queries and no administrator privileges. Lsof's ambiguous caret escapes remain display text, not action targets. Queries do not change networking or connect to user servers.

Ports include only processes visible to the current user; empty selection differs from query failure. Process command text is for display, not a lossless argument vector. Exit/permission failures leave details unavailable. Network snapshots retain scoped IPv6 gateways and separate defaults, with a `system` table label rather than Linux policy-table claims. Subnet filtering omits host, rejected, blackhole, loopback, link-local and multicast routes. `pimux ip --once --all` includes loopback interfaces.

Missing NVIDIA tools produce explicit unavailable telemetry, not a claim that the Mac has no GPU. Apple GPU metrics are unimplemented. Proxy saving and shell reports use the selected runtime. Legacy foreground-environment inference still requires Linux `/proc`; Mac reports unknown rather than inspecting credentials or restarting processes.

`pimux tmux` execs the configured command array, preserving native arguments, streams and cancellation. This common fix also exists in Linux draft PR #1; this independent branch does not modify that PR.

The process-directory adapter in `window_details.py` still inherits the base branch's preference for the parent pane process over a foreground program's directory. Linux draft PR #2 fixes that precedence and multiline metadata separately. When combining the branches, retain #2's tmux foreground-directory preference and use this native adapter only as its missing-directory fallback; do not replace the #2 fix. This preview does not claim that foreground-directory issue is resolved.

## Verification and limits

Run the unchanged repository gate before pushing, with explicit targets in **Ubuntu 24.04 / tmux 3.4**:

```sh
bash scripts/check.sh tests/test_pimux.py tests/test_gpu.py tests/test_views.py \
  tests/test_environment.py tests/test_macos.py tests/test_host_runtime.py \
  tests/test_native_terminal.py -q
```

The native CI job builds the pinned toolchain and runs the full local suite. The isolated installation regression checks modern Bash selection from a system-only PATH, two clients, windows/splits, keyboard/mouse targets, cancelled closure, proxy saving, detach, reinstall and uninstall while keeping live processes and a separate sentinel server. Native probes require a real Mac; Linux skips them. Starship is optional, and the Linux-only ss listener test has a separate native listener probe.

Darwin PTY buffers are small: tests drain output during shutdown, stop on EOF and verify restored flags through the surviving master descriptor. Targeting/process-preservation assertions remain strict. Cancellation is compared after a response from the initialized native tmux client, avoiding signals raced against startup.

Client views independently select **windows**, sharing programs. Panes within the same shared tmux window retain native shared active-pane semantics; this preview does not claim independent same-window focus or program copies. There is no packaged Mac release, Intel Mac validation, Apple GPU collector, host inventory, remote protocol or cross-server aggregation. CI validates its exact source commit and tested platforms; it is not release certification.

## Following major-version milestones

1. **Host inventory and read-only aggregation:** explicit host IDs and opt-in entries; system SSH configuration/agent without copying keys; host-key verification; per-host connection/timeouts; versioned structured snapshots with capability flags. Aggregate at least two isolated test servers, including unavailable hosts and duplicate session names.
2. **Targeted server actions:** route by `(host_id, server/socket, session/window/pane_id)`; prove actions cannot cross hosts and reconnect/network failures preserve work. Use disposable fixtures before opt-in real-server validation.
3. **Release readiness:** finalize packaging/support versions, upgrade/rollback, independent Linux/Mac CI and two-server gates before choosing and publishing the major version.

Later product decisions: Linux-first remote support; manual host entries versus optional SSH-config import; and management actions beyond terminal/session lifecycle. These do not block the local runtime foundation.
