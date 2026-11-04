# Mac foundation 1.0.0-beta.1 release checkpoint

Candidate status: the uploaded Mac/Homebrew implementation at `006216b044ee4861110d57592e651f350fe9663d` has been integrated with Linux main `71b766ad55f004a78ff89a68fb6e1f673553ffaf`. The app version is now `1.0.0-beta.1`. This candidate still needs matching cloud CI and separate release publication. No Mac is controlled during the cloud validation.

The requested scope
is now a usable Mac terminal and Homebrew installation. Unified multi-server TUI
and remote session attachment/creation/splitting/termination are deferred.

## Scope and version proposal

Use **1.0.0-beta.1** for the Mac foundation checkpoint. No release tag has been published. Keep the separate Linux correction track distinguishable in release
notes. A prerelease must not replace the stable Linux download accidentally.
This Mac candidate is independent of PR #5 and
`release/pimux-0.11.0-linux-20261104`; it does not take over or publish that Linux
release branch.

The supported checkpoint should be the native local terminal, independent client
window selection, local inspectors, source installation and Homebrew lifecycle.
The existing `hosts` CLI can remain explicitly experimental: it provides one-shot
read-only snapshots, not a remote-session manager. Public-key enrollment is also
currently reachable and separately confirmed; it should not be advertised as a
core requirement of this first Mac release. It has isolated SSH/PTY evidence and
scoped security reviews, but creates persistent authorization and may leave a grant
pending when verification fails. If the owner wants it completely hidden/disabled,
that needs a small explicit entry-point change and regression review; it has not
silently been disabled in this proposal.

The current platform evidence is Apple silicon macOS 26.7.1. Homebrew packaging was
tested with Brew implementation 7.0.8, Bash 5.3.20, tmux 3.8, ncurses 6.6 and Python
3.14.10 in an isolated nondefault prefix. Source installation still requires Bash
5.1+, tmux 3.2+ and Python 3.10+. The shared tmux version contract remains 3.2; use
matched package-manager dependencies instead of new compatibility paths for 3.1.
Intel and the minimum supported macOS version require actual matching CI/hardware
results. The macos-14 workflow is preparation, not existing evidence of support.

## Fixed local inputs and integration

- `dc123c84aee79661ead967e78e1a02db42b8fd91`: reviewed SSH/terminal-safety behavior.
- `0bee0382668acd4b9089a5ea9fbe5bc85f476db2`: source preview/help closeout.
- `3ad1f78087453cbc0b4de3d4506f210257c8d598` through
  `fc78f4f1a47ca437ee2b3429a2e19feb0297c399`: Homebrew package layout, recipe,
  provenance and actual lifecycle fixture. Packaging review is still required.
- Only `lib/tmux_compat.bash` was copied from Linux
  `4bb7d4f490aea1eeb293e7474c3657cc6aaea010`. Installer/reload/source-upgrade logic
  from that branch was not imported. Path/receipt alone cannot prove an installed
  binary has not been replaced; the Mac probe provides human guidance only.
- PR #3's platform foundation and PR #4's exact local terminal base
  `ffe660b437dacf9c5d60a4c01087e77d92ac744e` are inherited. PR #1 passthrough/client
  fixes overlap and must be reconciled. PR #2 foreground-directory/multiline fixes are integrated from current Linux main; foreground tmux metadata wins and native adapters are used only for missing-directory fallback. Use parent-confirmed final heads, not stale PR metadata.

Do not combine these by replacing whole files/branches. The final integration
commit needs the standard Ubuntu24.04/tmux3.4 gate, Mac source/PTY regression,
Homebrew lifecycle, and existing isolated SSH coverage for any retained host
features. A stopped validation VM was not restarted by the packaging work.

## Formula, download and tap proposal

The local recipe is `packaging/homebrew/pimux-preview.rb.in`; `render.py` binds an
existing git archive and seven locked universal Python wheels to SHA-256 values.
The application and private Python environment live in the package's Cellar,
with stable opt paths for tmux helpers. Installing the package does not edit shell
startup files, copy user configuration, replace a source launcher or reload servers.
Upgrading tmux does not replace an already running server. Package uninstall keeps
running programs, settings and server grants.

Reuse the existing `2-mo/pimux` repository rather than creating a second tap
repository. A reviewed `Formula/pimux-preview.rb` can be added there, with a later
user flow of `brew tap 2-mo/pimux https://github.com/2-mo/pimux` followed by
`brew install 2-mo/pimux/pimux-preview`. The explicit URL is required because the
repository is not named `homebrew-pimux`. This public Formula and install flow are
**not available yet**. No public URL is used by the local tests. A proposed release
asset location is
`https://github.com/2-mo/pimux/releases/download/v1.0.0-beta.1/pimux-source.tar.gz`;
it does not exist yet and must not be advertised as an available download.

After authorization, publish only the exact reviewed source archive, fetch it
again and compare its hash, render the public recipe with that URL and checksum,
and test the URL-based installation. The current local renderer deliberately emits
a file URL; public URL support must validate the downloaded bytes against the
same fixed archive. Test in the standard Homebrew prefix on a disposable CI runner
as well as the already exercised isolated prefix. A bottle is optional for the
first source-formula preview; no Intel bottle, signed app or automatic updater is
being promised. Freeze the application archive at commit R, then add the Formula
in a later reviewed distribution commit T pointing to R's verified asset; the
Formula cannot contain the checksum of an archive that includes that same Formula.

## CI and publication gates

`.github/workflows/homebrew-preview.yml` prepares explicit Linux contract checks
and hosted-Mac install/audit/test/upgrade/cleanup/uninstall checks. It records the
actual commit, OS/CPU/tool versions, source archive and formula hashes. The hosted
runner is disposable; that workflow is not a script to run against a user's real
Homebrew installation. Local lifecycle testing additionally covers two attached
clients, helpers after old-keg removal, original files and a sentinel server.

No matching remote run has been verified for this packaging work. Before release,
verify both PR head and merge-reference checks against the final integrated SHA;
download their logs/artifacts and compare the recorded source hashes. Older green
Mac/Linux runs do not cover later local commits. Complete independent packaging
review before making a readiness claim.

Publication order, each still requiring the parent's appropriate authorization:

1. Decide supported scope/version/platforms and whether experimental host commands
   remain exposed; finish the precise integration and version bump locally.
2. Publish the review branch/PR to the agreed repository/base, inspect exact-head CI
   and review results, then obtain the merge/release decision.
3. Create the agreed prerelease tag/release and upload the exact source archive and
   checksum. Verify the public bytes; do not replace an existing asset silently.
4. Add/update the Formula in the existing repository, test the explicit-URL tap,
   real download URL and recipe, then publish the formula. Publish bottles only
   for CPU/OS combinations actually verified.

Users of the eventual preview would install via the agreed tap, run `pimux doctor`
then `pimux -n local`, and use Homebrew for update/removal. For now, use the fixed
local source preview or the task-isolated package; no public brew command is ready.

Known remaining limits: Apple GPU telemetry, Intel/minimum-macOS coverage, real
tailnet testing, complete remote management, PR #2 integration, matching release
CI and public distribution. No real host/tailnet, user private key, agent/Keychain,
authorized_keys or network settings were changed by this packaging stage.
