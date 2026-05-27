"""Shared fixtures for GUI tests.

Forces headless Qt (QT_QPA_PLATFORM=offscreen) before any Qt import,
isolates QSettings to a tmp_path, and provides a qapp fixture so each
test gets a fresh QApplication or reuses the session-level one.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")

import pytest


@pytest.fixture(autouse=True)
def _isolate_qsettings(tmp_path, monkeypatch):
    """Redirect QSettings to tmp_path so tests don't touch real preferences."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    from PySide6.QtCore import QSettings, QCoreApplication

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(
        QSettings.IniFormat,
        QSettings.UserScope,
        str(tmp_path / "qsettings"),
    )
    QCoreApplication.setOrganizationName("valabji-test")
    QCoreApplication.setApplicationName("valscanner-test")

    yield


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication for the whole test session.

    On session teardown drain the thumbnail-cache worker so its QThread
    does not outlive the QApplication (which would SIGABRT at exit).
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    try:
        from valscanner.gui.models import _THUMB_CACHE
        _THUMB_CACHE.shutdown()
    except Exception:
        pass
    app.processEvents()


@pytest.fixture(autouse=True)
def _drain_events_after_test(request):
    """Process queued Qt events after each test so deleteLater() runs."""
    yield
    if "qapp" in request.fixturenames:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            for _ in range(3):
                app.processEvents()


@pytest.fixture
def fixture_db(tmp_path):
    """A minimal SQLite DB with the current schema."""
    from valscanner.core.bootstrap import ensure_schema

    db_path = tmp_path / "fixture.db"
    url = f"sqlite:///{db_path}"
    ensure_schema(url)
    return db_path
