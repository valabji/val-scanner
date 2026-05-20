from __future__ import annotations

import pytest

from valscanner.core.db import reset_repos
from valscanner.core.db_config import reset_engines


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path, monkeypatch):
    """Point app_settings at an empty config dir for every test.

    Bypasses keyring entirely — password goes to/from the settings blob so
    tests never touch the developer's OS keychain or block on a GUI prompt.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from valscanner.core import app_settings

    # Route password through the blob so keyring is never called.
    def _noop_set(blob: dict, value: str) -> None:
        blob["pg_password"] = value

    def _noop_get(blob: dict) -> str:
        return blob.get("pg_password", "")

    monkeypatch.setattr(app_settings, "_set_pg_password", _noop_set)
    monkeypatch.setattr(app_settings, "_get_pg_password", _noop_get)
    monkeypatch.setattr(app_settings, "_warned_no_keyring", False, raising=False)

    yield

    reset_repos()
    reset_engines()
