from __future__ import annotations
import csv
import json
import sqlite3


def export_csv(db_path: str, out_path: str, scan_id: int | None = None) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    q    = "SELECT * FROM files" + (" WHERE scan_id=?" if scan_id else "") + " ORDER BY path"
    rows = conn.execute(q, (scan_id,) if scan_id else ()).fetchall()
    if not rows:
        print("No rows to export.")
        conn.close()
        return
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows([dict(r) for r in rows])
    conn.close()
    print(f"✓ CSV exported → {out_path}")


def export_json(db_path: str, out_path: str, scan_id: int | None = None) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    q    = "SELECT * FROM files" + (" WHERE scan_id=?" if scan_id else "") + " ORDER BY path"
    rows = [dict(r) for r in conn.execute(q, (scan_id,) if scan_id else ())]
    conn.close()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"✓ JSON exported → {out_path}")
