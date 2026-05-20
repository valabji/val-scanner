from __future__ import annotations

from valscanner.core import app_settings


def test_active_url_expands_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    url = app_settings.active_url("~/data.db")
    assert "~" not in url
    assert url.startswith("sqlite:///")


def test_active_url_normalizes_windows_path():
    url = app_settings.active_url("C:\\\\foo\\\\bar.db")
    assert url.endswith("C:/foo/bar.db")


def test_active_url_url_encodes_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    app_settings.save({
        **app_settings.load(),
        "db_backend": "postgresql",
        "pg_user": "ali ce",
        "pg_password": "p@ss/word",
    })
    url = app_settings.active_url()
    assert "ali%20ce" in url and "p%40ss%2Fword" in url


def test_active_url_passthrough_for_full_urls():
    assert app_settings.active_url("postgresql://u:p@h/db") == "postgresql://u:p@h/db"
    assert app_settings.active_url("sqlite:///x.db") == "sqlite:///x.db"


def test_mask_url_hides_password():
    assert app_settings.mask_url("postgresql://u:secret@h:5432/d") == \
        "postgresql://u:***@h:5432/d"
    assert app_settings.mask_url("sqlite:////tmp/a.db") == "sqlite:////tmp/a.db"


def test_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    app_settings.save({
        **app_settings.load(),
        "sqlite_path": "~/scan.db",
        "pg_user": "u",
        "pg_password": "p",
    })
    s = app_settings.load()
    assert s["sqlite_path"] == "~/scan.db"
    assert s["pg_user"] == "u"
    assert s["pg_password"] == "p"
