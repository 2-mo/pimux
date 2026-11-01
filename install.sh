#!/usr/bin/env bash
# Download and install the latest complete PiMux release.
set -euo pipefail
for dependency in curl tar sha256sum; do
    command -v "$dependency" >/dev/null 2>&1 || {
        printf 'PiMux installer requires %s.\n' "$dependency" >&2
        exit 1
    }
done
release_url=https://github.com/2-mo/pimux/releases/latest/download
install_work=$(mktemp -d)
trap 'rm -rf -- "$install_work"' EXIT
curl --fail --show-error --silent --location --proto '=https' --tlsv1.2 \
    "$release_url/pimux-linux.tar.gz" -o "$install_work/pimux-linux.tar.gz"
curl --fail --show-error --silent --location --proto '=https' --tlsv1.2 \
    "$release_url/SHA256SUMS" -o "$install_work/SHA256SUMS"
(cd "$install_work" && sha256sum --check SHA256SUMS)
tar --extract --gzip --no-same-owner --file "$install_work/pimux-linux.tar.gz" --directory "$install_work"
bash "$install_work/pimux/setup-tmux.sh"
