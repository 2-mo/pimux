#!/usr/bin/env bash
# Exercise the preserved Linux floor with an actual Bash 4.2 executable.
set -euo pipefail
(( BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] == 2 )) || {
    printf 'Run this compatibility check with Bash 4.2; found %s.\n' "$BASH_VERSION" >&2
    exit 1
}
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$project_dir/lib/runtime.bash"
[[ $OSTYPE == linux* ]]
pimux_valid_bash "$BASH"
pimux_bootstrap "$project_dir/bin/pimux"
# Deliberately scope this to the new bootstrap. The unchanged base ui.bash
# already fails to parse one translated associative key in this legacy image.
printf 'Linux bootstrap accepted actual Bash %s.\n' "$BASH_VERSION"
# This checks the platform-specific version policy, not native macOS behavior.
OSTYPE=darwin-compatibility-check
if pimux_valid_bash "$BASH"; then
    printf 'The Mac preview must reject Bash 4.2.\n' >&2
    exit 1
fi
if output=$(pimux_bootstrap "$project_dir/bin/pimux" 2>&1); then
    printf 'The Mac bootstrap incorrectly accepted Bash 4.2.\n' >&2
    exit 1
fi
[[ $output == *'Bash >= 5.1'* ]]
printf 'Mac policy rejected Bash 4.2 with its 5.1 requirement.\n'
