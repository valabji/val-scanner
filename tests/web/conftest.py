from __future__ import annotations

import tempfile
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


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def client_populated(app_populated):
    from fastapi.testclient import TestClient
    return TestClient(app_populated)


@pytest.fixture
def web_client():
    with tempfile.TemporaryDirectory() as scandir, tempfile.TemporaryDirectory() as dbdir:
        (Path(scandir) / "a.txt").write_text("hi")
        (Path(scandir) / "b.pdf").write_text("pdf")

        db_path = f"{dbdir}/web.db"
        run_scan(Path(scandir), db_path, compute_hash=False)

        from valscanner.web.server import create_app
        from fastapi.testclient import TestClient
        app = create_app(db_path)
        with TestClient(app) as c:
            yield c, db_path
