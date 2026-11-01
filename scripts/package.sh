#!/usr/bin/env bash
# Build the standalone release from an explicit list of distributable files.
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
output_dir="$project_dir/dist"
mkdir -p "$output_dir"
files=(pimux pimux.conf ui.bash manager.bash gpu.bash shell.bash bashrc starship.toml
       setup-tmux.sh uninstall.sh install.sh README.md README.zh-CN.md LICENSE CHANGELOG.md docs/preview.svg)
tar --create --gzip --file "$output_dir/pimux-linux.tar.gz" --directory "$project_dir" \
    --transform='s,^,pimux/,' "${files[@]}"
(cd "$output_dir" && sha256sum pimux-linux.tar.gz > SHA256SUMS)
printf 'Built %s\n' "$("$project_dir/pimux" --version)"
printf '%s\n' "$output_dir/pimux-linux.tar.gz" "$output_dir/SHA256SUMS"
