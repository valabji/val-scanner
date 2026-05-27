from __future__ import annotations

import pytest

from tests.core.conftest import sample_file


def _insert_folder(repo, scan_id, path):
    repo.upsert_folder(scan_id=scan_id, path=path,
                       file_count=0, total_bytes=0,
                       total_human="0 B",
                       indexed_at="2024-01-01 00:00:00")


def test_remap_same_os_prefix_swap(sqlite_repo):
    sid = sqlite_repo.create_scan("/srv/orig")
    sqlite_repo.insert_file({**sample_file(sid), "path": "/srv/orig/a.txt"})
    sqlite_repo.insert_file({**sample_file(sid), "path": "/srv/orig/sub/b.txt"})
    _insert_folder(sqlite_repo, sid, "/srv/orig")
    _insert_folder(sqlite_repo, sid, "/srv/orig/sub")

    summary = sqlite_repo.remap_scan_root(sid, "/srv/moved")

    assert summary["files_updated"] == 2
    assert summary["folders_updated"] == 2
    assert summary["files_skipped"] == []
    assert sqlite_repo.get_scan(sid)["root"] == "/srv/moved"
    paths = {r["path"] for r in sqlite_repo.list_files(scan_id=sid)}
    assert paths == {"/srv/moved/a.txt", "/srv/moved/sub/b.txt"}
    folder_paths = {r["path"] for r in sqlite_repo.list_folders_for_scan(sid)}
    assert folder_paths == {"/srv/moved", "/srv/moved/sub"}


def test_remap_cross_os_windows_to_posix(sqlite_repo):
    sid = sqlite_repo.create_scan(r"C:\Photos")
    sqlite_repo.insert_file({**sample_file(sid), "path": r"C:\Photos\sub\a.jpg"})
    sqlite_repo.insert_file({**sample_file(sid), "path": r"C:\Photos\b.jpg"})
    _insert_folder(sqlite_repo, sid, r"C:\Photos")
    _insert_folder(sqlite_repo, sid, r"C:\Photos\sub")

    summary = sqlite_repo.remap_scan_root(sid, "/Volumes/Photos")

    assert summary["files_updated"] == 2
    assert summary["folders_updated"] == 2
    assert sqlite_repo.get_scan(sid)["root"] == "/Volumes/Photos"
    paths = {r["path"] for r in sqlite_repo.list_files(scan_id=sid)}
    assert paths == {"/Volumes/Photos/sub/a.jpg", "/Volumes/Photos/b.jpg"}


def test_remap_noop_when_root_unchanged(sqlite_repo):
    sid = sqlite_repo.create_scan("/srv/orig")
    sqlite_repo.insert_file({**sample_file(sid), "path": "/srv/orig/a.txt"})

    summary = sqlite_repo.remap_scan_root(sid, "/srv/orig")

    assert summary["files_updated"] == 0
    assert summary["folders_updated"] == 0
    assert sqlite_repo.get_scan(sid)["root"] == "/srv/orig"


def test_remap_strips_trailing_separator(sqlite_repo):
    sid = sqlite_repo.create_scan("/srv/orig")
    sqlite_repo.insert_file({**sample_file(sid), "path": "/srv/orig/a.txt"})

    summary = sqlite_repo.remap_scan_root(sid, "/srv/moved/")

    assert summary["files_updated"] == 1
    assert sqlite_repo.get_scan(sid)["root"] == "/srv/moved"
    paths = {r["path"] for r in sqlite_repo.list_files(scan_id=sid)}
    assert paths == {"/srv/moved/a.txt"}


def test_remap_skips_rows_outside_old_root(sqlite_repo):
    sid = sqlite_repo.create_scan("/srv/orig")
    sqlite_repo.insert_file({**sample_file(sid), "path": "/srv/orig/a.txt"})
    sqlite_repo.insert_file({**sample_file(sid), "path": "/elsewhere/stray.txt"})

    summary = sqlite_repo.remap_scan_root(sid, "/srv/moved")

    assert summary["files_updated"] == 1
    assert summary["files_skipped"] == ["/elsewhere/stray.txt"]
    paths = {r["path"] for r in sqlite_repo.list_files(scan_id=sid)}
    assert paths == {"/srv/moved/a.txt", "/elsewhere/stray.txt"}


def test_remap_unknown_scan_raises(sqlite_repo):
    with pytest.raises(ValueError):
        sqlite_repo.remap_scan_root(999, "/anywhere")


def test_remap_fts_stays_in_sync(sqlite_repo):
    sid = sqlite_repo.create_scan("/srv/orig")
    sqlite_repo.insert_file({**sample_file(sid),
                              "path": "/srv/orig/report.pdf",
                              "filename": "report.pdf",
                              "tags": "finance"})
    sqlite_repo.remap_scan_root(sid, "/srv/moved")

    # FTS should reflect the new path (AFTER UPDATE trigger ran).
    items = sqlite_repo.search_paged(sid, search="moved")["items"]
    assert any(it["path"] == "/srv/moved/report.pdf" for it in items)
