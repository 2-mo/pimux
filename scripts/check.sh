#!/usr/bin/env bash
# Check explicit pytest targets in the same environment locally and on Actions.
set -euo pipefail
if [[ $# == 0 || $1 == -* ]]; then
    printf 'Usage: bash scripts/check.sh TEST_PATH[::TEST_NAME] [PYTEST_ARGS...]\n' >&2
    exit 2
fi
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
docker build --build-arg HTTP_PROXY --build-arg HTTPS_PROXY \
    --build-arg "http_proxy=${http_proxy:-${HTTP_PROXY:-}}" \
    --build-arg "https_proxy=${https_proxy:-${HTTPS_PROXY:-}}" \
    --tag pimux-check "$project_dir/.github/ci"
docker run --rm \
    --volume "$project_dir:/source:ro" \
    --env HTTP_PROXY --env HTTPS_PROXY --env ALL_PROXY --env NO_PROXY \
    pimux-check bash -euo pipefail -c '
        tmux -V
        python3 --version
        uv --version
        tar -C /source --exclude=.git --exclude=.venv --exclude=dist \
            --exclude=__pycache__ --exclude=.pytest_cache -cf - . | tar -xf -
        for file in bin/pimux install.sh lib/*.bash lib/bashrc scripts/*.sh; do
            bash -n "$file"
        done
        uv run --locked python -m pytest -p no:cacheprovider "$@"
    ' check "$@"
