#!/usr/bin/env bash
# Disposable loopback-only SSH acceptance. Does not change the host SSH service.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
docker build --build-arg HTTP_PROXY --build-arg HTTPS_PROXY \
    --build-arg "http_proxy=${http_proxy:-${HTTP_PROXY:-}}" \
    --build-arg "https_proxy=${https_proxy:-${HTTPS_PROXY:-}}" \
    --tag pimux-ssh-fixture tests/ssh
fixture_root=$(mktemp -d /tmp/pimux-ssh-check.XXXXXXXX)
cleanup() {
    if [[ -f $fixture_root/endpoints/manifest.json ]]; then
        python3 tests/ssh/fixture.py stop "$fixture_root/endpoints"
    fi
    rm -rf -- "$fixture_root"
}
trap cleanup EXIT
python3 tests/ssh/fixture.py start "$fixture_root/endpoints"
PIMUX_SSH_FIXTURE_MANIFEST="$fixture_root/endpoints/manifest.json" \
    uv run --locked python -m pytest tests/test_hosts_ssh.py tests/test_access_setup_ssh.py tests/test_access_identity_ssh.py tests/test_ssh_security_ssh.py -q
