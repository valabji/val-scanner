from __future__ import annotations


def test_health(web_client):
    client, _ = web_client
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "***" not in body.get("db", "") or "@" not in body.get("db", "")


def test_scans(web_client):
    client, _ = web_client
    r = client.get("/api/scans")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_files_paged(web_client):
    client, _ = web_client
    scan_id = client.get("/api/scans").json()[0]["id"]
    r = client.get(f"/api/files?scan_id={scan_id}&page=1&page_size=10")
    assert r.status_code == 200
    payload = r.json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 2


def test_files_search(web_client):
    client, _ = web_client
    scan_id = client.get("/api/scans").json()[0]["id"]
    r = client.get(f"/api/files?scan_id={scan_id}&search=a")
    assert r.status_code == 200


def test_folders(web_client):
    client, _ = web_client
    scan_id = client.get("/api/scans").json()[0]["id"]
    r = client.get(f"/api/folders?scan_id={scan_id}")
    assert r.status_code == 200


def test_export_csv(web_client):
    client, _ = web_client
    scan_id = client.get("/api/scans").json()[0]["id"]
    r = client.get(f"/api/export/csv?scan_id={scan_id}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
