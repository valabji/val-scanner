from __future__ import annotations

import pytest
from valscanner.core.exceptions import DuplicateRecordError
from tests.core.conftest import sample_file


def test_create_and_list_scans(sqlite_repo):
    sid = sqlite_repo.create_scan("/tmp", label="test")
    scans = sqlite_repo.list_scans()
    assert len(scans) == 1
    assert scans[0]["label"] == "test"
    assert scans[0]["id"] == sid


def test_delete_scan_cascades(sqlite_repo):
    sid = sqlite_repo.create_scan("/tmp")
    sqlite_repo.insert_file(sample_file(sid))
    sqlite_repo.delete_scan(sid)
    assert sqlite_repo.list_scans() == []
    assert sqlite_repo.list_files() == []


def test_insert_file_duplicate_raises(sqlite_repo):
    sid = sqlite_repo.create_scan("/tmp")
    sqlite_repo.insert_file(sample_file(sid))
    with pytest.raises(DuplicateRecordError):
        sqlite_repo.insert_file(sample_file(sid))


def test_pagination(sqlite_repo):
    sid = sqlite_repo.create_scan("/tmp")
    for i in range(10):
        sqlite_repo.insert_file(sample_file(sid, f"/tmp/f{i}.txt"))
    page1 = sqlite_repo.list_files(scan_id=sid, page=1, page_size=5)
    page2 = sqlite_repo.list_files(scan_id=sid, page=2, page_size=5)
    assert len(page1) == 5 and len(page2) == 5
    assert {r["path"] for r in page1}.isdisjoint({r["path"] for r in page2})


def test_fts_search(sqlite_repo):
    sid = sqlite_repo.create_scan("/tmp")
    sqlite_repo.insert_file({
        **sample_file(sid, "/tmp/report.pdf"),
        "tags": "finance, annual",
    })
    assert len(sqlite_repo.search_files("finance")) == 1


def test_fts_ranking(sqlite_repo):
    """Filename matches should outrank path matches."""
    sid = sqlite_repo.create_scan("/tmp")
    sqlite_repo.insert_file({**sample_file(sid, "/tmp/alpha/dir/x.txt"), "tags": ""})
    sqlite_repo.insert_file({**sample_file(sid, "/tmp/alpha.txt"),
                              "filename": "alpha.txt", "tags": ""})
    items = sqlite_repo.search_paged(sid, search="alpha")["items"]
    assert items[0]["filename"] == "alpha.txt"


def test_search_paged_total(sqlite_repo):
    sid = sqlite_repo.create_scan("/tmp")
    for i in range(50):
        sqlite_repo.insert_file({**sample_file(sid, f"/tmp/x{i}.txt"),
                                  "filename": f"x{i}.txt", "tags": "alpha"})
    out = sqlite_repo.search_paged(sid, search="alpha", page=1, page_size=10)
    assert out["total"] == 50
    assert len(out["items"]) == 10


def test_thumbnail_roundtrip(sqlite_repo):
    sid = sqlite_repo.create_scan("/tmp")
    fid = sqlite_repo.insert_file(sample_file(sid))
    sqlite_repo.save_thumbnail(fid, b"\xff\xd8\xff", 64, 64)
    assert sqlite_repo.get_thumbnail(fid) == b"\xff\xd8\xff"


def test_media_sample_roundtrip(sqlite_repo):
    sid = sqlite_repo.create_scan("/tmp")
    fid = sqlite_repo.insert_file(sample_file(sid, "/tmp/x.mp3"))
    sqlite_repo.save_media_sample(fid, b"audio", "mp3", 3.5)
    assert sqlite_repo.get_media_sample(fid) == (b"audio", "mp3")


def test_get_file_with_scan_root(sqlite_repo):
    sid = sqlite_repo.create_scan("/srv/scan_root")
    fid = sqlite_repo.insert_file({**sample_file(sid),
                                   "path": "/srv/scan_root/a.txt"})
    assert sqlite_repo.get_file_with_scan_root(fid) == (
        "/srv/scan_root/a.txt", "/srv/scan_root"
    )


def test_analysis_run_roundtrip(sqlite_repo):
    run_id = sqlite_repo.save_analysis_run(
        min_files=5, threshold=0.7,
        scope_scan_ids=[1, 2], scope_label="all",
        duration_ms=123, results=[{"a": 1}], filters={"category": "image"},
    )
    run = sqlite_repo.load_analysis_run(run_id)
    assert run["results"] == [{"a": 1}]
    assert run["scope_scan_ids"] == [1, 2]
    assert run["filters"]["category"] == "image"
    sqlite_repo.delete_analysis_run(run_id)
    assert sqlite_repo.load_analysis_run(run_id) is None


def test_summary(sqlite_repo):
    sid = sqlite_repo.create_scan("/tmp")
    for i in range(3):
        sqlite_repo.insert_file(sample_file(sid, f"/tmp/x{i}.txt"))
    assert sqlite_repo.summary()["total_files"] == 3
