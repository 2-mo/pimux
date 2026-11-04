"""Pure packaging/provenance checks; never invoke the user's Homebrew or tmux."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'packaging/homebrew' / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_formula_uses_exact_archive_and_locked_portable_dependencies(tmp_path):
    render = module('render')
    archive = tmp_path / 'source archive.tar.gz'
    commit = 'a' * 40
    with tarfile.open(archive, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': commit}) as tar:
        data = (ROOT / 'uv.lock').read_bytes()
        info = tarfile.TarInfo('pimux/uv.lock'); info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    output = tmp_path / 'tap/Formula/pimux-preview.rb'
    manifest = render.render(archive, commit, 1, output)
    assert manifest['source_sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert archive.as_uri() in output.read_text()
    assert {r['name'] for r in manifest['resources']} == {
        'blessed', 'jinxed', 'wcwidth', 'rich', 'markdown-it-py', 'mdurl', 'pygments'}
    assert '--no-index' in output.read_text() and '--no-deps' in output.read_text()
    assert '@@' not in output.read_text()
    with pytest.raises(ValueError, match='provenance'):
        render.render(archive, 'b' * 40, 1, output)


def test_new_unreviewed_dependency_marker_is_rejected():
    render = module('render')
    lock = tomllib.loads((ROOT / 'uv.lock').read_text())
    package = next(p for p in lock['package'] if p['name'] == 'rich')
    package['dependencies'][0]['marker'] = "python_version < '3.99'"
    with pytest.raises(ValueError, match='marker'):
        render.wheel_resources(lock)


@pytest.fixture
def keg(tmp_path, monkeypatch):
    probe = module('tmux_source')
    cellar = tmp_path / 'brew/Cellar/tmux'
    binary = cellar / '3.1c/bin/tmux'; binary.parent.mkdir(parents=True)
    binary.write_text('fixture only')
    receipt = binary.parent.parent / 'INSTALL_RECEIPT.json'
    receipt.write_text(json.dumps({'source': {'tap': 'homebrew/core'}}))
    opt = tmp_path / 'brew/opt/tmux'; opt.parent.mkdir(parents=True); opt.symlink_to(binary.parent.parent)
    calls = []

    def query(argv):
        calls.append(argv)
        if argv == [str(binary), '-V']: return 'tmux 3.1c'
        if argv == ['/fixture/brew', '--cellar', 'tmux']: return str(cellar)
        if argv == ['/fixture/brew', '--prefix', '--installed', 'tmux']: return str(opt)
        pytest.fail(f'Unexpected operation: {argv}')
    monkeypatch.setattr(probe, 'query', query)
    return probe, binary, receipt, opt, calls


def test_brew_layout_reports_manual_command_without_claiming_binary_integrity(keg):
    probe, binary, _, _, calls = keg
    result = probe.inspect(binary, '/fixture/brew')
    assert result['upgrade_argv'] is None and result['binary_content_verified'] is False
    assert result['manual_upgrade_argv'] == ['/fixture/brew', 'upgrade', '--formula', 'tmux']
    assert result['version_output'] == 'tmux 3.1c'
    assert result['minimum'] == '3.2' and result['supported'] is False
    assert result['requires_confirmation'] and not result['running_server_checked']
    assert all('upgrade' not in command for command in calls)


def test_replaced_binary_with_unchanged_receipt_cannot_enable_automatic_upgrade(keg):
    probe, binary, _, _, _ = keg
    binary.write_text('manually replaced executable with the same version banner')
    result = probe.inspect(binary, '/fixture/brew')
    assert result['upgrade_argv'] is None
    assert result['binary_content_verified'] is False
    assert 'manually replaced' in result['note']


@pytest.mark.parametrize('kind', ['custom_tap', 'symlink_receipt', 'missing_receipt', 'old_keg', 'bad_json', 'bad_type'])
def test_source_uncertainty_cannot_propose_an_upgrade(keg, kind):
    probe, binary, receipt, opt, _ = keg
    if kind == 'custom_tap': receipt.write_text('{"source":{"tap":"custom/tap"}}')
    elif kind == 'bad_json': receipt.write_text('{')
    elif kind == 'bad_type': receipt.write_text('{"source":[]}')
    elif kind == 'missing_receipt': receipt.unlink()
    elif kind == 'symlink_receipt':
        other = receipt.with_name('other'); receipt.rename(other); receipt.symlink_to(other)
    else:
        other = binary.parents[2] / '3.8/bin/tmux'; other.parent.mkdir(parents=True); other.touch()
        opt.unlink(); opt.symlink_to(other.parent.parent)
    assert probe.inspect(binary, '/fixture/brew')['upgrade_argv'] is None


def test_custom_executable_is_not_treated_as_brew_package(keg, tmp_path, monkeypatch):
    probe, _, _, _, _ = keg
    binary = tmp_path / 'custom/tmux'; binary.parent.mkdir(); binary.touch()
    original = probe.query
    monkeypatch.setattr(probe, 'query', lambda argv: 'tmux 3.1' if argv == [str(binary), '-V'] else original(argv))
    assert probe.inspect(binary, '/fixture/brew')['upgrade_argv'] is None


def test_current_supported_version_does_not_offer_upgrade(keg, monkeypatch):
    probe, binary, _, _, _ = keg
    original = probe.query
    monkeypatch.setattr(probe, 'query', lambda argv: 'tmux 3.2a' if argv == [str(binary), '-V'] else original(argv))
    result = probe.inspect(binary, '/fixture/brew')
    assert result['supported'] is True and result['upgrade_argv'] is None
