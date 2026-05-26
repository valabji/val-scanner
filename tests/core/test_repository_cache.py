"""Tests for valscanner.core.repository.cache.CacheMixin.

These exercise db_version, get/set/invalidate/warm_gui_cache against a real
SQLite repository so the SQL (including ON CONFLICT upsert) gets executed.
"""
from __future__ import annotations

import pytest

from valscanner.core.bootstrap import ensure_schema
from valscanner.core.db import repo_for, reset_repos
from valscanner.core.db_config import reset_engines


@pytest.fixture
def repo(tmp_path):
    url = f"sqlite:///{tmp_path / 'cache.db'}"
    ensure_schema(url)
    r = repo_for(url)
    yield r
    reset_repos()
    reset_engines()


def _seed_scan(repo, *, root: str = "/data", n_files: int = 1) -> int:
    sid = repo.create_scan(root, label="seed")
    for i in range(n_files):
        repo.insert_file({
            "scan_id":    sid,
            "path":       f"{root}/f{i}.txt",
            "filename":   f"f{i}.txt",
            "extension":  ".txt",
            "category":   "document",
            "size_bytes": 10 * (i + 1),
            "size_human": f"{10 * (i + 1)} B",
            "indexed_at": "2024-01-01 00:00:00",
        })
    repo.upsert_folder(
        scan_id=sid, path=root, file_count=n_files,
        total_bytes=10 * n_files, total_human=f"{10 * n_files} B",
        indexed_at="2024-01-01 00:00:00",
    )
    repo.update_scan_totals(sid, file_count=n_files,
                            total_bytes=10 * n_files,
                            total_human=f"{10 * n_files} B")
    return sid


# ─── db_version ────────────────────────────────────────────────────────────
#
# NOTE: as currently written, db_version()'s SQL references a non-existent
# column (`scans.indexed_at` — the real column is `scanned_at`). The query
# raises and the broad except returns "". These tests pin that current
# behaviour so any future fix shows up as a deliberate test change.

def test_db_version_returns_string(repo):
    assert isinstance(repo.db_version(), str)


def test_db_version_returns_empty_on_bad_query(repo):
    """SQL bug → exception → returns '' rather than crashing the GUI."""
    assert repo.db_version() == ""


# ─── get/set round-trip ────────────────────────────────────────────────────

def test_set_then_get_round_trip(repo):
    repo.set_gui_cache("k1", "v1", {"a": 1, "b": [2, 3]})
    assert repo.get_gui_cache("k1", "v1") == {"a": 1, "b": [2, 3]}


def test_get_returns_none_on_missing_key(repo):
    assert repo.get_gui_cache("never-set", "v1") is None


def test_get_returns_none_on_version_mismatch(repo):
    repo.set_gui_cache("k1", "v1", {"x": 1})
    assert repo.get_gui_cache("k1", "v2") is None


def test_set_overwrites_existing_key(repo):
    """ON CONFLICT(key) DO UPDATE — second write wins, even with a new version."""
    repo.set_gui_cache("k1", "v1", {"first": True})
    repo.set_gui_cache("k1", "v2", {"second": True})
    assert repo.get_gui_cache("k1", "v1") is None  # version moved
    assert repo.get_gui_cache("k1", "v2") == {"second": True}


# ─── invalidate ────────────────────────────────────────────────────────────

def test_invalidate_removes_all_entries(repo):
    repo.set_gui_cache("k1", "v1", {"a": 1})
    repo.set_gui_cache("k2", "v1", {"b": 2})
    repo.invalidate_gui_cache()
    assert repo.get_gui_cache("k1", "v1") is None
    assert repo.get_gui_cache("k2", "v1") is None


# ─── warm_gui_cache ────────────────────────────────────────────────────────
#
# Because db_version() currently returns "", warm_gui_cache() early-returns
# without populating anything. We test that the call is safe (no exception)
# AND drive the real population path by stubbing db_version() with a fixed
# fingerprint so the SQL underneath actually runs.

def test_warm_gui_cache_is_safe_on_broken_version(repo):
    """No crash even though db_version() returns ''."""
    repo.warm_gui_cache()  # must not raise


def test_warm_gui_cache_populates_when_version_resolves(repo, monkeypatch):
    _seed_scan(repo, n_files=3)
    monkeypatch.setattr(type(repo), "db_version", lambda self: "fp1")
    repo.warm_gui_cache()

    folder_cache = repo.get_gui_cache("folder_tree:all", "fp1")
    assert folder_cache["mode"] == "combined"
    assert any(r[0] == "/data" for r in folder_cache["rows"])

    file_cache = repo.get_gui_cache("file_list:all", "fp1")
    assert file_cache["total"] == 3
    assert file_cache["total_size"] == 60  # 10 + 20 + 30
    # Row shape: (path, filename, category, size_bytes, size_human, modified_at, tags, extra_meta)
    assert len(file_cache["rows"]) == 3
    assert file_cache["rows"][0][1].startswith("f")  # filename column


def test_warm_gui_cache_respects_page_size(repo, monkeypatch):
    _seed_scan(repo, n_files=5)
    monkeypatch.setattr(type(repo), "db_version", lambda self: "fp1")
    repo.warm_gui_cache(page_size=2)
    cache = repo.get_gui_cache("file_list:all", "fp1")
    assert cache["total"] == 5         # full count is unaffected
    assert len(cache["rows"]) == 2     # but rows are paged
