"""Gap-filling tests for the FastAPI web routers.

Targets the branches that the existing per-router tests don't reach:
success paths (reveal, media), unknown-id 404s (api/spa), delete + cancel,
and the localhost-only guard helpers in server.py.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from valscanner.core.db import repo_for
from valscanner.web import server as srv


# ─── server.py: _is_loopback / api 404 / SPA ────────────────────────────────

def test_is_loopback_recognizes_localhost_aliases():
    assert srv._is_loopback("127.0.0.1") is True
    assert srv._is_loopback("::1") is True
    assert srv._is_loopback("localhost") is True


def test_is_loopback_rejects_public_ip():
    assert srv._is_loopback("8.8.8.8") is False
    assert srv._is_loopback("example.com") is False


def test_api_unknown_route_returns_404_with_error_envelope(client):
    r = client.get("/api/this-route-does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "not_found"
    assert "unknown api route" in body["detail"]


def test_health_endpoint_returns_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "db" in body
    assert "version" in body


# ─── reveal.py: success path + 410 gone + subprocess ────────────────────────

def test_reveal_success_calls_platform_opener(client_populated, monkeypatch):
    """200/204 reveal should invoke subprocess.run exactly once."""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "valscanner.web.routers.reveal.subprocess.run",
        lambda argv, **kw: calls.append(list(argv)),
    )
    r = client_populated.post("/api/reveal", json={"file_id": 1})
    assert r.status_code == 204
    assert len(calls) == 1
    assert calls[0][0] in ("open", "explorer", "xdg-open")


def test_reveal_file_missing_on_disk_returns_410(client_populated, populated_db):
    """File was deleted from disk after scan → 410 Gone."""
    repo = repo_for(populated_db)
    row = repo.list_files()[0]
    # Point the DB row at a path that's *inside* scan root but doesn't exist
    import sqlite3
    conn = sqlite3.connect(populated_db)
    scan_row = conn.execute("SELECT root FROM scans WHERE id = ?",
                            (row["scan_id"],)).fetchone()
    scan_root = scan_row[0]
    conn.execute("UPDATE files SET path = ? WHERE id = ?",
                 (f"{scan_root}/ghost.txt", row["id"]))
    conn.commit()
    conn.close()

    r = client_populated.post("/api/reveal", json={"file_id": row["id"]})
    assert r.status_code == 410
    assert r.json()["error"] == "gone"


# ─── media.py: thumbnail + sample success paths ─────────────────────────────

def test_thumbnail_success_returns_jpeg_with_etag(client_populated, populated_db):
    repo = repo_for(populated_db)
    fid = repo.list_files()[0]["id"]
    repo.save_thumbnail(fid, b"\xff\xd8FAKE-JPEG-BYTES", 64, 64)

    r = client_populated.get(f"/api/thumbnail/{fid}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    assert "ETag" in r.headers
    assert "max-age" in r.headers["Cache-Control"]
    assert r.content.startswith(b"\xff\xd8")


def test_sample_success_uses_mime_lookup(client_populated, populated_db):
    repo = repo_for(populated_db)
    fid = repo.list_files()[0]["id"]
    repo.save_media_sample(fid, b"FAKE-MP3-BYTES", "mp3", 1.5)

    r = client_populated.get(f"/api/sample/{fid}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"FAKE-MP3-BYTES"


def test_sample_unknown_format_falls_back_to_octet_stream(client_populated, populated_db):
    repo = repo_for(populated_db)
    fid = repo.list_files()[0]["id"]
    repo.save_media_sample(fid, b"AAA", "weird-fmt", 1.0)

    r = client_populated.get(f"/api/sample/{fid}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"


# ─── scans.py: delete + cancel + stream-not-found ──────────────────────────

def test_stream_unknown_scan_returns_404(client_populated):
    r = client_populated.get("/api/scan/99999/stream")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


def test_cancel_unknown_scan_returns_404(client_populated):
    r = client_populated.post("/api/scan/99999/cancel")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


def test_delete_scan_success(client_populated, populated_db):
    sid = repo_for(populated_db).list_scans()[0]["id"]
    r = client_populated.delete(f"/api/scan/{sid}")
    assert r.status_code == 204
    assert repo_for(populated_db).list_scans() == []


def test_delete_running_scan_returns_409(client, fixture_tree, monkeypatch):
    """A scan that's still active cannot be deleted (409 conflict)."""
    from valscanner.web import scan_registry as reg

    fake_id = 4242
    # Pretend a scan is running by registering it directly
    state = reg.REGISTRY.start(fake_id)
    try:
        r = client.delete(f"/api/scan/{fake_id}")
        assert r.status_code == 409
        assert r.json()["error"] == "scan_in_progress"
    finally:
        reg.REGISTRY.finish(fake_id)
