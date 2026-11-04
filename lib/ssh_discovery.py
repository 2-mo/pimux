# pimux-managed: syntax-only VS Code/OpenSSH discovery; never invokes ssh or a shell.
"""Candidates are not resolved connection properties. OpenSSH owns evaluation."""
import glob
import fnmatch
import json
from pathlib import Path
import re
import shlex

ALIAS = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}')


def jsonc(source):
    """Remove comments/trailing commas only outside JSON strings."""
    output, i, quoted, escaped = [], 0, False, False
    while i < len(source):
        char = source[i]
        if quoted:
            output.append(char)
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == '"': quoted = False
            i += 1
        elif char == '"':
            quoted = True
            output.append(char)
            i += 1
        elif source[i:i+2] == '//':
            end = source.find('\n', i + 2)
            i = len(source) if end == -1 else end
        elif source[i:i+2] == '/*':
            end = source.find('*/', i + 2)
            if end == -1: raise ValueError('Unterminated JSONC comment')
            output.append(' ')
            i = end + 2
        else:
            output.append(char)
            i += 1
    source = ''.join(output)
    output, quoted, escaped = [], False, False
    for i, char in enumerate(source):
        if quoted:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == '"': quoted = False
        elif char == '"': quoted = True
        elif char == ',' and source[i+1:].lstrip().startswith(('}', ']')): continue
        output.append(char)
    return json.loads(''.join(output))


def expand_path(value, home, relative):
    value = value.replace('${userHome}', str(home)).replace('${env:HOME}', str(home))
    if value == '~': value = str(home)
    elif value.startswith('~/'): value = str(home / value[2:])
    if '$' in value or '%' in value or value.startswith('~') or '\x00' in value:
        raise ValueError('Unresolved path expansion')
    path = Path(value)
    return path if path.is_absolute() else relative / path


def settings_paths(home):
    roots = [home / 'Library/Application Support' / name / 'User' for name in ('Code', 'Code - Insiders', 'VSCodium')]
    roots += [home / '.config' / name / 'User' for name in ('Code', 'Code - Insiders', 'VSCodium')]
    for root in roots:
        yield root / 'settings.json'
        if (root / 'profiles').is_dir():
            yield from sorted((root / 'profiles').glob('*/settings.json'))


def discover(home=None, settings=None, config_files=None, capture=False):
    home = Path.home() if home is None else Path(home)
    notes, roots, candidates, public_paths = [], [], [], set()
    captured = {}
    settings_found = 0
    inspection_complete, execution_directives = True, False
    def note(kind, informational=False):
        nonlocal inspection_complete
        notes.append(kind)
        # Every skipped, unresolved or partially inspected input fails closed.
        # Only explicit informational observations preserve completeness.
        if not informational: inspection_complete = False
    if config_files is not None:
        roots = [Path(path) for path in config_files]
    else:
        roots = [home / '.ssh/config']
        for path in settings_paths(home) if settings is None else map(Path, settings):
            if not path.is_file(): continue
            settings_found += 1
            try:
                if path.stat().st_size > 1024 * 1024: raise ValueError('settings limit')
                value = jsonc(path.read_text()).get('remote.SSH.configFile')
                if value:
                    if not isinstance(value, str): raise ValueError('configFile type')
                    # VS Code documents an explicit path; do not guess relative semantics.
                    config = expand_path(value, home, home)
                    if not value.startswith(('~/', '/', '${userHome}', '${env:HOME}')):
                        note('relative_vscode_config_requires_explicit_path')
                    else: roots.append(config)
            except (OSError, ValueError, AttributeError): note('unreadable_or_invalid_vscode_settings')
    roots = list(dict.fromkeys(path.absolute() for path in roots))
    for root in roots:
        visited, active, aliases, identities = set(), set(), set(), set()
        def tokens(line):
            match = re.match(r'^\s*([A-Za-z][A-Za-z0-9]*)\s*(?:=\s*)?(.*)$', line)
            if not match:
                if line.strip() and not line.lstrip().startswith('#'): note('unparsed_ssh_line')
                return None
            directive, tail = match.groups()
            try:
                lexer = shlex.shlex(tail, posix=True)
                lexer.whitespace_split = True
                lexer.quotes = '"'
                return directive.lower(), list(lexer)
            except ValueError:
                note('unparsed_ssh_line'); return None
        def visit(path, explicit=True):
            nonlocal execution_directives
            try: path = path.resolve()
            except (OSError, RuntimeError):
                note('unresolvable_ssh_config'); return
            if path in active:
                note('include_cycle'); return
            if path in visited: return
            if len(visited) >= 128: note('include_limit'); return
            if path in identities:
                note('declared_identity_excluded'); return
            # A wildcard is not permission to open arbitrary files in ~/.ssh.
            # Extensionless/custom entries require a literal Include target.
            if not explicit and path.name not in {'config', 'ssh_config'} and path.suffix not in {'.conf', '.config', '.sshconfig'}:
                note('broad_include_unclassified_file_skipped'); return
            # Never follow common credential/public-key files accidentally matched by Include.
            if (path.name.startswith('id_') or path.suffix in {'.pem', '.key', '.pub'}
                    or path.name in {'authorized_keys', 'known_hosts'}):
                note('credential_file_excluded'); return
            visited.add(path)
            try:
                if path.stat().st_size > 256 * 1024: raise ValueError('SSH config limit')
                # No buffered prefetch: inspect only a short type/header line
                # before reading an explicitly selected configuration's body.
                with path.open('rb', buffering=0) as stream:
                    header = stream.readline(256)
                    if (b'PRIVATE KEY' in header or header.startswith(b'PuTTY-User-Key-File')
                            or any(byte < 9 or 13 < byte < 32 for byte in header)):
                        note('private_or_binary_file_excluded'); return
                    source = (header + stream.read(256 * 1024 + 1)).decode()
                    if len(source) > 256 * 1024: raise ValueError('SSH config limit')
            except (OSError, UnicodeError, ValueError): note('missing_or_unreadable_ssh_config'); return
            directives = [(index, item) for index, line in enumerate(source.splitlines()) if (item := tokens(line)) is not None]
            captured[str(path)] = dict(source=source, includes={})
            # Collect all declared key paths before following any Include,
            # including IdentityFile lines appearing later in this file.
            for _, (directive, values) in directives:
                if directive == 'identityfile' and len(values) == 1:
                    try: identities.add(expand_path(values[0], home, home / '.ssh').resolve())
                    except ValueError: pass
            active.add(path)
            try:
                for index, (directive, values) in directives:
                    if directive == 'host':
                        excluded = [value[1:] for value in values if value.startswith('!')]
                        for value in values:
                            if ALIAS.fullmatch(value) and not any(fnmatch.fnmatchcase(value, pattern) for pattern in excluded): aliases.add(value)
                            else: note('pattern_or_negation_not_a_target', informational=True)
                    elif directive == 'match':
                        note('match_not_evaluated', informational=True)
                        if any(value.lower() in {'exec', '!exec'} for value in values):
                            execution_directives = True
                            note('match_exec_not_executed', informational=True)
                    elif directive == 'proxycommand' and values != ['none']:
                        execution_directives = True
                        note('custom_proxy_command_requires_review', informational=True)
                    elif directive == 'identityfile':
                        if len(values) != 1:
                            note('unparsed_identity_hint'); continue
                        for value in values:
                            try:
                                key = expand_path(value, home, home / '.ssh')
                                public_paths.add(str(key if key.suffix == '.pub' else Path(str(key) + '.pub')))
                            except ValueError: note('dynamic_identity_not_resolved')
                    elif directive == 'include':
                        captured[str(path)]['includes'][index] = []
                        for value in values:
                            try: pattern = str(expand_path(value, home, home / '.ssh'))
                            except ValueError: note('dynamic_include_not_resolved'); continue
                            paths = sorted(glob.glob(pattern))
                            if not paths: note('missing_include')
                            # Count matches before resolving/deduplicating symlinks.
                            if len(paths) > 128: note('include_limit')
                            for child in paths[:128]:
                                visit(Path(child), explicit=not glob.has_magic(pattern))
                                captured[str(path)]['includes'][index].append(str(Path(child).resolve()))
            finally: active.remove(path)
        visit(root)
        for alias in sorted(aliases): candidates.append(dict(alias=alias, ssh_config=str(root)))
    result = dict(candidates=candidates, notes=sorted(set(notes)), settings_files=settings_found,
                config_files=len(roots), public_key_paths=sorted(public_paths),
                inspection_complete=inspection_complete,
                connection_allowed=inspection_complete and not execution_directives)
    if capture: result['_files'] = captured
    return result


def profile(alias, config):
    if not ALIAS.fullmatch(alias): raise ValueError('Select a concrete SSH alias')
    import hashlib
    host_id = 'ssh-' + hashlib.sha256((str(config) + '\0' + alias).encode()).hexdigest()[:16]
    return dict(host_id=host_id, name=alias, alias=alias, ssh_config=str(Path(config).absolute()),
                node_id=None, socket='pimux', timeout=10)


def resolve_alias(alias, config_files=None):
    rows = [row for row in discover(config_files=config_files)['candidates'] if row['alias'] == alias]
    if len(rows) != 1:
        raise ValueError('Select one discovered alias; use --ssh-config when configurations are ambiguous')
    return profile(alias, rows[0]['ssh_config'])


def inspected_configuration(config, destination=None, selected_identity=False):
    """Freeze the inspected Include closure; never let SSH re-open mutable inputs.

    OpenSSH still evaluates Host/Match and connection attributes. For an explicit
    selected identity, also produce a destination-only copy without additive
    IdentityFile/CertificateFile directives. Jump clients use the untouched copy.
    """
    import hashlib
    found = discover(config_files=[config], capture=True)
    if not found['connection_allowed']:
        raise ValueError('SSH configuration is incomplete or contains local execution directives')
    files = found['_files']
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    if destination is None: return digest
    destination = Path(destination)
    names = {name: destination / ('config-' + hashlib.sha256(name.encode()).hexdigest()[:24]) for name in files}
    def write_copies(mapping, omit_identities=False):
        for name, item in files.items():
            lines = item['source'].splitlines()
            for index, children in item['includes'].items():
                lines[index] = 'Include ' + ' '.join('"' + str(mapping[child]) + '"' for child in children)
            if omit_identities:
                lines = [line for line in lines if not re.match(r'^\s*(?:IdentityFile|CertificateFile)(?:\s|=)', line, re.I)]
            with mapping[name].open('x') as stream: stream.write('\n'.join(lines) + '\n')
            mapping[name].chmod(0o600)
    write_copies(names)
    root = str(Path(config).resolve())
    if selected_identity:
        projected = {name: path.with_name('selected-' + path.name) for name, path in names.items()}
        write_copies(projected, True)
        return str(projected[root]), str(names[root]), digest
    return str(names[root]), digest
