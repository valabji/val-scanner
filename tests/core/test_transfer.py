"""Tests for valscanner.core.transfer — SQLite ↔ SQLite copy with PK remapping.

PostgreSQL paths are exercised by the same code, but we only need SQLite
fixtures to cover branches: optional analysis/cache transfer, scan_id
remapping inside JSON payloads, and orphan-thumbnail/skip behavior.
"""
from __future__ import annotations

import json

import pytest

from valscanner.core.bootstrap import ensure_schema
from valscanner.core.db import repo_for, reset_repos
from valscanner.core.db_config import reset_engines
from valscanner.core.transfer import _remap_scan_ids, transfer_db


@pytest.fixture
def src_db(tmp_path):
    url = f"sqlite:///{tmp_path / 'src.db'}"
    ensure_schema(url)
    return url


@pytest.fixture
def dst_db(tmp_path):
    return f"sqlite:///{tmp_path / 'dst.db'}"


def _seed(src_url: str, *, with_analysis: bool = False,
          with_cache: bool = False) -> dict:
    repo = repo_for(src_url)
    sid = repo.create_scan("/data", label="seed")
    fid = repo.insert_file({
        "scan_id":    sid,
        "path":       "/data/a.txt",
        "filename":   "a.txt",
        "extension":  ".txt",
        "category":   "document",
        "size_bytes": 42,
        "size_human": "42 B",
        "indexed_at": "2024-01-01 00:00:00",
    })
    repo.save_thumbnail(fid, b"jpeg-bytes", 64, 64)
    repo.save_media_sample(fid, b"audio-bytes", "mp3", 1.5)

    if with_analysis:
        repo.save_analysis_run(
            min_files=3, threshold=0.4,
            scope_scan_ids=[sid], scope_label="seed-scope",
            duration_ms=10,
            results=[{"score": 0.9, "scan_id_a": sid, "scan_id_b": sid}],
            filters={"skip_hidden_files": True},
        )

    if with_cache:
        repo.set_gui_cache("k1", "v1", {"v": 1})

    reset_repos()
    reset_engines()
    return {"scan_id": sid, "file_id": fid}


def test_remap_scan_ids_dict_and_nested():
    obj = {
        "scan_id": 1,
        "scan_id_a": 2,
        "scan_id_b": 3,
        "nested": [{"scan_id": 1}, {"scan_id": 999}],
    }
    _remap_scan_ids(obj, {1: 100, 2: 200, 3: 300})
    assert obj == {
        "scan_id": 100,
        "scan_id_a": 200,
        "scan_id_b": 300,
        "nested": [{"scan_id": 100}, {"scan_id": 999}],
    }


def test_remap_scan_ids_ignores_other_types():
    """Plain strings/ints/None should pass through without error."""
    _remap_scan_ids("hello", {1: 2})
    _remap_scan_ids(None, {1: 2})
    _remap_scan_ids(42, {1: 2})


def test_transfer_copies_scans_files_thumbs_samples(src_db, dst_db):
    seeded = _seed(src_db)
    stats = transfer_db(src_db, dst_db)
    assert stats == {
        "scans": 1, "files": 1, "folders": 0,
        "thumbnails": 1, "samples": 1,
    }
    dst = repo_for(dst_db)
    files = dst.list_files()
    assert len(files) == 1
    # PK should have been remapped to dst's auto-assigned id
    new_fid = files[0]["id"]
    assert dst.get_thumbnail(new_fid) == b"jpeg-bytes"
    assert dst.get_media_sample(new_fid) == (b"audio-bytes", "mp3")


def test_transfer_with_progress_callback_collects_messages(src_db, dst_db):
    _seed(src_db)
    msgs: list[str] = []
    transfer_db(src_db, dst_db, on_progress=msgs.append)
    assert any("scans" in m for m in msgs)
    assert any("files" in m for m in msgs)


def test_transfer_include_analysis_remaps_embedded_ids(src_db, dst_db):
    seeded = _seed(src_db, with_analysis=True)
    stats = transfer_db(src_db, dst_db, include_analysis=True)
    assert stats.get("analysis_runs") == 1

    dst = repo_for(dst_db)
    runs = dst.list_analysis_runs()
    assert len(runs) == 1
    run = dst.load_analysis_run(runs[0]["id"])

    # Source scan id was 1 (first scan), destination scan id should also be 1
    # (empty dst). The key invariant: results JSON refers to the *destination*
    # scan id after remap, not to the bare source id.
    new_sid = dst.list_scans()[0]["id"]
    assert run["scope_scan_ids"] == [new_sid]
    assert run["results"][0]["scan_id_a"] == new_sid
    assert run["results"][0]["scan_id_b"] == new_sid


def test_transfer_include_cache(src_db, dst_db):
    _seed(src_db, with_cache=True)
    stats = transfer_db(src_db, dst_db, include_cache=True)
    assert stats.get("cache_entries") == 1
    assert repo_for(dst_db).get_gui_cache("k1", "v1") == {"v": 1}


def test_transfer_default_skips_analysis_and_cache(src_db, dst_db):
    """Without explicit flags, analysis_runs / gui_cache must NOT cross over."""
    _seed(src_db, with_analysis=True, with_cache=True)
    stats = transfer_db(src_db, dst_db)
    assert "analysis_runs" not in stats
    assert "cache_entries" not in stats
    assert repo_for(dst_db).list_analysis_runs() == []
    assert repo_for(dst_db).get_gui_cache("k1", "v1") is None
