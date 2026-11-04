# Multi-server preview and confirmed public-key setup

This local development milestone lets one Mac query multiple explicitly selected Linux servers and keep their sessions/resources separate. It is based on the local macOS terminal milestone, not a released major version. Session/resource inspection stays read-only. A separate interactive public-key setup command can make the specifically confirmed authorization change. This local development branch has not been released. Reinstall it from the reviewed source checkout; the Linux release updater is not an upgrade path for these unpublished slices. `inspect` prints a single text/JSON snapshot and exits. There is no unified multi-server TUI, continuous remote dashboard, remote shell/session attachment, or remote session create/split/terminate command. The existing main TUI and `pimux tmux` operate on the selected local tmux server.

## Use existing VS Code / SSH configuration

```sh
pimux hosts
pimux hosts inspect server_a server_b
pimux hosts inspect server_a server_b --json
```

The first command only discovers candidates. It reads `~/.ssh/config` and VS Code / Code Insiders / VSCodium user settings and profile settings on macOS and Linux. JSONC comments and trailing commas are supported, including `remote.SSH.configFile`, absolute paths, `~/`, `${userHome}` and `${env:HOME}`. Custom user-data/workspace settings can be selected with `pimux hosts discover --settings /absolute/path/settings.json`. Relative VS Code config paths and unresolved variables are reported instead of guessed.

Discovery follows bounded literal/glob `Include` paths (relative user includes use `~/.ssh`), detects cycles/missing files and lists only concrete positive aliases. Wildcards, negated aliases and conditional `Match` rules are reported, not evaluated. It does not run `ssh -G`, `Match exec`, ProxyCommand, a shell or a network query. Candidate discovery is not a replacement for OpenSSH configuration evaluation; aliases inside conditional includes may still be conditional. Declared identity paths and unclassified broad matches are excluded before opening. Explicitly selected files receive only a short unbuffered type-header check before any body read; a private-key header stops the read. Every skipped, cyclic, missing, malformed or truncated input marks the scan incomplete and prevents connection.

When an alias exists in several configurations, choose only the configuration:

```sh
pimux hosts --ssh-config '/absolute/path/ssh config' inspect server_a server_b
```

An explicit inspect invokes system OpenSSH with that configuration. OpenSSH retains responsibility for Host/Include/Match, ProxyJump, identity/agent selection and host-key lookup. PiMux forces strict host-key verification, no key updates, no agent forwarding, no local commands, no shared control socket and no automatic agent/Keychain credential caching. Unselected/configured authentication remains noninteractive; an already verified saved identity can use masked prompts during terminal inspection, as described below. Custom ProxyCommand and Match exec directives are refused before connection. A private OpenSSH wrapper enforces the same strict policy on each implicit ProxyJump process, including known-host command suppression and no persistent control connection. Non-executing Match rules remain OpenSSH's responsibility. Incomplete configuration inspection also prevents connection; candidate discovery alone does not certify a configuration as connectable.

OpenSSH's implicit ProxyJump command mishandles spaces/metacharacters in its `-F` path on the tested Mac. PiMux freezes the inspected configuration and Include closure into private, short-lived files under `/tmp/pimux-access-*`, passing safe paths to OpenSSH. Original files are not changed. A saved target identity uses a second destination-only copy; jumps retain the original inspected rules. Temporary copies are removed after success, failure or cancellation.

Discovered profiles receive deterministic local host IDs from configuration path plus alias. Their server identity is authenticated by the existing SSH host key and returned Linux machine ID; the preview does **not** persist a new machine-ID pin automatically. To enforce an expected machine ID as well, use the explicit inventory below. Unknown or changed SSH host keys fail; there is no auto-accept, keyscan or disabling of verification. Without a saved verified identity, read-only inspection requires noninteractive authentication. A saved choice binds later results to the reviewed server/account as well as its selected public key; terminal inspection can request its passphrase, while batch inspection remains noninteractive. The separate setup wizard can request initial authentication through the system SSH client without storing passwords.

## Optional explicit inventory

```sh
pimux hosts add lab_a --name 'Lab A' --address 127.0.0.1 --port 2222 \
  --user fixture --node-id 0123456789abcdef0123456789abcdef \
  --known-hosts /absolute/path/verified_known_hosts --identity-file /absolute/path/test_key
pimux hosts list
pimux hosts inspect lab_a
pimux hosts inspect --all
```

`add` is a local atomic configuration write and does not connect. The optional file is `~/.config/pimux/hosts.json` (mode 0600), with version 1, unique `host_id` and expected `node_id` values. Existing malformed files and symlinks are refused. Direct entries use an explicitly supplied verified known-hosts file and an explicit identity file or the agent; they do not read ambient SSH configuration or search default private-key files. PiMux itself never reads identity-file contents. `--all` queries only this saved inventory, not every discovered alias. Inspection without targets is rejected.

## Snapshot and failure boundaries

The fixed SSH command runs bundled standard-library Python code in memory, with bytecode writes disabled. No remote agent is installed. Parameters are JSON on stdin, not shell fragments. Remote prerequisites are Linux, Python 3.10+ and a stable `/etc/machine-id`; tmux, iproute2 and NVIDIA tools are optional capabilities. Existing server shell startup output can contaminate stdout; that is rejected as a protocol error rather than silently stripped.

Protocol `pimux.snapshot` version 1 uses a length-delimited frame and a fresh request ID. The client validates frame size, version, exact fields, request/host/socket identity, machine ID, account and every resource row; duplicate JSON keys, non-finite numbers, wrong types, oversized output and leading/trailing pollution are rejected. It does not display partially parsed snapshots.

Each host result has a stable `host_id`, visible name, connection state, server hostname, account and node ID. A session key is `(host_id, socket, session_id)`, so duplicate session names and `$0` IDs on different hosts remain distinct. Capabilities independently report `available`, `unavailable`, `permission_denied` or `error`:

- Sessions: existing tmux sessions on the selected socket, literal names and window counts. No server/session creation, focus changes or process output capture.
- Resources: Linux load averages and `/proc/meminfo`; container cgroup limits are not inferred.
- Network: current interface names and addresses; no network changes or topology discovery.
- GPU: available NVIDIA memory telemetry; missing NVIDIA tooling is unavailable, not proof that there is no GPU.

The saved inventory is limited to 32 entries. Batch inspection queries selected hosts with four concurrent workers and a per-host 1–30 second deadline (default 10). Terminal inspection processes hosts sequentially so prompts cannot overlap; a saved identity with interactive authentication has a 120-second connection deadline. A failed host retains its own error while healthy results remain available. SSH errors, host-key/authentication errors, timeouts, protocol errors and identity mismatches are distinct. Collectors also bound each command and total lifetime. Cancellation kills task-owned client groups, closes owned OS pipes and waits for their leader with a bounded cleanup deadline, including output-flood cases. Remote query commands have their own deadline; an unresponsive kernel cannot be guaranteed to reap within a fixed wall-clock limit. Exit status is nonzero for a failed host connection/protocol; capability availability remains explicit inside each connected snapshot.

## Public-key authorization preview

```sh
pimux hosts access-preview server_a
# Only when several public keys exist or conditional rules leave ambiguity:
pimux hosts access-preview server_a --key /absolute/path/chosen_key.pub
```

This separate entry point discovers public `.pub` files and literal public companions mentioned by the selected configuration. It validates fingerprints, deduplicates identical public keys and preselects a sole candidate. With multiple candidates or unevaluated Match rules, it reports the selection requirement; supply `--key` to choose explicitly. Preview does not open an interactive key chooser and does not connect until that choice is unambiguous. It never generates long-lived credentials, reads private key files or derives public keys by opening private keys.

After an explicitly selected connection, the preview shows the actual account/server, verified SSH host-key fingerprint, server ID, selected public-key fingerprint and proposed authentication permission. The collector reads only the standard user's `.ssh/authorized_keys`, refuses symlinks/unsafe ownership or group/world-writable paths, preserves restrictions and detects an already-listed key irrespective of comments. Custom AuthorizedKeysFile/AuthorizedKeysCommand and server policy are not inferred; a file entry is not a claim that authentication with that key has been tested.

## Confirmed public-key setup

```sh
pimux hosts access-setup server_a
# Only when selection is ambiguous:
pimux hosts access-setup server_a --key /absolute/path/chosen_key.pub
```

The wizard chooses a sole applicable public key automatically. If none exists, it prepares a temporary Ed25519 key using native `ssh-keygen`; the user chooses its passphrase there. The key is retained as `~/.ssh/id_ed25519` when that name is unused, or under a unique `~/.ssh/pimux_<host-id>_<unique-id>_ed25519` name, only after confirmation. Existing SSH configuration remains untouched. The wizard reports the retained public-key path and remembers a successfully verified key for this target inside PiMux. It never overwrites an existing key. The private file is mode 0600, and cancellation before confirmation removes the temporary candidate. The program does not read existing private-key contents or put passwords/passphrases in command arguments, configuration or logs.

The user selects the target, authenticates when needed, and confirms one review showing the actual account/server, machine ID, independently verified SSH host-key fingerprint, public-key fingerprint and proposed persistent login permission. A newly generated key also shows its final path and protection. There is no noninteractive `--yes` option. Unknown/changed host keys stop the workflow; they are never automatically accepted. An encrypted key not already unlocked in an agent can require its passphrase again during verification.

The connection uses a private frozen copy of the inspected Include closure, preserving ordering and passing other rules to OpenSSH. Immediately after confirmation, it checks the original configuration and selected public key again. Changed inputs require a new confirmation. The connected server also compares the authorization file with the reviewed digest before appending. It refuses symlinks, hardlinked authorization files, unsafe ownership/permissions and oversized files; it does not elevate privileges, change sshd settings or overwrite other authorizations. A matching fingerprint with existing restriction options is preserved and never duplicated as an unrestricted entry.

An approved write appends one uniquely marked public-key line, records the operation, then opens a new connection with password and keyboard-interactive authentication disabled. Success requires the selected client-key fingerprint, the same verified server key, node ID and account. If verification fails, the new authorization may still exist. The wizard preserves the file and operation receipt and reports that recovery needs review. It does not automatically revoke an entry or replace/truncate the shared authorized_keys file: there is no enforceable exclusive-writer contract with other authorization managers. A digest check followed by replacement cannot protect concurrent edits. Revocation therefore requires a separately coordinated administrator action; this preview provides no automatic revoke command.

If the channel drops after a possible write, the client queries operation state under the selected key before considering the outcome. It never blindly repeats an append. Local mode-0600 receipts in `~/.local/state/pimux/enrollment/` and remote private `.ssh/.pimux-enrollment/` records support reconciliation. The next invocation recognizes pending local operations. Before every existing-key or recovery fast path it checks the original account/UID, node ID, verified host key, configuration digest and public-key fingerprint. A changed alias destination, even if independently trusted and already authorized with the same key, cannot resolve the original operation. Failed verification, unsupported login policy and nonterminal remote records preserve the original pending receipt; changed targets require review and fresh confirmation for a separate operation. `--operation ID` explicitly selects a recorded operation. If connectivity/authentication still prevents checking, the result remains unconfirmed. A generated key already retained by confirmation remains available for recovery.

### Reusing the selected identity

After `access-setup` proves that the selected public key authenticates on the reviewed server/account, PiMux stores only public-key metadata and target/configuration binding in private `~/.local/state/pimux/identities/` records. Ordinary `hosts inspect` and read-only access preview then reuse that identity automatically. An existing matching authorization needs verification but no new grant. The saved selection is also preferred when reopening the key chooser.

OpenSSH accumulates `IdentityFile` entries, so prepending `-i` does not isolate a key. For the destination, PiMux freezes the inspected Include closure and removes only IdentityFile/CertificateFile directives from a second temporary copy, supplying the chosen identity with `IdentitiesOnly=yes` and target password/keyboard-interactive authentication disabled. Host/Match and other options remain interpreted by OpenSSH. Each ProxyJump child receives the unmodified frozen configuration and keeps its own identity/certificate rules. PiMux neither edits original files nor creates an agent. Every system SSH invocation and jump wrapper forces `AddKeysToAgent=no`; macOS additionally forces `UseKeychain=no` before inherited configuration. Already-unlocked matching agent identities remain usable, while loading a file or entering its passphrase does not authorize automatic agent/Keychain persistence. Linux receives no macOS-only option. Temporary independent agents exist only in tests. This selected-public-key workflow does not substitute SSH certificates for the confirmed key.

Interactive inspection can ask OpenSSH's masked terminal helper to unlock an encrypted key; multiple hosts prompt sequentially. The parent saves and restores complete terminal attributes after each connection and on overall exit, including timeout, cancellation, SIGTERM and exceptions. Restoration applies attributes immediately and flushes residual input separately, without waiting for PTY output to drain. SSH process-group cleanup remains bounded; a killed prompt helper is not relied upon to restore echo. Batch inspection never prompts and reports when the selected key cannot authenticate. It does not silently fall back to another target identity. Already-unlocked matching identities may be used from an existing configured agent. Target results must still match the saved host key, node, account and accepted client-key fingerprint. Changed configuration or public metadata fails before connection; a different trusted server detected during the read discards the result.

`pimux hosts identity-reset server_a` removes only this local preference without connecting or revoking any server authorization. Then `access-setup` can select and verify another key. Pending authorization receipts retain their independent original-target recovery checks; resetting a preference never clears an unresolved operation. Ordinary SSH/VS Code commands keep using their existing configuration, since the saved choice applies to PiMux only.

### Jump hosts and Tailscale

Existing `ProxyJump` remains supported, with strict host-key validation, no local commands, no agent forwarding and no persistent control connection on every hop. Jump hosts and the destination may have separate passwords, key passphrases or MFA; the wizard cannot promise one password for every topology. Reusing already available authentication minimizes prompts.

Ordinary OpenSSH reached over an existing Tailscale network route uses the same setup flow. The agent checks its login-process ancestry: an OpenSSH ancestor permits the ordinary authorized_keys workflow; a detected Tailscale SSH policy login or unknown login mode refuses authorization writes. Tailscale SSH policy access is not configured by copying keys. No tailnet, network, service or policy setting is changed. No dedicated, authorized tailnet endpoint was used for this milestone. The local Tailscale installation and online status were inspected without connecting to peers or changing settings; this is not an end-to-end Tailscale test. Its login-mode distinction still has component evidence only. Before real testing, record security-fixed client/server versions and explicitly authorized test nodes/accounts, host-key trust, network/SSH policy scope, and any check-mode approval. Ordinary OpenSSH over a tailnet and Tailscale SSH policy mode require separate evidence.

## Verification and scope

Component/installation regression uses explicit targets through `bash scripts/check.sh` in Ubuntu 24.04 / tmux 3.4. Native Mac tests additionally use two disposable Ubuntu SSH containers with distinct host keys, machine IDs and duplicate `shared` sessions. Containers publish only on the VM's loopback address; native Mac access uses the existing task VM's loopback forwarding. Fixtures never use the user's SSH configuration, keys or servers.

`tests/ssh/fixture.py` creates task-generated authentication material and records exact container names for cleanup. `tests/test_hosts_ssh.py` requires `PIMUX_SSH_FIXTURE_MANIFEST`; without it, the tests explicitly skip and are not evidence of SSH support. Real cases cover both servers, malformed/versioned/polluted/flooded output, timeout/disconnect isolation, unknown/changed keys, mismatched machine ID, cancellation, existing aliases/Include, actual ProxyJump and repeated read-only authorization preview. Pane/process identities on both managed and sentinel sockets are checked around tests. `tests/test_access_setup_ssh.py` adds real fixture-only authorization append, selected-key verification, restricted-key deduplication, confirmation conflicts, declined unsafe rollback with concurrent edits, original-target recovery binding, a server-side lost acknowledgement, masked terminal password authentication, generated-key retention and ProxyJump enrollment. `tests/test_access_identity_ssh.py` adds existing/multiple IdentityFile conflicts, remembered selection, missing-key refusal and encrypted-key terminal/batch failures. `tests/test_ssh_security.py` covers offline native policy precedence and real PTY interruption/repeated-call cleanup; `tests/test_ssh_security_ssh.py` adds actual masked SSH prompts and unchanged temporary-agent key lists across target and jump authentication. These tests never use the user's agent or write Keychain. Fixture authorization files and temporary daemon settings are restored after every case.

There is no server dashboard TUI, remote session mutation, real-server validation, Mac remote collector, SSH config import/edit, SSH config semantics emulator, Apple GPU collection or release artifact. Source-only local commits and patches are the deliverable; the base macOS PR's latest remote CI is tracked separately. The read-only baseline is a separate fixed commit. Authorization setup is a later local slice requiring its own independent review. Future session actions must remain keyed by host/server/session identity.
