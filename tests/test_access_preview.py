import asyncio
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

import access_preview
import host_snapshot
import hosts


@pytest.fixture
def public(tmp_path):
    directory = tmp_path / '.ssh'
    directory.mkdir(mode=0o700)
    path = directory / 'fixture_key'
    subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(path)], check=True)
    return Path(str(path) + '.pub')


def test_only_public_candidates_are_opened_and_duplicate_fingerprints_collapse(tmp_path, public, monkeypatch):
    duplicate = public.with_name('duplicate.pub')
    duplicate.write_bytes(public.read_bytes())
    read_text = Path.read_text
    def checked(path, *args, **kwargs):
        assert path.suffix == '.pub'
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', checked)
    rows = access_preview.candidates(tmp_path)
    assert len(rows) == 1 and rows[0]['fingerprint'].startswith('SHA256:')
    with pytest.raises(ValueError): access_preview.public_key(public.with_suffix(''))


def test_authorization_inspection_preserves_existing_restricted_and_unrelated_entries(tmp_path, public, monkeypatch):
    monkeypatch.setattr(host_snapshot.pwd, 'getpwuid', lambda _uid: SimpleNamespace(pw_dir=str(tmp_path)))
    path = tmp_path / '.ssh/authorized_keys'
    contents = '# keep comment\nrestrict,command="echo limited" ' + public.read_text() + '# keep other authorization\n'
    path.write_text(contents)
    path.chmod(0o600)
    fingerprint = access_preview.public_key(public)['fingerprint']
    for _ in range(2):
        result = host_snapshot.access_state(fingerprint)
        assert result['state'] == 'present' and result['restricted']
        assert path.read_text() == contents
    path.chmod(0o666)
    with pytest.raises(host_snapshot.CapabilityError) as error: host_snapshot.access_state(fingerprint)
    assert error.value.status == 'permission_denied' and path.read_text() == contents


def test_missing_authorization_and_symlink_failures_never_create_or_replace_files(tmp_path, public, monkeypatch):
    monkeypatch.setattr(host_snapshot.pwd, 'getpwuid', lambda _uid: SimpleNamespace(pw_dir=str(tmp_path)))
    path = tmp_path / '.ssh/authorized_keys'
    fingerprint = access_preview.public_key(public)['fingerprint']
    assert host_snapshot.access_state(fingerprint)['state'] == 'absent'
    assert not path.exists()
    path.symlink_to(public)
    before = public.read_bytes()
    with pytest.raises(host_snapshot.CapabilityError): host_snapshot.access_state(fingerprint)
    assert path.is_symlink() and public.read_bytes() == before


def test_zero_or_multiple_public_keys_require_a_choice_without_connecting(tmp_path, public, monkeypatch):
    async def forbidden(*args): raise AssertionError('No target query before an unambiguous key choice')
    monkeypatch.setattr(hosts, 'fetch_host', forbidden)
    other = tmp_path / '.ssh/other'
    subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(other)], check=True)
    result = asyncio.run(access_preview.preview({'host_id': 'example'}, home=tmp_path))
    assert result['status'] == 'choose_public_key' and not result['writes_supported']
    result = asyncio.run(access_preview.preview({'host_id': 'example'}, home=tmp_path / 'empty'))
    assert result['status'] == 'no_public_key_available'
