from __future__ import annotations

import os
import pytest

from valscanner.core.db_config import make_engine, reset_engines
from valscanner.core.schema import drop_all
from valscanner.core.repository import Repository
from valscanner.core.db import reset_repos


@pytest.fixture
def sqlite_repo():
    engine = make_engine("sqlite:///:memory:")
    repo = Repository(engine)
    yield repo
    drop_all(engine)
    reset_engines()
    reset_repos()


@pytest.fixture(scope="session")
def pg_url():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgres://")):
        pytest.skip("DATABASE_URL not set to a PostgreSQL instance")
    return url


@pytest.fixture
def pg_repo(pg_url):
    engine = make_engine(pg_url)
    drop_all(engine)
    repo = Repository(engine)
    yield repo
    drop_all(engine)
    reset_engines()
    reset_repos()


def sample_file(scan_id: int, path: str = "/tmp/a.txt") -> dict:
    return {
        "scan_id":    scan_id,
        "path":       path,
        "filename":   path.split("/")[-1],
        "extension":  ".txt",
        "category":   "document",
        "size_bytes": 1024,
        "size_human": "1.0 KB",
        "indexed_at": "2024-01-01 00:00:00",
    }
