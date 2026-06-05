"""Tests for valscanner.core.db — legacy wrappers + the Repository cache.

These wrappers are thin pass-throughs to Repository methods, but they also
own (a) the per-URL Repository cache and (b) the human-readable formatting
emitted by ``search_db`` / ``print_summary``.
"""
from __future__ import annotations

import pytest

from valscanner.core import db as db_mod
from valscanner.core.bootstrap import ensure_schema
from valscanner.core.db import (
    delete_analysis_run, delete_scan, list_analysis_runs, list_scans,
    load_analysis_run, print_summary, search_db, repo_for, reset_repos,
    save_analysis_run,
)
from valscanner.core.db_config import reset_engines


@pytest.fixture
def db_url(tmp_path):
    """A freshly-bootstrapped SQLite URL with isolated engine + repo caches."""
    url = f"sqlite:///{tmp_path / 'wrappers.db'}"
    ensure_schema(url)
    yield url
    reset_repos()
    reset_engines()


def _seed_one_file(url: str, *, root: str = "/data") -> tuple[int, int]:
    repo = repo_for(url)
    sid = repo.create_scan(root, label="seeded")
    fid = repo.insert_file({
        "scan_id":    sid,
        "path":       f"{root}/readme.txt",
        "filename":   "readme.txt",
        "extension":  ".txt",
        "category":   "document",
        "size_bytes": 42,
        "size_human": "42 B",
        "indexed_at": "2024-01-01 00:00:00",
        "tags":       "documents, readme",
    })
    repo.upsert_folder(
        scan_id=sid, path=root, file_count=1,
        total_bytes=42, total_human="42 B", indexed_at="2024-01-01 00:00:00",
    )
    repo.update_scan_totals(sid, file_count=1, total_bytes=42, total_human="42 B")
    return sid, fid


# ─── repo_for / reset_repos ─────────────────────────────────────────────────

def test_repo_for_caches_per_url(db_url):
    r1 = repo_for(db_url)
    r2 = repo_for(db_url)
    assert r1 is r2  # Same URL → cached instance


def test_repo_for_distinct_urls_get_distinct_repos(tmp_path):
    url_a = f"sqlite:///{tmp_path / 'a.db'}"
    url_b = f"sqlite:///{tmp_path / 'b.db'}"
    ensure_schema(url_a)
    ensure_schema(url_b)
    try:
        assert repo_for(url_a) is not repo_for(url_b)
    finally:
        reset_repos()
        reset_engines()


def test_reset_repos_clears_cache(db_url):
    r1 = repo_for(db_url)
    reset_repos()
    r2 = repo_for(db_url)
    assert r1 is not r2  # Reset rebuilt the Repository


def test_repo_for_uses_default_when_none(monkeypatch, tmp_path):
    """A None argument must resolve via active_url(), not crash."""
    fake = f"sqlite:///{tmp_path / 'def.db'}"
    monkeypatch.setattr(db_mod, "active_url", lambda v=None: fake)
    ensure_schema(fake)
    try:
        repo = repo_for(None)
        assert repo is not None
    finally:
        reset_repos()
        reset_engines()


# ─── list_scans / delete_scan ───────────────────────────────────────────────

def test_list_scans_empty(db_url):
    assert list_scans(db_url) == []


def test_list_and_delete_scan_round_trip(db_url):
    sid, _fid = _seed_one_file(db_url)
    rows = list_scans(db_url)
    assert len(rows) == 1
    assert rows[0]["id"] == sid

    delete_scan(db_url, sid)
    assert list_scans(db_url) == []


# ─── analysis-run wrappers ──────────────────────────────────────────────────

def test_save_list_load_delete_analysis_run(db_url):
    sid, _fid = _seed_one_file(db_url)
    run_id = save_analysis_run(
        db_url, min_files=3, threshold=0.4,
        scope_scan_ids=[sid], scope_label="ad-hoc",
        duration_ms=11,
        results=[{"score": 0.95, "scan_id_a": sid, "scan_id_b": sid}],
        filters={"skip_hidden_files": True},
    )
    assert isinstance(run_id, int) and run_id > 0

    rows = list_analysis_runs(db_url)
    assert len(rows) == 1 and rows[0]["id"] == run_id

    loaded = load_analysis_run(db_url, run_id)
    assert loaded is not None
    assert loaded["scope_scan_ids"] == [sid]
    # save_analysis_run merges scope_scan_ids into filters before persisting
    assert loaded["filters"]["skip_hidden_files"] is True
    assert loaded["filters"]["scope_scan_ids"] == [sid]
    assert loaded["results"][0]["score"] == 0.95

    delete_analysis_run(db_url, run_id)
    assert list_analysis_runs(db_url) == []


def test_load_analysis_run_missing_returns_none(db_url):
    assert load_analysis_run(db_url, 9_999) is None


# ─── search_db ─────────────────────────────────────────────────────────────

def test_search_db_prints_hits_and_count(db_url, capsys):
    _seed_one_file(db_url)
    search_db(db_url, "readme")
    out = capsys.readouterr().out
    assert "Searching for: 'readme'" in out
    assert "readme.txt" in out
    assert "Found 1 result" in out


def test_search_db_no_hits_still_prints_banner(db_url, capsys):
    _seed_one_file(db_url)
    search_db(db_url, "this-will-not-match-anything-12345")
    out = capsys.readouterr().out
    assert "Searching for:" in out
    assert "Found 0 result(s)" in out


# ─── print_summary ──────────────────────────────────────────────────────────

def test_print_summary_single_scan(db_url, capsys):
    _seed_one_file(db_url)
    print_summary(db_url)
    out = capsys.readouterr().out
    assert "Total files indexed" in out
    assert "Total size" in out
    assert "Files by category" in out
    assert "Top 10 most common extensions" in out
    assert "Top 10 tags" in out
    assert "Top 10 largest folders" in out
    # Per-scan header is only emitted when there is MORE than one scan
    assert "Scans in database" not in out


def test_print_summary_multiple_scans_lists_them(db_url, capsys):
    _seed_one_file(db_url, root="/data1")
    _seed_one_file(db_url, root="/data2")
    print_summary(db_url)
    out = capsys.readouterr().out
    assert "Scans in database: 2" in out
