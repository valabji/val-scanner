def test_thumbnail_missing(client_populated):
    r = client_populated.get("/api/thumbnail/999999")
    assert r.status_code == 404
    assert r.json()["error"] == "no_thumbnail"


def test_sample_missing(client_populated):
    r = client_populated.get("/api/sample/999999")
    assert r.status_code == 404
    assert r.json()["error"] == "no_sample"
