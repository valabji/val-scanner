def test_folders_tree_shape(client_populated):
    r = client_populated.get("/api/folders", params={"scan_id": 1})
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert "children" in body
    assert isinstance(body["children"], list)
