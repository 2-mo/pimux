#!/usr/bin/env bash
# Build the standalone release with its runtime, configuration and user docs.
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
output_dir="$project_dir/dist"
mkdir -p "$output_dir"
files=(bin install.sh lib config scripts/setup-tmux.sh scripts/uninstall.sh
       README.md LICENSE docs pyproject.toml uv.lock)
tar --create --gzip --file "$output_dir/pimux-linux.tar.gz" --directory "$project_dir" \
    --exclude='__pycache__' --transform='s,^,pimux/,' "${files[@]}"
(cd "$output_dir" && sha256sum pimux-linux.tar.gz > SHA256SUMS)
printf 'Built %s\n' "$("$project_dir/bin/pimux" --version)"
printf '%s\n' "$output_dir/pimux-linux.tar.gz" "$output_dir/SHA256SUMS"
