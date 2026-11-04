#!/usr/bin/env python3
"""Render a private-preview formula from an immutable local source archive."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile
import tomllib


def ruby_string(value):
    return json.dumps(value, ensure_ascii=False).replace('#{', '\\#{')


def wheel_resources(lock):
    packages = {p['name']: p for p in lock['package']}
    names = set()

    def visit(name):
        if name in names:
            return
        names.add(name)
        for dep in packages[name].get('dependencies', []):
            marker = dep.get('marker')
            if marker == "sys_platform == 'win32'":
                continue
            if marker:
                raise ValueError(f'Review new dependency marker: {marker}')
            visit(dep['name'])

    for dependency in packages['pimux-dev']['dependencies']:
        visit(dependency['name'])
    resources = []
    for name in sorted(names):
        wheels = [w for w in packages[name]['wheels'] if w['url'].endswith('-none-any.whl')]
        if len(wheels) != 1:
            raise ValueError(f'Expected one locked universal wheel: {name}')
        wheel = wheels[0]
        digest = wheel['hash'].removeprefix('sha256:')
        if not re.fullmatch('[a-f0-9]{64}', digest) or not wheel['url'].startswith('https://files.pythonhosted.org/'):
            raise ValueError('Unrecognized dependency source/hash')
        resources.append({'name': name, 'version': packages[name]['version'],
                          'url': wheel['url'], 'sha256': digest})
    return resources


def render(archive, commit, revision, output):
    if not re.fullmatch('[a-f0-9]{40}', commit) or revision < 1:
        raise ValueError('Provide a full source commit and positive package revision')
    archive = archive.resolve(strict=True)
    with tarfile.open(archive) as tar:
        if tar.pax_headers.get('comment') != commit:
            raise ValueError('Archive provenance must match the requested git commit')
        locks = [m for m in tar.getmembers() if m.isfile() and m.name.endswith('/uv.lock')]
        if len(locks) != 1:
            raise ValueError('Source archive must contain one uv.lock')
        lock = tomllib.loads(tar.extractfile(locks[0]).read().decode())
    resources = wheel_resources(lock)
    source_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    blocks = ['  resource "' + r['name'] + '" do\n'
              + '    url ' + ruby_string(r['url']) + ', using: :nounzip\n'
              + '    sha256 "' + r['sha256'] + '"\n  end' for r in resources]
    template = (Path(__file__).with_name('pimux-preview.rb.in')).read_text()
    for key, value in {'SOURCE_URL': ruby_string(archive.as_uri()), 'SOURCE_SHA256': ruby_string(source_hash),
                       'SOURCE_COMMIT': ruby_string(commit), 'REVISION': str(revision),
                       'RESOURCES': '\n\n'.join(blocks)}.items():
        template = template.replace('@@' + key + '@@', value)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template)
    record = {'source_archive': str(archive), 'source_sha256': source_hash, 'source_commit': commit,
              'package_revision': revision, 'resources': resources, 'formula': str(output),
              'formula_sha256': hashlib.sha256(template.encode()).hexdigest(), 'published': False}
    output.with_suffix('.manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('commit')
    parser.add_argument('output', type=Path)
    parser.add_argument('--revision', type=int, default=1)
    args = parser.parse_args()
    print(json.dumps(render(args.archive, args.commit, args.revision, args.output), indent=2))
