from __future__ import annotations
import os
from pathlib import Path

import pytest

from valscanner.web.server import create_app
from valscanner.core.scanner import scan as run_scan
from valscanner.web.scan_registry import REGISTRY


@pytest.fixture(autouse=True)
def _reset_scan_registry():
    """Reset the global scan registry before each test."""
    REGISTRY._active_id = None
    REGISTRY._states.clear()
    yield


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
    return create_app(db_path)


@pytest.fixture
def app_populated(populated_db: str):
    return create_app(populated_db)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def client_populated(app_populated):
    from fastapi.testclient import TestClient
    return TestClient(app_populated)
