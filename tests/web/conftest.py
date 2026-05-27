from __future__ import annotations

from pathlib import Path

import pytest

from valscanner.core.scanner import scan as run_scan


@pytest.fixture
def fixture_tree(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    (root / "a.txt").write_text("alpha")
    (root / "b.txt").write_text("bravo")
    sub = root / "nested"
    sub.mkdir()
    (sub / "c.txt").write_text("charlie")
    return root


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


@pytest.fixture
def populated_db(db_path: str, fixture_tree: Path) -> str:
    run_scan(fixture_tree, db_path, compute_hash=False, label="test")
    return db_path


@pytest.fixture
def app(db_path: str):
    from valscanner.web.server import create_app
    return create_app(db_path)


@pytest.fixture
def app_populated(populated_db: str):
    from valscanner.web.server import create_app
    return create_app(populated_db)


def _drain_active_scans() -> None:
    from valscanner.web.scan_registry import REGISTRY

    active_id = REGISTRY.active_id()
    if active_id is None:
        return
    state = REGISTRY.get(active_id)
    if state is None:
        return
    state.cancel_event.set()
    if state.thread is not None:
        state.thread.join(timeout=10)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c
    _drain_active_scans()


@pytest.fixture
def client_populated(app_populated):
    from fastapi.testclient import TestClient
    with TestClient(app_populated) as c:
        yield c
    _drain_active_scans()


@pytest.fixture
def web_client(tmp_path: Path):
    scandir = tmp_path / "scan"
    scandir.mkdir()
    (scandir / "a.txt").write_text("hi")
    (scandir / "b.pdf").write_text("pdf")

    db_path = str(tmp_path / "web.db")
    run_scan(scandir, db_path, compute_hash=False)

    from valscanner.web.server import create_app
    from fastapi.testclient import TestClient
    app = create_app(db_path)
    with TestClient(app) as c:
        yield c, db_path
