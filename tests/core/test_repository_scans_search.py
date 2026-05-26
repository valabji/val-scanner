"""Gap-filling tests for ScansMixin and SearchMixin on SQLite.

The existing `test_repository_sqlite.py` covers create/list/delete and basic
FTS. This file targets the under-tested branches: status column handling,
interrupted-scan lookup, label updates, category-filtered search, LIKE
fallback when no FTS rows match.
"""
from __future__ import annotations

import pytest

from valscanner.core.bootstrap import ensure_schema
from valscanner.core.db import repo_for, reset_repos
from valscanner.core.db_config import reset_engines


@pytest.fixture
def repo(tmp_path):
    url = f"sqlite:///{tmp_path / 'scans.db'}"
    ensure_schema(url)
    r = repo_for(url)
    yield r
    reset_repos()
    reset_engines()


def _file(sid: int, **overrides) -> dict:
    base = {
        "scan_id":    sid,
        "path":       "/data/a.txt",
        "filename":   "a.txt",
        "extension":  ".txt",
        "category":   "document",
        "size_bytes": 10,
        "size_human": "10 B",
        "indexed_at": "2024-01-01 00:00:00",
    }
    base.update(overrides)
    return base


# ─── ScansMixin gaps ────────────────────────────────────────────────────────

def test_get_scan_returns_dict_with_columns(repo):
    sid = repo.create_scan("/data", label="alpha")
    row = repo.get_scan(sid)
    assert row is not None
    assert row["label"] == "alpha"
    assert row["root"] == "/data"


def test_get_scan_missing_returns_none(repo):
    assert repo.get_scan(99_999) is None


def test_update_scan_label(repo):
    sid = repo.create_scan("/data", label="old")
    repo.update_scan_label(sid, "renamed")
    assert repo.get_scan(sid)["label"] == "renamed"


def test_set_scan_status_then_find_interrupted(repo):
    sid = repo.create_scan("/data")
    repo.set_scan_status(sid, "running")
    assert repo.find_interrupted_scan("/data") == sid

    repo.set_scan_status(sid, "complete")
    assert repo.find_interrupted_scan("/data") is None


def test_find_interrupted_scan_unknown_root(repo):
    assert repo.find_interrupted_scan("/nope/never") is None


def test_find_interrupted_scan_picks_most_recent(repo):
    sid1 = repo.create_scan("/data")
    sid2 = repo.create_scan("/data")
    repo.set_scan_status(sid1, "running")
    repo.set_scan_status(sid2, "running")
    assert repo.find_interrupted_scan("/data") == sid2


def test_update_scan_totals_reflected_in_list(repo):
    sid = repo.create_scan("/data")
    repo.update_scan_totals(sid, file_count=7, total_bytes=999, total_human="999 B")
    row = repo.list_scans()[0]
    assert row["file_count"] == 7
    assert row["total_bytes"] == 999
    assert row["total_human"] == "999 B"


# ─── SearchMixin gaps ───────────────────────────────────────────────────────

def test_search_paged_no_filter_lists_everything(repo):
    sid = repo.create_scan("/data")
    repo.insert_file(_file(sid, path="/data/a.txt", filename="a.txt"))
    repo.insert_file(_file(sid, path="/data/b.txt", filename="b.txt"))
    out = repo.search_paged(sid)
    assert out["total"] == 2
    assert {i["filename"] for i in out["items"]} == {"a.txt", "b.txt"}


def test_search_paged_filters_by_category(repo):
    sid = repo.create_scan("/data")
    repo.insert_file(_file(sid, path="/data/a.txt", category="document"))
    repo.insert_file(_file(sid, path="/data/b.mp3", filename="b.mp3",
                           extension=".mp3", category="audio"))
    out = repo.search_paged(sid, category="audio")
    assert out["total"] == 1
    assert out["items"][0]["filename"] == "b.mp3"


def test_search_paged_pagination_offsets(repo):
    sid = repo.create_scan("/data")
    for i in range(5):
        repo.insert_file(_file(sid, path=f"/data/f{i}.txt", filename=f"f{i}.txt"))
    page1 = repo.search_paged(sid, page=1, page_size=2)
    page2 = repo.search_paged(sid, page=2, page_size=2)
    assert page1["total"] == page2["total"] == 5
    assert len(page1["items"]) == 2
    # Distinct items across pages
    assert {i["id"] for i in page1["items"]} & {i["id"] for i in page2["items"]} == set()


def test_search_paged_with_search_term_finds_match(repo):
    sid = repo.create_scan("/data")
    repo.insert_file(_file(sid, path="/data/readme.txt", filename="readme.txt"))
    repo.insert_file(_file(sid, path="/data/other.txt", filename="other.txt"))
    out = repo.search_paged(sid, search="readme")
    assert out["total"] >= 1
    assert any(i["filename"] == "readme.txt" for i in out["items"])


def test_search_paged_items_carry_has_thumbnail_flag(repo):
    sid = repo.create_scan("/data")
    fid = repo.insert_file(_file(sid, path="/data/img.png", filename="img.png",
                                  extension=".png", category="photo"))
    other = repo.insert_file(_file(sid, path="/data/plain.txt", filename="plain.txt"))
    repo.save_thumbnail(fid, b"jpeg-bytes", 64, 64)

    out = repo.search_paged(sid)
    by_id = {i["id"]: i for i in out["items"]}
    assert by_id[fid]["has_thumbnail"] is True
    assert by_id[other]["has_thumbnail"] is False


def test_search_files_returns_dict_rows(repo):
    sid = repo.create_scan("/data")
    repo.insert_file(_file(sid, path="/data/readme.txt", filename="readme.txt",
                           tags="docs, readme"))
    rows = repo.search_files("readme")
    assert len(rows) >= 1
    assert rows[0]["path"] == "/data/readme.txt"
    assert rows[0]["category"] == "document"


def test_search_files_no_match_returns_empty(repo):
    sid = repo.create_scan("/data")
    repo.insert_file(_file(sid))
    assert repo.search_files("nothing-matches-this-token-xyz") == []


def test_search_files_respects_limit(repo):
    sid = repo.create_scan("/data")
    for i in range(5):
        repo.insert_file(_file(sid, path=f"/data/readme{i}.txt",
                               filename=f"readme{i}.txt"))
    rows = repo.search_files("readme", limit=2)
    assert len(rows) == 2
