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


_ANALYSIS_CSV_COLUMNS = (
    "scan_id",
    "scan_label",
    "folder",
    "category",
    "subcategory",
    "file_count",
    "total_bytes",
    "dominance",
    "mirror_count",
    "mirror_paths",
)


def export_quick_analysis_csv(results: list[dict], out_path: str) -> None:
    """Write quick-analysis primary rows to CSV.

    Mirrors are flattened: their paths are joined into ``mirror_paths`` with
    ``;`` and the count is exposed via ``mirror_count``.
    """
    if not results:
        print("No analysis rows to export.")
        return
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(_ANALYSIS_CSV_COLUMNS))
        w.writeheader()
        for r in results:
            mirrors = r.get("mirrors") or []
            w.writerow({
                "scan_id":      r.get("scan_id"),
                "scan_label":   r.get("scan_label", ""),
                "folder":       r.get("folder", ""),
                "category":     r.get("category", ""),
                "subcategory":  r.get("subcategory", "") or "",
                "file_count":   r.get("file_count", 0),
                "total_bytes":  r.get("total_bytes", 0),
                "dominance":    r.get("dominance", 0.0),
                "mirror_count": len(mirrors),
                "mirror_paths": ";".join(m.get("folder", "") for m in mirrors),
            })
    print(f"✓ Analysis CSV exported → {out_path}")


def export_quick_analysis_json(results: list[dict], out_path: str) -> None:
    """Write quick-analysis rows to JSON, keeping the nested ``mirrors`` list."""
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"✓ Analysis JSON exported → {out_path}")
