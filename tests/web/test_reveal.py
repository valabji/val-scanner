import sqlite3


def test_reveal_bad_id(client_populated):
    r = client_populated.post("/api/reveal", json={"file_id": 999999})
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


def test_reveal_outside_root(client_populated, populated_db, tmp_path):
    # Manually corrupt the DB: set file 1's path to /etc/hosts, outside scan root.
    conn = sqlite3.connect(populated_db)
    conn.execute("UPDATE files SET path = '/etc/hosts' WHERE id = 1")
    conn.commit()
    conn.close()
    r = client_populated.post("/api/reveal", json={"file_id": 1})
    assert r.status_code == 403
    assert r.json()["error"] == "outside_scan_root"
