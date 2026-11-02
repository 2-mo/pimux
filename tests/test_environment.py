"""Environment persistence and real Bash behavior, including literal values."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess

import pytest
from rich.console import Console

import environment
from environment_ui import EnvironmentPanel

SOURCE = Path(__file__).resolve().parents[1]


def test_environment_shell_applies_literals_preserves_manual_values_and_restores_exports(tmp_path):
    marker = tmp_path / "must-not-run"
    env = dict(os.environ, PATH=f'{SOURCE / "bin"}:{os.environ["PATH"]}',
               PIMUX_ENV_FILE=str(tmp_path / "environment.json"),
               PIMUX_PROXY_FILE=str(tmp_path / "proxy"),
               PIMUX_LANGUAGE_FILE=str(tmp_path / "language"),
               TEST_LITERAL=f"$(touch '{marker}') $HOME 'quoted'\nnext line")
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    script = r'''set -eu
source "$1/bin/pimux"
source "$1/lib/environment.bash"
FOO=original-local
export -n FOO
export BAR=original-export
unset NEW_VAR
pimux_environment_shell_init
pimux_environment_shell_init
load_proxy
pimux_proxy_shell_init
pimux env set FOO "$TEST_LITERAL"
[[ $FOO == "$TEST_LITERAL" ]]
bash -c '[[ $FOO == "$TEST_LITERAL" ]]'
export FOO=manual-override
pimux env set BAR changed
[[ $FOO == manual-override && $BAR == changed ]]
pimux env on FOO
[[ $FOO == "$TEST_LITERAL" ]]
pimux env off FOO
[[ ! -v FOO ]]
pimux env on FOO
[[ $FOO == "$TEST_LITERAL" ]]
pimux env reset FOO
[[ $FOO == original-local ]]
bash -c '[[ ! -v FOO ]]'
pimux env reset BAR
[[ $BAR == original-export ]]
bash -c '[[ $BAR == original-export ]]'
pimux env set NEW_VAR ''
[[ -v NEW_VAR && -z $NEW_VAR ]]
pimux env reset NEW_VAR
[[ ! -v NEW_VAR ]]
pimux env set key lower-case
pimux env set status still-a-value
[[ $key == lower-case && $status == still-a-value ]]
declare -i INTEGER=1
declare -n ALIAS=BAR
readonly LOCKED=keep
pimux env set INTEGER "$TEST_LITERAL"
pimux env set ALIAS "$TEST_LITERAL"
pimux env set LOCKED changed
[[ $INTEGER == 1 && $BAR == original-export && $LOCKED == keep ]]
printf invalid > "$PIMUX_ENV_FILE"
pimux_apply_environment
[[ $key == lower-case && $status == still-a-value ]]
set +e
false
pimux_environment_prompt
TEST_ENV_EXIT=$?
[[ $TEST_ENV_EXIT == 1 ]]
'''
    result = subprocess.run(["bash", "-c", script, "test", str(SOURCE)], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()


def test_environment_writes_are_atomic_private_and_merge_concurrent_edits(tmp_path, monkeypatch):
    path = tmp_path / "environment.json"
    monkeypatch.setenv("PIMUX_ENV_FILE", str(path))
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(environment.change, f"EXPERIMENT_{i}", "set", str(i)) for i in range(8)]
        for future in futures:
            future.result()
    data = environment.read_settings()
    assert len(data) == 8
    assert path.stat().st_mode & 0o777 == 0o600
    environment.change("EXPERIMENT_0", "off")
    assert environment.read_settings()["EXPERIMENT_0"] == {"enabled": False, "value": "0"}
    environment.change("EXPERIMENT_0", "reset")
    assert "EXPERIMENT_0" not in environment.read_settings()


@pytest.mark.parametrize("name", ["HOME", "PATH", "PIMUX_ENV_FILE", "TMUX", "PROMPT_COMMAND", "http_proxy", "9INVALID", "BAD-NAME"])
def test_runtime_and_proxy_variables_cannot_be_overridden(name, tmp_path, monkeypatch):
    monkeypatch.setenv("PIMUX_ENV_FILE", str(tmp_path / "environment.json"))
    with pytest.raises(ValueError):
        environment.change(name, "set", "value")
    assert not (tmp_path / "environment.json").exists()


def test_environment_editor_cancel_masking_toggle_and_inheritance(tmp_path, monkeypatch):
    path = tmp_path / "environment.json"
    monkeypatch.setenv("PIMUX_ENV_FILE", str(path))
    monkeypatch.delenv("HF_TOKEN", raising=False)
    view = EnvironmentPanel()
    view.refresh()
    view.on_key("n")
    for char in "HF_TOKEN":
        view.on_key(char)
    view.on_key("KEY_ENTER")
    for char in "private-test-token":
        view.on_key(char)
    console = Console(width=80)
    def rendered():
        lines = console.render_lines(view.render(80, 24), console.options, pad=False)
        assert len(lines) == 24
        return "".join(segment.text for line in lines for segment in line)
    assert "private-test-token" not in rendered()
    view.on_key("KEY_F2")
    assert "private-test-token" in rendered()
    view.on_key("KEY_F2")
    view.on_key("KEY_ENTER")
    assert environment.read_settings()["HF_TOKEN"]["value"] == "private-test-token"
    view.on_key(" ")
    assert not environment.read_settings()["HF_TOKEN"]["enabled"]
    view.on_key("i")
    assert "HF_TOKEN" not in environment.read_settings()
    view.on_key("n")
    view.on_key("K")
    view.on_key("KEY_ESCAPE")
    assert json.loads(path.read_text()) == {}


def test_secret_and_url_display_does_not_expose_credentials():
    assert "private-token" not in environment.display_value("HF_TOKEN", "private-token")
    assert "private-password" not in environment.display_value("DATABASE_URL", "postgres://user:private-password@host/db")


def test_environment_context_uses_the_selected_pane_and_never_the_popup_server(monkeypatch):
    import environment_ui

    monkeypatch.setenv("HF_HOME", "/daemon-value")
    monkeypatch.setattr(environment_ui, "read_settings", lambda: {})
    monkeypatch.setattr(environment_ui, "foreground_environment", lambda pid: {"HF_HOME": "/foreground-value"})
    result = [subprocess.CompletedProcess([], 0, "123\ton\n", "")]
    monkeypatch.setattr(environment_ui.subprocess, "run", lambda *args, **kwargs: result[0])
    view = EnvironmentPanel(("tmux", "/tmp/specific", "%12"))
    view.refresh()
    assert view.inherited == {"HF_HOME": "/foreground-value"} and view.integrated
    result[0] = subprocess.CompletedProcess([], 1, "", "pane exited")
    view.refresh()
    assert view.inherited == {} and not view.integrated
