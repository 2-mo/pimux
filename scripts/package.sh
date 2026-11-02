#!/usr/bin/env bash
# Build the standalone release with its runtime, configuration and user docs.
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
output_dir="$project_dir/dist"
mkdir -p "$output_dir"
files=(pimux install.sh setup-tmux.sh lib config scripts/uninstall.sh
       README.md README.zh-CN.md LICENSE CHANGELOG.md docs pyproject.toml uv.lock)
tar --create --gzip --file "$output_dir/pimux-linux.tar.gz" --directory "$project_dir" \
    --exclude='__pycache__' --transform='s,^,pimux/,' "${files[@]}"
(cd "$output_dir" && sha256sum pimux-linux.tar.gz > SHA256SUMS)
printf 'Built %s\n' "$("$project_dir/pimux" --version)"
printf '%s\n' "$output_dir/pimux-linux.tar.gz" "$output_dir/SHA256SUMS"
