# Development checks

Local verification and GitHub Actions use the same image from `.github/ci/Dockerfile`: Ubuntu 24.04, tmux 3.4, Python 3.12 and a pinned uv. Python dependencies come from `uv.lock`.

Run the tests affected by a change before pushing:

```bash
bash scripts/check.sh tests/test_pimux.py::test_background_tmux_manages_exact_windows_without_a_terminal -q
```

The first call builds the environment; Docker reuses its layers on later calls. The checkout is mounted read only and copied into a disposable workspace, with its own Python environment. Running checks does not replace the project's `.venv` or access a live user tmux server.

Tests must be specified explicitly. Actions passes the terminal, GPU, views, environment and installer test files, then builds the release archive. Installer tests stub package managers and use isolated PTYs for confirmation; they never upgrade the test host. Documentation-only changes retain the workflow's skip rules. No retry or failure-suppression step is used.

When changing interactions, select the relevant keyboard, mouse or client-targeting regressions. Avoid assertions about incidental help text, exact rendered rows or version-dependent native formatting; verify the operation and its target instead.

These tools require Docker for development checks; the installed `pimux` command uses its normal terminal dependencies.
