# pimux-managed: shared tmux version checks (also usable by package installers).
# Keep this module compatible with Bash 3; it never starts or changes a server.
PIMUX_TMUX_MINIMUM=3.2

pimux_tmux_version_supported() {
    local version=$1
    [[ $version =~ ^tmux\ ([0-9]+)\.([0-9]+)[a-z]?$ ]] || return 1
    (( 10#${BASH_REMATCH[1]} > 3 ||
       (10#${BASH_REMATCH[1]} == 3 && 10#${BASH_REMATCH[2]} >= 2) ))
}

pimux_tmux_package_supported() {
    local version=${1#*:}
    # A distro package revision is not part of the upstream version.
    version=${version%%-*}
    pimux_tmux_version_supported "tmux $version"
}
