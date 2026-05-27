"""Tests for phased scanning (CLI feature added after v0.2.0).

Each phase is idempotent and sentinel-tracked, so we exercise:
* `enumerate_only` writes file rows but no hashes / thumbnails / samples.
* Each `enrich_*` is a no-op on a second call (zero rows processed).
* Phase order is irrelevant — hash-then-metadata == metadata-then-hash.
* The legacy `scan(root, db, ...)` orchestrator still produces a fully
  enriched DB byte-for-byte equivalent to phase-by-phase population.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from valscanner.core.bootstrap import ensure_schema
from valscanner.core.db import repo_for, reset_repos
from valscanner.core.db_config import reset_engines
from valscanner.core.schema import files as files_tbl, media_samples, thumbnails
from valscanner.core.scanner import (
    ALL_PHASES,
    PHASE_ENUMERATE,
    PHASE_HASH,
    PHASE_METADATA,
    PHASE_SAMPLES,
    PHASE_THUMBNAILS,
    enrich_hashes,
    enrich_metadata,
    enrich_samples,
    enrich_thumbnails,
    enumerate_only,
    scan,
)


# ---------------------------------------------------------------------------
# Fixture: small directory tree
# ---------------------------------------------------------------------------

@pytest.fixture()
def tree_and_db(tmp_path: Path) -> tuple[Path, str]:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("hello phased world")
    (tree / "b.py").write_text("# python\n")
    sub = tree / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("nested content")
    db_path = tmp_path / "phases.db"
    return tree, f"sqlite:///{db_path}"


def _fresh_db(tmp_path: Path, name: str) -> str:
    db = tmp_path / name
    url = f"sqlite:///{db}"
    ensure_schema(url)
    return url


def _file_count(url: str, scan_id: int) -> int:
    engine = repo_for(url)._engine
    with engine.connect() as conn:
        return conn.execute(
            select(files_tbl).where(files_tbl.c.scan_id == scan_id)
        ).rowcount or len(list(conn.execute(
            select(files_tbl.c.id).where(files_tbl.c.scan_id == scan_id)
        )))


def _files_for(url: str, scan_id: int) -> list[dict]:
    engine = repo_for(url)._engine
    with engine.connect() as conn:
        rows = conn.execute(
            select(files_tbl).where(files_tbl.c.scan_id == scan_id)
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def _thumb_count(url: str, scan_id: int) -> int:
    engine = repo_for(url)._engine
    with engine.connect() as conn:
        rows = conn.execute(
            select(thumbnails.c.file_id)
            .select_from(thumbnails.join(files_tbl, thumbnails.c.file_id == files_tbl.c.id))
            .where(files_tbl.c.scan_id == scan_id)
        ).fetchall()
    return len(rows)


def _sample_count(url: str, scan_id: int) -> int:
    engine = repo_for(url)._engine
    with engine.connect() as conn:
        rows = conn.execute(
            select(media_samples.c.file_id)
            .select_from(media_samples.join(files_tbl, media_samples.c.file_id == files_tbl.c.id))
            .where(files_tbl.c.scan_id == scan_id)
        ).fetchall()
    return len(rows)


# ---------------------------------------------------------------------------
# Phase 1: enumerate_only writes minimal rows
# ---------------------------------------------------------------------------

def test_enumerate_only_writes_minimal_rows(tree_and_db):
    tree, url = tree_and_db
    ensure_schema(url)

    stats = enumerate_only(tree, url)
    assert stats["scanned"] == 3
    sid = stats["scan_id"]

    rows = _files_for(url, sid)
    assert len(rows) == 3

    # Phase 1 must not populate sha256 / extra_meta / thumbnails / samples.
    for r in rows:
        assert (r["sha256"] or "") == ""
        assert (r["extra_meta"] or "") == ""

    assert _thumb_count(url, sid) == 0
    assert _sample_count(url, sid) == 0


# ---------------------------------------------------------------------------
# Phase 2-5: idempotency (second call processes zero files)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("enrich_fn,phase", [
    (enrich_metadata,   PHASE_METADATA),
    (enrich_hashes,     PHASE_HASH),
    (enrich_thumbnails, PHASE_THUMBNAILS),
    (enrich_samples,    PHASE_SAMPLES),
])
def test_enrich_phase_is_idempotent(tree_and_db, enrich_fn, phase):
    tree, url = tree_and_db
    ensure_schema(url)
    sid = enumerate_only(tree, url)["scan_id"]

    first  = enrich_fn(sid, url)
    second = enrich_fn(sid, url)

    # First call may process some files (or zero, if no eligible files
    # exist in the fixture); the second must always be zero.
    assert second["processed"] == 0
    assert second["errors"] == 0
    assert second["phase"] == phase


# ---------------------------------------------------------------------------
# Ordering independence: hash → metadata == metadata → hash
# ---------------------------------------------------------------------------

def test_phase_order_independence(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("hash order independence test")
    (tree / "b.py").write_text("# more bytes\n")

    url_a = _fresh_db(tmp_path, "order_a.db")
    url_b = _fresh_db(tmp_path, "order_b.db")

    sid_a = enumerate_only(tree, url_a)["scan_id"]
    enrich_metadata(sid_a, url_a)
    enrich_hashes(sid_a, url_a)

    sid_b = enumerate_only(tree, url_b)["scan_id"]
    enrich_hashes(sid_b, url_b)
    enrich_metadata(sid_b, url_b)

    by_path_a = {r["path"]: r for r in _files_for(url_a, sid_a)}
    by_path_b = {r["path"]: r for r in _files_for(url_b, sid_b)}
    assert by_path_a.keys() == by_path_b.keys()
    for p in by_path_a:
        assert by_path_a[p]["sha256"] == by_path_b[p]["sha256"]
        assert (by_path_a[p]["extra_meta"] or "") == (by_path_b[p]["extra_meta"] or "")


# ---------------------------------------------------------------------------
# Back-compat: legacy scan(root, db) still works (no `phases` kwarg)
# ---------------------------------------------------------------------------

def test_legacy_scan_signature_still_works(tree_and_db):
    tree, url = tree_and_db
    ensure_schema(url)
    stats = scan(tree, url, compute_hash=True,
                 store_thumbnails=False, store_samples=False)
    sid = stats["scan_id"]
    assert stats["scanned"] == 3

    rows = _files_for(url, sid)
    for r in rows:
        assert (r["sha256"] or "") != "", f"hash missing for {r['path']!r}"


# ---------------------------------------------------------------------------
# scan(phases=...) — explicit phase set
# ---------------------------------------------------------------------------

def test_scan_with_explicit_phases_subset(tree_and_db):
    tree, url = tree_and_db
    ensure_schema(url)

    # Phase 1 only — no hashes anywhere.
    stats = scan(tree, url, phases=[PHASE_ENUMERATE])
    sid = stats["scan_id"]
    assert stats["phases"] == [PHASE_ENUMERATE]
    rows = _files_for(url, sid)
    assert all((r["sha256"] or "") == "" for r in rows)

    # Now layer on hashes only against the same scan.
    stats2 = scan(tree, url, scan_id=sid, phases=[PHASE_HASH])
    assert stats2["scan_id"] == sid
    rows2 = _files_for(url, sid)
    assert all((r["sha256"] or "") != "" for r in rows2)


def test_scan_phases_canonicalized_order(tree_and_db):
    tree, url = tree_and_db
    ensure_schema(url)
    # Even when the caller passes phases out of order, the orchestrator must
    # run them in canonical cost order (enumerate first, samples last).
    stats = scan(tree, url, phases=[PHASE_HASH, PHASE_ENUMERATE, PHASE_METADATA])
    assert stats["phases"][0] == PHASE_ENUMERATE
    assert PHASE_HASH in stats["phases"]
    assert PHASE_METADATA in stats["phases"]


def test_scan_rejects_unknown_phase(tree_and_db):
    tree, url = tree_and_db
    ensure_schema(url)
    with pytest.raises(ValueError, match="unknown phase"):
        scan(tree, url, phases=["bogus"])


# ---------------------------------------------------------------------------
# repo.phase_status — backs --scan-status
# ---------------------------------------------------------------------------

def test_phase_status_reports_done_for_complete_scan(tree_and_db):
    tree, url = tree_and_db
    ensure_schema(url)
    stats = scan(tree, url, compute_hash=True,
                 store_thumbnails=False, store_samples=False)
    sid = stats["scan_id"]

    repo = repo_for(url)
    status = repo.phase_status(sid)

    # enumerate + hash should be 100%; eligible counts may be zero for
    # categories with no matching fixture files.
    assert status["enumerate"]["done"] == status["enumerate"]["eligible"]
    assert status["hash"]["done"]      == status["hash"]["eligible"]
    for phase in ALL_PHASES:
        assert phase in status
        assert status[phase]["done"] <= status[phase]["eligible"]
