"""Never let terminal tests read or modify the developer's home or tmux client."""

import pytest


@pytest.fixture(autouse=True)
def isolated_user_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("isolated-home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
