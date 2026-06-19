"""Navigation prefetch cache: the next hop is warmed in the background.

Builds a small scanned tree, drives MainWindow's browser navigation, and
asserts that immediate children / parent / scan-root hops are prefetched and
then served from cache (no fresh BrowserLoadWorker spawned).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest


def _pump(app, predicate, timeout: float = 8.0) -> bool:
    """Spin the Qt event loop until ``predicate()`` is true or we time out."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


@pytest.fixture
def scanned_db(tmp_path):
    """Scan a small tree (root + two subfolders) into a fresh SQLite DB."""
    from valscanner.core.scanner import scan

    proj = tmp_path / "proj"
    (proj / "sub1").mkdir(parents=True)
    (proj / "sub2").mkdir(parents=True)
    (proj / "a.txt").write_text("a")
    (proj / "b.txt").write_text("b")
    (proj / "sub1" / "c.txt").write_text("c")
    (proj / "sub1" / "d.txt").write_text("d")
    (proj / "sub2" / "e.txt").write_text("e")

    db_path = tmp_path / "scan.db"
    url = f"sqlite:///{db_path}"
    scan(proj, url, compute_hash=False)
    return db_path, str(proj)


@pytest.mark.usefixtures("qapp")
def test_prefetch_warms_and_serves_next_hop(scanned_db, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from valscanner.gui.window import MainWindow

    db_path, proj = scanned_db
    app = QApplication.instance()

    win = MainWindow()
    try:
        # Neutralise the deferred default-DB autoload so it can't race our load.
        monkeypatch.setattr(win, "_load_url", lambda *a, **k: None)
        app.processEvents()  # flush the (now no-op) startup singleShot
        win._db_path = str(db_path)
        win._active_scan_id = 0
        win._load_from_db()

        root_key = win._browser_cache_key("", False)
        proj_key = win._browser_cache_key(proj, False)

        # Root view loads, then the scan root (the only child hop) is prefetched.
        assert _pump(app, lambda: proj_key in win._browser_cache), (
            "scan root was never prefetched from the root view"
        )
        assert root_key in win._browser_cache

        # Drilling into the scan root must be a cache hit: no new loader spawned.
        win._navigate_to(proj)
        assert win._browser_worker is None
        assert win._browser_path == proj
        assert win._all_rows  # folders + files rendered immediately

        # From the scan root, the parent (root) and each child subdir warm up.
        sub1 = str(Path(proj) / "sub1")
        sub1_key = win._browser_cache_key(sub1, False)
        assert _pump(app, lambda: sub1_key in win._browser_cache), (
            "child subfolder was never prefetched from the scan-root view"
        )
        assert root_key in win._browser_cache  # parent hop stays warm

        # Navigating into the warmed child is again instant.
        win._navigate_to(sub1)
        assert win._browser_worker is None
        assert win._browser_path.endswith("sub1")
    finally:
        win._clear_browser_cache()
        win.close()
        win.deleteLater()


@pytest.mark.usefixtures("qapp")
def test_cache_cleared_on_db_reload(scanned_db, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from valscanner.gui.window import MainWindow

    db_path, proj = scanned_db
    app = QApplication.instance()

    win = MainWindow()
    try:
        monkeypatch.setattr(win, "_load_url", lambda *a, **k: None)
        app.processEvents()
        win._db_path = str(db_path)
        win._active_scan_id = 0
        win._load_from_db()

        proj_key = win._browser_cache_key(proj, False)
        assert _pump(app, lambda: proj_key in win._browser_cache)

        # A reload (scan switch / DB change funnels through here) drops the cache.
        win._load_from_db()
        assert proj_key not in win._browser_cache
        assert not win._prefetch_workers
    finally:
        win._clear_browser_cache()
        win.close()
        win.deleteLater()
