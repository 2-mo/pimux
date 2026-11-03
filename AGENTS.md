# PiMux development

PiMux is an independent repository for research and project terminals. Users and their agents choose how to organize experiments; PiMux provides terminal management.

- Before pushing a behavior change, run its directly affected tests with `bash scripts/check.sh TEST_PATH::TEST_NAME -q`. This is the same Ubuntu 24.04 environment used by Actions, including tmux 3.4. Do not substitute the host's tmux version.
- Supply explicit test targets. Keep local verification focused; documentation-only changes need diff review, and Actions already skips them. The existing full CI scope is specified in `.github/workflows/check.yml`.
- Test keyboard, mouse, targeting and process behavior. Screen readiness must use screen identity rather than incidental body text or a binding row that can scroll out of view.
- For native tmux passthrough, verify arguments and compare native behavior; do not require one version's escaping, spacing or display decoration.
- Treat a failure as a real failure. Fix the cause before merging or publishing; do not add retries or suppress errors to make a check green.

See [development checks](docs/development.md) for commands. These are developer tools; user installation does not require Docker.
