import json
from pathlib import Path
import subprocess

import pytest

import hosts
import ssh_discovery


def test_jsonc_preserves_quoted_slashes_comments_and_spaces():
    assert ssh_discovery.jsonc('''{ // comment
      "remote.SSH.configFile": "~/config with spaces", /* another */
      "url": "https://example.test/a//b", "quote": "\\\"/*literal*/", "array": [1,2,],
    }''') == {'remote.SSH.configFile': '~/config with spaces', 'url': 'https://example.test/a//b',
             'quote': '"/*literal*/', 'array': [1, 2]}


def test_default_profiles_custom_paths_include_cycles_and_match_are_only_read(tmp_path, monkeypatch):
    home = tmp_path / 'home with spaces'
    ssh = home / '.ssh'
    ssh.mkdir(parents=True)
    (ssh / 'config').write_text('Host default_alias * !excluded\nInclude parts/*.conf\nInclude absent.conf\n')
    (ssh / 'parts').mkdir()
    (ssh / 'parts/one.conf').write_text('Host included\nInclude config\nMatch exec "touch MUST_NOT_EXIST"\n IdentityFile ~/key with spaces\n')
    custom = home / 'custom config'
    custom.write_text('Host custom_alias\n ProxyJump jump_alias\n IdentityFile "~/key with spaces"\n')
    user = home / 'Library/Application Support/Code/User'
    user.mkdir(parents=True)
    (user / 'settings.json').write_text('{"remote.SSH.configFile":"${env:HOME}/custom config",}')
    profile = user / 'profiles/test'
    profile.mkdir(parents=True)
    profiled = home / 'profile config'
    profiled.write_text('Host profile_alias\n')
    (profile / 'settings.json').write_text('{/*profile*/"remote.SSH.configFile":"${userHome}/profile config"}')
    def prohibited(*args, **kwargs): raise AssertionError('Discovery must not execute commands or ssh -G')
    monkeypatch.setattr(subprocess, 'run', prohibited)
    monkeypatch.setattr(subprocess, 'Popen', prohibited)
    found = ssh_discovery.discover(home)
    assert {row['alias'] for row in found['candidates']} == {'default_alias', 'included', 'custom_alias', 'profile_alias'}
    assert found['settings_files'] == 2
    assert {'include_cycle', 'missing_include', 'match_exec_not_executed', 'pattern_or_negation_not_a_target'} <= set(found['notes'])
    assert str(home / 'key with spaces.pub') in found['public_key_paths']
    assert not (home / 'MUST_NOT_EXIST').exists()
    assert custom.read_text().count('ProxyJump jump_alias') == 1


def test_concrete_alias_selection_defers_every_connection_attribute_to_openssh(tmp_path):
    config = tmp_path / 'chosen config'
    original = 'Host selected\n HostName fictional.invalid\n User account\n ProxyJump gateway\n Match exec "exit 1"\n'
    config.write_text(original)
    host = ssh_discovery.resolve_alias('selected', [config])
    argv = hosts.ssh_command(host)
    assert argv[:4] == ['/usr/bin/ssh', '-F', str(config), '-T']
    assert argv[-2] == 'selected'
    assert not any(option in argv for option in ('ProxyCommand=none', 'ProxyJump=none', 'IdentityFile=none'))
    assert '-l' not in argv and '-p' not in argv
    assert 'StrictHostKeyChecking=yes' in argv and 'UpdateHostKeys=no' in argv
    assert config.read_text() == original
    with pytest.raises(ValueError): ssh_discovery.resolve_alias('*', [config])


def test_same_alias_in_two_profiles_requires_only_the_configuration_choice(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.write_text('Host repeated\n')
    second.write_text('Host repeated\n')
    with pytest.raises(ValueError, match='ambiguous'):
        ssh_discovery.resolve_alias('repeated', [first, second])
    assert ssh_discovery.resolve_alias('repeated', [first])['ssh_config'] == str(first)


def test_discovery_excludes_credential_files_from_broad_includes(tmp_path, monkeypatch):
    directory = tmp_path / '.ssh'
    directory.mkdir()
    (directory / 'config').write_text('Include *\nHost safe\n')
    (directory / 'id_ed25519').write_text('MUST NOT READ')
    open_file = Path.open
    def checked_read(path, *args, **kwargs):
        assert path.name != 'id_ed25519'
        return open_file(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', checked_read)
    found = ssh_discovery.discover(tmp_path)
    assert found['candidates'][0]['alias'] == 'safe'
    assert 'broad_include_unclassified_file_skipped' in found['notes']


def test_terminal_metadata_cannot_emit_control_sequences():
    assert '\x1b' not in hosts.safe_text('\x1b[2J')
    assert '\x9b' not in hosts.safe_text('\x9b2J')
    assert '\n' not in hosts.safe_text('two\nlines')


def test_negation_and_single_quotes_do_not_invent_connectable_aliases(tmp_path):
    config = tmp_path / 'config'
    config.write_text("Host blocked !blocked\nHost 'not-an-alias'\nHost exact other !oth*\n")
    found = ssh_discovery.discover(tmp_path, config_files=[config])
    assert [row['alias'] for row in found['candidates']] == ['exact']


def test_custom_identity_declared_after_include_is_excluded_before_open(tmp_path, monkeypatch):
    directory = tmp_path / '.ssh'; directory.mkdir()
    (directory / 'config').write_text('Include work_rsa\nInclude *.conf\nIdentityFile ~/.ssh/work_rsa\nHost fictional\n')
    (directory / 'work_rsa').write_text('PRIVATE MATERIAL MUST NOT BE OPENED')
    (directory / 'nested.conf').write_text('Include nested_secret\nIdentityFile ~/.ssh/nested_secret\nHost nested\n')
    (directory / 'nested_secret').write_text('PRIVATE MATERIAL MUST NOT BE OPENED')
    original = Path.open
    def checked(path, *args, **kwargs):
        assert path.name not in {'work_rsa', 'nested_secret'}
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', checked)
    result = ssh_discovery.discover(tmp_path)
    assert {row['alias'] for row in result['candidates']} == {'fictional', 'nested'}
    assert 'declared_identity_excluded' in result['notes']


def test_broad_include_never_opens_unclassified_custom_key_names(tmp_path, monkeypatch):
    directory = tmp_path / '.ssh'; directory.mkdir()
    (directory / 'config').write_text('Include *\nHost fictional\n')
    (directory / 'company_login').write_text('PRIVATE MATERIAL MUST NOT BE OPENED')
    original = Path.open
    def checked(path, *args, **kwargs):
        assert path.name != 'company_login'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', checked)
    assert ssh_discovery.discover(tmp_path)['candidates'][0]['alias'] == 'fictional'


def test_explicit_key_shaped_include_reads_only_the_type_header(tmp_path, monkeypatch):
    directory = tmp_path / '.ssh'; directory.mkdir()
    (directory / 'config').write_text('Include misplaced.conf\nHost fictional\n')
    path = directory / 'misplaced.conf'
    path.write_text('-----BEGIN OPENSSH PRIVATE KEY-----\nPRIVATE BODY MUST NOT BE READ\n')
    original = Path.open
    class HeaderOnly:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def readline(self, size): return b'-----BEGIN OPENSSH PRIVATE KEY-----\n'
        def read(self, *args): raise AssertionError('Private key body read')
    def checked(candidate, *args, **kwargs):
        return HeaderOnly() if candidate == path else original(candidate, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', checked)
    assert 'private_or_binary_file_excluded' in ssh_discovery.discover(tmp_path)['notes']


@pytest.mark.parametrize('hidden', ['ProxyCommand echo NEVER_EXECUTED', 'Match exec "touch NEVER_EXECUTED"'])
@pytest.mark.parametrize('case', ['credential_name', 'symlink_glob_limit', 'cycle', 'invalid_line'])
def test_any_incomplete_scan_blocks_connection_before_ssh(tmp_path, monkeypatch, case, hidden):
    import asyncio
    config = tmp_path / 'config'
    if case == 'credential_name':
        child = tmp_path / 'id_transport.conf'
        child.write_text(hidden + '\n')
        config.write_text(f'Host fictional\nInclude "{child}"\n')
    elif case == 'symlink_glob_limit':
        parts = tmp_path / 'parts'; parts.mkdir()
        shared = tmp_path / 'shared.conf'; shared.write_text('# harmless\n')
        for index in range(128): (parts / f'{index:03}.conf').symlink_to(shared)
        (parts / '999.conf').write_text(hidden + '\n')
        config.write_text(f'Host fictional\nInclude "{parts}/*.conf"\n')
    elif case == 'cycle':
        config.write_text(f'Host fictional\nInclude "{config}"\n')
    else: config.write_text('Host fictional\n!invalid syntax\n')
    found = ssh_discovery.discover(config_files=[config])
    assert not found['inspection_complete'] and not found['connection_allowed']
    if case == 'symlink_glob_limit': assert 'include_limit' in found['notes']
    async def prohibited(*args, **kwargs): raise AssertionError('Incomplete config reached SSH')
    monkeypatch.setattr(hosts, 'exchange', prohibited)
    row = asyncio.run(hosts.fetch_host(ssh_discovery.profile('fictional', config)))
    assert row['status'] == 'configuration_error'


@pytest.mark.parametrize('directive', ['ProxyCommand echo NEVER_EXECUTED', 'Match exec "touch NEVER_EXECUTED"'])
def test_complete_scan_rejects_local_execution_directives(tmp_path, monkeypatch, directive):
    import asyncio
    config = tmp_path / 'config'
    config.write_text('Host fictional\n' + directive + '\n')
    found = ssh_discovery.discover(config_files=[config])
    assert found['inspection_complete'] and not found['connection_allowed']
    async def prohibited(*args, **kwargs): raise AssertionError('Execution directive reached SSH')
    monkeypatch.setattr(hosts, 'exchange', prohibited)
    assert asyncio.run(hosts.fetch_host(ssh_discovery.profile('fictional', config)))['status'] == 'configuration_error'
