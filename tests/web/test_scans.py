import time


def test_list_scans_empty(client):
    r = client.get("/api/scans")
    assert r.status_code == 200
    assert r.json() == []


def test_invalid_root(client):
    r = client.post("/api/scan", json={"root": "/definitely/not/a/real/path"})
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_root"


def test_scan_lifecycle(client, fixture_tree):
    r = client.post("/api/scan", json={"root": str(fixture_tree), "no_hash": True})
    assert r.status_code == 202
    scan_id = r.json()["scan_id"]

    # Stream until we see {"done": true}.
    with client.stream("GET", f"/api/scan/{scan_id}/stream") as resp:
        assert resp.status_code == 200
        seen_done = False
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            if '"done": true' in line or '"done":true' in line:
                seen_done = True
                break
        assert seen_done

    # Give the worker thread a moment to finalize.
    time.sleep(0.1)
    r = client.get("/api/scans")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_scan_conflict(client, fixture_tree):
    a = client.post("/api/scan", json={"root": str(fixture_tree), "no_hash": True})
    assert a.status_code == 202
    b = client.post("/api/scan", json={"root": str(fixture_tree), "no_hash": True})
    assert b.status_code == 409
    assert b.json()["error"] == "scan_in_progress"
