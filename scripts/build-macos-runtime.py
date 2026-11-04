#!/usr/bin/env python3
"""Build an optional removable Bash/tmux toolchain, without Homebrew or sudo.

Requires macOS, Xcode command-line tools (C/C++, make, patch), curl and Python.
Downloads pinned upstream sources; writes only beneath the requested directory.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='new, removable build directory (no spaces or commas)')
    args = parser.parse_args()
    root = args.directory.resolve()
    if sys.platform != 'darwin':
        parser.error('this developer tool builds native macOS runtimes only')
    if root.exists() or any(c.isspace() or c == ',' for c in str(root)):
        parser.error('use a new directory whose path has no whitespace or commas')
    for tool in ('cc', 'c++', 'make', 'patch', 'curl', 'tar'):
        if not shutil.which(tool):
            parser.error(f'missing build tool: {tool}')
    root.mkdir(parents=True)
    downloads, source, prefix = (root / name for name in ('downloads', 'sources', 'prefix'))
    downloads.mkdir()
    source.mkdir()
    manifest = json.loads(Path(__file__).with_name('macos-runtime-sources.json').read_text())
    env = dict(os.environ)

    def run(command, cwd, **kwargs):
        subprocess.run(command, cwd=cwd, env=env, check=True, **kwargs)

    def download(item):
        path = downloads / item['name']
        run(['curl', '--fail', '--silent', '--show-error', '--location', '--proto', '=https',
             '--max-time', '300', item['url'], '-o', str(path)], root)
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError('Checksum mismatch: ' + path.name)
        print('Verified ' + path.name, flush=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(download, manifest))
    for item in manifest:
        if '.tar.' in item['name']:
            run(['tar', '-xf', str(downloads / item['name'])], source)
    bash = source / 'bash-5.3'
    for item in manifest:
        if item['name'].startswith('bash53-'):
            run(['patch', '-p0', '-i', str(downloads / item['name'])], bash)

    def build(directory, *flags):
        run(['./configure', '--prefix=' + str(prefix), *flags], directory)
        run(['make', '-j4'], directory)
        run(['make', 'install'], directory)

    build(bash, '--without-bash-malloc', '--disable-nls')
    # New SDKs can link a weak pipe2 symbol absent from the running macOS.
    # libevent's pipe + fcntl fallback provides the same required semantics.
    env['ac_cv_func_pipe2'] = 'no'
    build(source / 'libevent-2.1.13-stable', '--disable-openssl', '--disable-shared', '--enable-static')
    utf8 = source / 'utf8proc-2.12.0'
    run(['make', '-j4', 'libutf8proc.a'], utf8)
    shutil.copy2(utf8 / 'utf8proc.h', prefix / 'include')
    shutil.copy2(utf8 / 'libutf8proc.a', prefix / 'lib')
    build(source / 'jemalloc-5.4.0', '--disable-shared', '--enable-static')
    env.update(LIBEVENT_CFLAGS='-I' + str(prefix / 'include'),
               LIBEVENT_LIBS=str(prefix / 'lib/libevent.a'),
               JEMALLOC_CFLAGS='-I' + str(prefix / 'include'),
               # The Darwin zone constructor must survive static linking;
               # otherwise libc strdup allocations reach the wrong free().
               JEMALLOC_LIBS='-Wl,-force_load,' + str(prefix / 'lib/libjemalloc.a') + ' -lc++',
               CPPFLAGS='-I' + str(prefix / 'include'), LDFLAGS='-L' + str(prefix / 'lib'))
    build(source / 'tmux-3.8', '--enable-utf8proc', '--enable-jemalloc')
    run([str(prefix / 'bin/bash'), '--version'], root)
    run([str(prefix / 'bin/tmux'), '-V'], root)
    # Exercise server startup, client disconnect, splitting and cleanup, not
    # merely --version (which cannot detect allocator or event-loop failures).
    with tempfile.TemporaryDirectory(prefix='pimux-build-', dir='/tmp') as temporary:
        test_env = {**env, 'HOME': temporary, 'SHELL': str(prefix / 'bin/bash')}
        test_env.pop('TMUX', None)
        command = [str(prefix / 'bin/tmux'), '-S', temporary + '/socket', '-f', '/dev/null']
        try:
            subprocess.run([*command, 'new-session', '-d', '-s', 'check', 'sleep 30'], env=test_env, check=True)
            subprocess.run([*command, 'split-window', '-t', 'check', 'sleep 30'], env=test_env, check=True)
            result = subprocess.check_output([*command, 'list-panes', '-t', 'check', '-F', '#{pane_dead}'], env=test_env, text=True)
            if result.splitlines() != ['0', '0']:
                raise RuntimeError('Native tmux smoke test failed: ' + result)
        finally:
            subprocess.run([*command, 'kill-server'], env=test_env, capture_output=True)
    print('Verified native runtime: ' + str(prefix), flush=True)


if __name__ == '__main__':
    main()
