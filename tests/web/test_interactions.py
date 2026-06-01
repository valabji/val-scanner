"""Web UI request/response integration tests for /api/similar,
/api/export/json, and /api/files filter combinations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from valscanner.core.scanner import scan as run_scan


# -----------------------------------------------------------------------------
# /api/similar — folder-similarity endpoint
# -----------------------------------------------------------------------------

@pytest.fixture
def twin_folders_db(tmp_path: Path) -> str:
    """Two near-identical folder trees in one scan so similarity finds a pair."""
    root = tmp_path / "twin_root"
    root.mkdir()
    left = root / "left"
    right = root / "right"
    left.mkdir()
    right.mkdir()
    for name in ("alpha.txt", "beta.txt", "gamma.txt"):
        (left / name).write_text(f"shared {name}")
        (right / name).write_text(f"shared {name}")

    db_path = str(tmp_path / "twin.db")
    run_scan(root, db_path, compute_hash=False, label="twins")
    return db_path


@pytest.fixture
def twin_client(twin_folders_db):
    from fastapi.testclient import TestClient
    from valscanner.web.server import create_app

    app = create_app(twin_folders_db)
    with TestClient(app) as c:
        yield c


def test_similar_returns_pairs_for_lookalike_folders(twin_client):
    r = twin_client.get("/api/similar", params={"scan_id": 1})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    pair = data[0]
    for key in (
        "folder_a", "folder_b", "scan_id_a", "scan_id_b",
        "score", "label", "name_score", "ext_score",
        "size_score", "hash_score",
        "files_a", "files_b", "bytes_a", "bytes_b",
        "shared_names", "shared_hashes", "children",
    ):
        assert key in pair, f"missing key {key} in SimilarPair payload"
    assert 0.0 <= pair["score"] <= 1.0


def test_similar_empty_for_solo_folder(client_populated):
    r = client_populated.get("/api/similar", params={"scan_id": 1})
    assert r.status_code == 200
    assert r.json() == []


def test_similar_rejects_missing_scan_id(client):
    r = client.get("/api/similar")
    assert r.status_code == 422


def test_similar_rejects_zero_scan_id(client):
    r = client.get("/api/similar", params={"scan_id": 0})
    assert r.status_code == 422


# -----------------------------------------------------------------------------
# /api/export/json — JSON export endpoint
# -----------------------------------------------------------------------------

def test_export_json_returns_attachment(client_populated):
    r = client_populated.get("/api/export/json", params={"scan_id": 1})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    disp = r.headers.get("content-disposition", "")
    assert "attachment" in disp
    assert 'filename="scan_1.json"' in disp


def test_export_json_payload_is_list_of_rows(client_populated):
    r = client_populated.get("/api/export/json", params={"scan_id": 1})
    payload = json.loads(r.text)
    assert isinstance(payload, list)
    assert len(payload) >= 3
    sample = payload[0]
    assert isinstance(sample, dict)
    assert "path" in sample
    assert "size_bytes" in sample or "size" in sample


def test_export_json_unknown_scan_returns_empty(client_populated):
    r = client_populated.get("/api/export/json", params={"scan_id": 9999})
    assert r.status_code == 200
    assert json.loads(r.text) == []


def test_export_json_rejects_zero_scan_id(client):
    r = client.get("/api/export/json", params={"scan_id": 0})
    assert r.status_code == 422


# -----------------------------------------------------------------------------
# /api/files — search + category filters
# -----------------------------------------------------------------------------

def test_files_search_filters_to_matching_name(client_populated):
    full = client_populated.get(
        "/api/files", params={"scan_id": 1, "page_size": 500}
    ).json()
    assert full["total"] >= 3

    r = client_populated.get(
        "/api/files", params={"scan_id": 1, "search": "nested"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert data["total"] <= full["total"]
    for item in data["items"]:
        assert "nested" in item["path"].lower() or "nested" in item["name"].lower()


def test_files_search_no_matches_returns_empty(client_populated):
    r = client_populated.get(
        "/api/files",
        params={"scan_id": 1, "search": "zzzzzznosuchfilezzzzz"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_files_known_category_filter_returns_only_that_category(client_populated):
    r = client_populated.get(
        "/api/files", params={"scan_id": 1, "category": "document"},
    )
    assert r.status_code == 200
    data = r.json()
    for item in data["items"]:
        assert item["category"] == "document"


def test_files_search_and_category_combine(client_populated):
    r = client_populated.get(
        "/api/files",
        params={"scan_id": 1, "search": "nested", "category": "document"},
    )
    assert r.status_code == 200
    data = r.json()
    for item in data["items"]:
        assert item["category"] == "document"


def test_files_pagination_envelope_is_consistent(client_populated):
    r = client_populated.get(
        "/api/files", params={"scan_id": 1, "page": 1, "page_size": 2},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert len(data["items"]) <= 2
    assert data["total"] >= len(data["items"])
