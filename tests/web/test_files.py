def test_files_pagination(client_populated):
    # Scan id 1 is the only scan from the fixture.
    r = client_populated.get("/api/files", params={"scan_id": 1, "page_size": 2, "page": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total"] >= 3
    assert len(body["items"]) == 2

    r2 = client_populated.get("/api/files", params={"scan_id": 1, "page_size": 2, "page": 2})
    body2 = r2.json()
    assert body2["page"] == 2
    assert len(body2["items"]) >= 1


def test_files_bad_category(client_populated):
    r = client_populated.get("/api/files", params={"scan_id": 1, "category": "bogus"})
    assert r.status_code == 400
    assert r.json()["error"] == "bad_category"
