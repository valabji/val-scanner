from __future__ import annotations
import csv
import json

from .db import repo_for


def export_csv(db_path: str, out_path: str, scan_id: int | None = None) -> None:
    rows = list(repo_for(db_path).iter_files_for_export(scan_id=scan_id))
    if not rows:
        print("No rows to export.")
        return
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"✓ CSV exported → {out_path}")


def export_json(db_path: str, out_path: str, scan_id: int | None = None) -> None:
    rows = list(repo_for(db_path).iter_files_for_export(scan_id=scan_id))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"✓ JSON exported → {out_path}")
