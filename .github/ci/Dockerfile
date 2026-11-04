FROM ghcr.io/astral-sh/uv:0.11.29 AS uv
FROM ubuntu:24.04 AS tmux-build

# Keep Ubuntu's packaging and patches; backport only upstream tmux issue #4559.
# A real .deb preserves dpkg ownership and file digests for installer tests.
RUN sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential dpkg-dev patch \
    && apt-get build-dep -y --no-install-recommends tmux
WORKDIR /build
COPY tmux-utempter-sigchld.patch /build/
RUN apt-get source tmux \
    && cd tmux-3.4 \
    && version=$(dpkg-parsechangelog -S Version) \
    && case "$version" in 3.4-*) ;; *) exit 1 ;; esac \
    && patch --batch --forward --fuzz=0 -p1 < /build/tmux-utempter-sigchld.patch \
    && { printf 'tmux (%s+pimux1) noble; urgency=medium\n\n  * CI-only backport of upstream fa5f3cef (utempter SIGCHLD).\n\n -- PiMux CI <ci@pimux.invalid>  Wed, 04 Nov 2026 00:00:00 +0000\n\n' "$version"; cat debian/changelog; } > /build/changelog \
    && mv /build/changelog debian/changelog \
    && dpkg-buildpackage -b -us -uc -j2

FROM ubuntu:24.04
COPY --from=tmux-build /build/tmux_*.deb /tmp/
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates python3 /tmp/tmux_*.deb ncurses-term iproute2 procps util-linux \
    && rm -rf /var/lib/apt/lists/* /tmp/tmux_*.deb
COPY --from=uv /uv /usr/local/bin/uv

ENV UV_CACHE_DIR=/tmp/uv-cache \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8
WORKDIR /workspace
