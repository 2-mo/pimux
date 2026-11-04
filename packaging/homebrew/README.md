# Local Homebrew source preview

This directory is an unpublished packaging track. There is no public tap, release
URL or bottle. A formula generated with `render.py` uses an existing local source
archive and its SHA-256; it never invents a public version URL. Rendering requires
Python 3.11+ (the product's source-install minimum remains Python 3.10).

The formula installs application files and a private Python environment beneath
its own Cellar entry. It does not run `scripts/setup-tmux.sh`, copy files into HOME,
edit shell startup files, reload servers or change an existing source installation.
It declares macOS 15+, Bash, tmux, ncurses and Python 3.14 dependencies. The first beta targets Apple silicon; Intel is not validated. Hosted packaging runs on macOS 15, within [Homebrew’s supported OS range](https://docs.brew.sh/Installation), instead of forcing current dependencies to build on unsupported macOS 14. Python runtime wheels
are universal, version/hash-pinned directly from `uv.lock`, and installed without
dependency resolution or build-backend downloads. This is a third-party preview
formula, not a submission to homebrew/core.

The wrapper and tmux helper paths use Homebrew's stable `opt` path. User settings
stay in the existing PiMux configuration/state locations. Upgrading the package
does not replace an already running tmux server. Uninstalling retains sessions,
settings, key preferences, receipts and any server authorizations. `pimux update`
and `pimux uninstall` provide Homebrew instructions rather than modifying a separate
source installation. Dependency upgrades may require separate session migration.

The unpublished previews through `e3e7967f` cached a physical Cellar path in
already loaded shell functions. Those existing shells require a new PiMux shell
to adopt the fixed logical-path runtime; upgrading files cannot rewrite functions
in a live Bash process. Keep any running work until it finishes. Shells started
with the fixed runtime follow `opt` across subsequent package upgrades and old-keg
cleanup. Removing PiMux preserves processes/data, but its UI/helpers are unavailable
until the package is installed again.

The shared tmux requirement remains **3.2 or newer**, with no 3.1 fallback. Future
installer guidance should inspect the selected binary's source, show the exact
package operation and ask through `/dev/tty` before an upgrade. Unknown/custom
installations must not be overwritten. This formula itself never invokes a second
package manager or performs an implicit `brew upgrade`.

`tmux_source.py /absolute/selected/tmux [--brew /absolute/brew]` is the read-only
source interface. It returns `version_output`, resolved paths and receipt-based
layout information. Receipts do not prove that a binary has not been replaced:
`binary_content_verified` remains false and `upgrade_argv` remains null. An old
current core keg can receive `manual_upgrade_argv` for human review only, never an
automatic package action. The shared installer
uses `pimux_tmux_version_supported` from `lib/tmux_compat.bash`, also used by the
Formula install check. The exact file was imported from the independent Linux
commit `4bb7d4f490aea1eeb293e7474c3657cc6aaea010` (SHA-256
`f4dc4f57bb5a17b992f0111077f20b3e7453ce85e2a7441dbac98ceb5ece7704`). This directory
does not duplicate that parser or threshold. The `requires_confirmation` and
`running_server_checked: false` fields
are intentional: confirmation belongs to the shared `/dev/tty` flow, followed by
separate client/server checks. A custom tap, missing receipt or explicit old keg
path gets a diagnostic instead of an automatic operation. Shared installer wiring
is separate from this packaging slice; no shared installer was changed here.

For a local formula, create a fixed `git archive` of the reviewed commit, then:

```sh
python3 packaging/homebrew/render.py /absolute/path/source.tar.gz FULL_COMMIT \
  /isolated/tap/Formula/pimux-preview.rb
```

Use a dedicated Homebrew prefix/HOME/cache for install, test, upgrade and uninstall
verification. Do not run these tests against a developer's real Cellar. A nondefault
prefix may require building dependencies because official bottles are not always
relocatable. Formula audit results and actual lifecycle evidence must be recorded;
the presence of a formula is not proof of installation support.

Publishing requires an authorized immutable source URL/checksum, tap location,
matching CI and supported CPU/macOS matrix. The candidate package version is 1.0.0-beta.1; package revisions used for lifecycle tests do not publish a release.
