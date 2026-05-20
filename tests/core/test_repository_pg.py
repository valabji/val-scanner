from __future__ import annotations

import pytest
from valscanner.core.exceptions import DuplicateRecordError
from tests.core.conftest import sample_file


def test_create_and_list_scans_pg(pg_repo):
    pg_repo.create_scan("/data", label="pg-test")
    assert any(s["label"] == "pg-test" for s in pg_repo.list_scans())


def test_fts_search_pg(pg_repo):
    sid = pg_repo.create_scan("/data")
    pg_repo.insert_file({
        **sample_file(sid, "/data/invoice.pdf"),
        "tags": "finance, invoice",
        "category": "document",
    })
    assert len(pg_repo.search_files("invoice")) >= 1


def test_fts_ranking_pg(pg_repo):
    sid = pg_repo.create_scan("/data")
    pg_repo.insert_file({**sample_file(sid, "/data/alpha/x.txt"), "filename": "x.txt"})
    pg_repo.insert_file({**sample_file(sid, "/data/alpha.txt"), "filename": "alpha.txt"})
    out = pg_repo.search_paged(sid, search="alpha")
    assert out["items"][0]["filename"] == "alpha.txt"


def test_duplicate_raises_pg(pg_repo):
    sid = pg_repo.create_scan("/data")
    pg_repo.insert_file(sample_file(sid))
    with pytest.raises(DuplicateRecordError):
        pg_repo.insert_file(sample_file(sid))
