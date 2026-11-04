# Development checks

Local verification and GitHub Actions use the same image from `.github/ci/Dockerfile`: Ubuntu 24.04, tmux 3.4, Python 3.12 and a pinned uv. Python dependencies come from `uv.lock`.

The check image rebuilds Ubuntu's tmux 3.4 source package with the [upstream fix for libutempter losing child-exit notifications](https://github.com/tmux/tmux/commit/fa5f3cef3d651b0eb9abfa77fc37ccade81679b5). APT authenticates the Ubuntu source and build dependencies; the two-line backport is stored in `.github/ci/tmux-utempter-sigchld.patch` and applies without fuzz. The rebuild retains Ubuntu's patches and packaging, adds a `+pimux1` package revision, and installs the resulting `.deb` normally, including its genuine dpkg ownership and file digests. The separate build stage adds compiler/dependency downloads and compilation to an uncached image build; later local checks reuse Docker layers, and build tools are not copied into the test image. This is a test-environment backport only: user installation, the tmux 3.2 minimum and all test assertions are unchanged. If Ubuntu incorporates the fix, remove this backport rather than skipping a failed patch.

Run the tests affected by a change before pushing:

```bash
bash scripts/check.sh tests/test_pimux.py::test_background_tmux_manages_exact_windows_without_a_terminal -q
```

The first call builds the environment; Docker reuses its layers on later calls. The checkout is mounted read only and copied into a disposable workspace, with its own Python environment. Running checks does not replace the project's `.venv` or access a live user tmux server.

Tests must be specified explicitly. Actions passes the test files listed in `.github/workflows/check.yml`, then builds the release archive. `tests/test_tmux_passthrough.py` checks argument, byte-stream and cancellation forwarding with an isolated native-command stand-in; the real tmux lifecycle checks remain in `tests/test_pimux.py`. Installer tests stub package managers and use isolated PTYs for confirmation; they never upgrade the test host. Documentation-only changes retain the workflow's skip rules. No retry or failure-suppression step is used.

The macOS job builds pinned Bash/tmux into a removable directory and runs the terminal, inspector and isolated source-installation tests. Homebrew has a separate hosted-Mac package lifecycle gate. See [macOS scope and checks](macos.md).

When changing interactions, select the relevant keyboard, mouse or client-targeting regressions. Avoid assertions about incidental help text, exact rendered rows or version-dependent native formatting; verify the operation and its target instead.

These tools require Docker for development checks; the installed `pimux` command uses its normal terminal dependencies.
