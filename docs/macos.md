# macOS major-version track

The Mac direction is one Mac managing several servers: host identity, connection state, terminal sessions and host resources. This is server management, not experiment management. This track is separate from Linux 0.10.x fixes. This local development branch adds [explicit read-only multi-server snapshots](hosts.md) to the native local terminal: host-aware aggregation is separate from ordinary SSH shells. There is no Mac release archive, version bump or published installer.

## Native local source preview

Mac source-preview prerequisites: Bash >=5.1, tmux >=3.2, Python >=3.10, curl, system OpenSSH/ssh-keygen, infocmp and `tmux-256color` terminfo. Provide these before installation; the Mac source installer does not install global packages. It reuses an existing uv executable or downloads uv into the user-local runtime, then installs locked Python dependencies there over HTTPS. uv is not a mandatory preinstalled command for end users. Apple Bash 3.2 can read the bootstrap and select modern Bash before loading application libraries. The Mac floor includes `PROMPT_COMMAND` array execution. Those hooks already existed before this change; they are not a reason to raise Linux's launcher minimum. Linux retains its existing Bash >=4.2 guard, and its complete interaction gate continues to use Ubuntu 24.04's Bash 5.2. This milestone does not newly certify every legacy Bash prompt behavior.

The pinned Bash 4.2.53 container passes the new Linux bootstrap and is rejected by the Mac version policy. A separate full-launch probe fails while parsing a translated associative-array key in `lib/ui.bash`; the exact unchanged PR #3 file reproduces that failure. The CI legacy check therefore covers only the new runtime guard, not a claim that the complete application works on Bash 4.2. Use the standard Bash 5.2 Linux environment for the verified interaction behavior.

Prefer existing dependencies. The optional developer build installs pinned upstream Bash 5.3.20 and tmux 3.8, with static libevent, utf8proc and jemalloc, entirely under a new removable directory:

```sh
python3 scripts/build-macos-runtime.py /tmp/pimux-native-runtime
export PIMUX_BASH=/tmp/pimux-native-runtime/prefix/bin/bash
export PATH="/tmp/pimux-native-runtime/prefix/bin:$PATH"
```

This requires Xcode command-line tools. Source URLs and SHA-256 values are in `scripts/macos-runtime-sources.json`. It never runs sudo, Homebrew or a package manager. The directory must be new and contain no whitespace or commas (upstream build constraints). Keep its prefix in a stable location for an installation; deleting it invalidates the runtime pin. Failed builds retain their sources for diagnosis.

The build uses libevent's pipe fallback because a newer SDK can weak-link `pipe2` absent from the running OS. Static jemalloc must retain its Darwin zone constructor to avoid mixing libc allocations with the wrong free routine; its C++ support uses the system library. A real server/split/cleanup smoke test follows compilation; `tmux -V` alone cannot detect these failures.

From a reviewed checkout containing this track, install using an existing modern runtime (replace the example executable directories):

```sh
export PIMUX_BASH=/absolute/path/to/modern/bash
export PATH="/absolute/path/to/tmux/bin:$PATH"
bash scripts/setup-tmux.sh
export PATH="$HOME/.local/bin:$PATH"
pimux --version
pimux -h
```

The optional build above provides the two executable paths instead. A completely clean Mac still needs Python and either preexisting Bash/tmux or Xcode command-line tools to build them. This is a source installation, not a dependency-complete Mac app. The public `main` download command is the Linux release path; do not assume it contains this local track. `uv sync --locked` is an optional developer-environment step, not an installed-user requirement.

For an isolated **local terminal** trial, use a disposable shell, fresh HOME and short socket directory:

```sh
export HOME="$(mktemp -d /tmp/pimux-home.XXXXXX)"
export TMUX_TMPDIR="$(mktemp -d /tmp/pimux-sockets.XXXXXX)"
bash scripts/setup-tmux.sh
"$HOME/.local/bin/pimux" -n local
```

The source installer checks dependencies before writing assets. The Linux download entry point `install.sh` continues to reject macOS before downloads or writes. Mac `pimux update` explains the source-preview boundary without fetching a Linux installer; reinstall from the chosen checkout. Existing Starship is optional on Mac and is not downloaded automatically.

Python packages live in `~/.local/share/pimux/venv`. A literal Bash pin is saved in `~/.config/pimux/shell.conf`; a tmux selection is created only when no existing runtime configuration exists. `PIMUX_BASH` explicitly overrides Bash selection. Malformed configuration, unavailable executables and old Bash fail clearly. Logical sessions, client views, helpers and subsequent panes use the selected runtime, including when a login shell or tmux client resets PATH. Existing user settings are preserved.

Installation backs up changed files and appends only the command PATH line to supported shell startup files. A fresh trial HOME will not discover the normal user's SSH/VS Code settings. Unrelated launcher/assets and existing configuration symlinks are refused. Reinstallation preserves saved proxy/environment/runtime settings and live panes. Uninstallation removes only the managed launcher. It retains configuration, the private Python runtime, shell PATH entries, local identity/operation records, key files and sessions. It does not revoke server authorizations.

## What is usable after source installation

| Entry | Actual scope |
| --- | --- |
| `pimux`, `pimux -n local` | Local tmux TUI; create/enter local sessions, windows and splits. |
| `pimux tmux ...`, `pimux ls` | Native commands/listing on the selected local tmux server. |
| `pimux ip`, `pimux ports`, `pimux gpu` | Local inspectors; unavailable telemetry is explicit. Apple GPU collection is absent. |
| `pimux hosts` | Read local SSH/VS Code candidates; no network connection. |
| `pimux hosts inspect server_a server_b --json` | One-shot, host-aware Linux session/resource snapshots over verified SSH. |
| `pimux hosts access-preview server_a` | Read-only public-key/authorization preview; use `--key` if ambiguous. |
| `pimux hosts access-setup server_a` | Interactive authentication and exact-target/key confirmation, then idempotent public-key grant and selected-key verification. |
| `pimux hosts identity-reset server_a` | Forget PiMux's local key preference only; no server connection or revocation. |

For duplicate aliases, place `--ssh-config '/absolute/path/config'` before the subcommand. Targets must already have a trusted host-key entry; PiMux does not scan hosts or auto-accept new keys. The Linux targets need Python >=3.10 and a stable machine ID. tmux/network/NVIDIA tooling contribute separately reported optional capabilities. No persistent remote collector is installed.

A typical sequence is discover, explicitly inspect two aliases, optionally preview/confirm setup for one selected target, then inspect again using the verified key choice. Passwords, jump authentication, encrypted-key passphrases or MFA may require distinct prompts. No target is contacted merely by discovery. See [the full host workflow and recovery limits](hosts.md).

**Multiple servers currently means CLI read-only aggregation.** There is no unified multi-server TUI, remote shell/session attachment, or remote session creation/termination/splitting. The local manager is not a remote server dashboard, and an ordinary SSH process in a local pane does not add host-aware remote actions. Public-key setup is the separately confirmed persistent-write exception. If verification fails after a possible grant, authorization may remain; receipts preserve uncertainty and automatic rollback does not overwrite the shared authorized_keys file.

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

The native CI job is configured to build the pinned toolchain and run the local suite. A workflow definition is not evidence that the current commit passed it. The isolated installation regression checks modern Bash selection from a system-only PATH, two clients, windows/splits, keyboard/mouse targets, cancelled closure, proxy saving, detach, reinstall and uninstall while keeping live processes and a separate sentinel server. Native probes require a real Mac; Linux skips them. Starship is optional, and the Linux-only ss listener test has a separate native listener probe.

Darwin PTY buffers are small: tests drain output during shutdown, stop on EOF and verify restored flags through the surviving master descriptor. Targeting/process-preservation assertions remain strict. Cancellation is compared after a response from the initialized native tmux client, avoiding signals raced against startup.

Client views independently select **windows**, sharing programs. Panes within the same shared tmux window retain native shared active-pane semantics; this preview does not claim independent same-window focus or program copies. There is no packaged Mac release, Intel Mac validation or Apple GPU collector. The local multi-server branch adds host/SSH/snapshot inspection and a separately confirmed public-key enrollment wizard. Remote session actions remain unimplemented. A CI result is usable only when its head/source matches the delivered commit; older green runs do not certify later commits. These local slices do not have current remote CI or release certification. Native evidence is from Apple silicon macOS 26.7.1, Bash 5.3.20, tmux 3.8, Python 3.11.14 and OpenSSH 10.3p1. The configured macos-14 job does not establish a tested minimum macOS version, and Intel Mac remains unverified.

## Integration dependencies

This local track starts from the exact terminal commit `ffe660b437dacf9c5d60a4c01087e77d92ac744e`; it does not certify whatever head a remote PR currently advertises.

| Track | Integration boundary |
| --- | --- |
| [PR #3](https://github.com/2-mo/pimux/pull/3) | macOS inspector/platform foundation inherited by the terminal track. |
| [PR #4](https://github.com/2-mo/pimux/pull/4) | Native terminal/runtime/source-installation layer, stacked on #3; this branch contains the local `ffe660b` base. |
| [PR #1](https://github.com/2-mo/pimux/pull/1) | Parallel Linux/client fixes. Native passthrough exec/cancellation overlaps the Mac implementation; reconcile it instead of applying it twice. |
| [PR #2](https://github.com/2-mo/pimux/pull/2) | Foreground-directory precedence and multiline metadata fixes are not integrated here. Preserve that precedence and use the native directory adapter as fallback when combining. |

The local host/snapshot, confirmed enrollment, selected-identity and SSH safety slices are later commits on this stack. They are not merged, released or automatically present in #4/main. Final integration needs tests on the combined exact commit, including the Linux fixes. The displayed version is still `0.10.1`; it is not a published Mac major-version number.

## Remaining major-version work

The first bounded multi-server milestone is implemented and locally verified with two isolated SSH endpoints: passive configuration discovery, host-aware snapshots, failure isolation and a separately confirmed public-key wizard. Actual user servers and a real tailnet were not used. Distinguish ordinary OpenSSH over an existing tailnet from Tailscale SSH policy authentication; copying a key is not a general solution to policy-managed access.

Remaining work is a unified host interface and deliberately scoped remote attachment/actions, followed by integration and release readiness. Actions must carry `(host_id, server/socket, session/window/pane_id)` and preserve work on reconnect/failure. A Mac package/distribution format, supported macOS/CPU matrix, major version, installation/upgrade/recovery policy and current matching Linux/Mac/SSH CI still need to be finalized and verified. There is no Mac automatic updater, signed/notarized app or Intel validation. `scripts/package.sh` builds only a Linux archive with GNU tools; it is not a Mac packaging command.

Real-server/tailnet testing and any new persistent credential grant require the appropriate explicit target authorization. Publishing branches/PRs, merging or releasing are separate from this local preview; no publication is implied by these instructions.
