#!/usr/bin/env bash
# Build the standalone release from an explicit list of distributable files.
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
output_dir="$project_dir/dist"
mkdir -p "$output_dir"
files=(pimux pimux.conf ui.bash manager.bash gpu.bash gpu.py gpu_ui.py inspect_ui.py ports.py window_details.py utility_ui.py environment.py environment_ui.py environment.bash proxy_ui.py proxy_status.py proxy.bash shell.bash bashrc starship.toml
       setup-tmux.sh uninstall.sh install.sh README.md README.zh-CN.md LICENSE
       CHANGELOG.md docs/preview.svg pyproject.toml uv.lock)
tar --create --gzip --file "$output_dir/pimux-linux.tar.gz" --directory "$project_dir" \
    --transform='s,^,pimux/,' "${files[@]}"
(cd "$output_dir" && sha256sum pimux-linux.tar.gz > SHA256SUMS)
printf 'Built %s\n' "$("$project_dir/pimux" --version)"
printf '%s\n' "$output_dir/pimux-linux.tar.gz" "$output_dir/SHA256SUMS"
