from __future__ import annotations
import json
import sqlite3
from collections import Counter
from datetime import datetime

from .schema import SCHEMA, human_size


def list_scans(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, label, root, scanned_at, file_count, total_bytes, total_human "
            "FROM scans ORDER BY id"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return [dict(r) for r in rows]


def _ensure_analysis_runs_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(analysis_runs)").fetchall()}
    if "filters_json" not in cols:
        conn.execute(
            "ALTER TABLE analysis_runs ADD COLUMN filters_json TEXT NOT NULL DEFAULT '{}'"
        )


def save_analysis_run(
    db_path: str,
    min_files: int,
    threshold: float,
    scope_scan_ids: list[int] | None,
    scope_label: str,
    duration_ms: int,
    results: list,
    filters: dict | None = None,
) -> int:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    _ensure_analysis_runs_columns(conn)
    scope_ids_str = ",".join(str(i) for i in scope_scan_ids) if scope_scan_ids else ""
    cur = conn.execute(
        "INSERT INTO analysis_runs "
        "(ran_at, min_files, threshold, scope_scan_ids, scope_label, "
        " duration_ms, pair_count, filters_json, results_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            min_files,
            threshold,
            scope_ids_str,
            scope_label,
            duration_ms,
            len(results),
            json.dumps(filters or {}),
            json.dumps(results),
        ),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def list_analysis_runs(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_analysis_runs_columns(conn)
        rows = conn.execute(
            "SELECT id, ran_at, min_files, threshold, scope_scan_ids, "
            "       scope_label, duration_ms, pair_count, filters_json "
            "FROM analysis_runs ORDER BY id DESC"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["filters"] = json.loads(d.pop("filters_json") or "{}")
        except (json.JSONDecodeError, KeyError):
            d["filters"] = {}
        out.append(d)
    return out


def load_analysis_run(db_path: str, run_id: int) -> dict | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_analysis_runs_columns(conn)
        row = conn.execute(
            "SELECT id, ran_at, min_files, threshold, scope_scan_ids, "
            "       scope_label, duration_ms, pair_count, filters_json, results_json "
            "FROM analysis_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    conn.close()
    if row is None:
        return None
    out = dict(row)
    try:
        out["results"] = json.loads(out.pop("results_json") or "[]")
    except json.JSONDecodeError:
        out["results"] = []
    try:
        out["filters"] = json.loads(out.pop("filters_json") or "{}")
    except (json.JSONDecodeError, KeyError):
        out["filters"] = {}
    return out


def delete_analysis_run(db_path: str, run_id: int) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM analysis_runs WHERE id = ?", (run_id,))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.close()


def delete_scan(db_path: str, scan_id: int) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
    conn.commit()
    conn.close()


def query_db(db_path: str, term: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    print(f"\n🔍 Searching for: '{term}'\n{'─'*60}")

    try:
        fts_rows = conn.execute(
            "SELECT path, category, size_human, tags FROM files "
            "WHERE id IN (SELECT rowid FROM files_fts WHERE files_fts MATCH ?) "
            "ORDER BY path LIMIT 50",
            (term,),
        ).fetchall()
    except sqlite3.OperationalError:
        fts_rows = []

    like = f"%{term}%"
    like_rows = conn.execute(
        "SELECT path, category, size_human, tags FROM files "
        "WHERE path LIKE ? OR category LIKE ? OR tags LIKE ? ORDER BY path LIMIT 50",
        (like, like, like),
    ).fetchall()

    seen: set[str] = set()
    total = 0
    for row in list(fts_rows) + list(like_rows):
        p = row["path"]
        if p in seen:
            continue
        seen.add(p)
        total += 1
        print(f"  {row['category']:14s}  {row['size_human']:>10s}  {p}")
        print(f"  {'':14s}  tags: {row['tags']}\n")

    print(f"{'─'*60}\n  Found {total} result(s).")
    conn.close()


def print_summary(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    total,      = conn.execute("SELECT COUNT(*) FROM files").fetchone()
    total_size, = conn.execute("SELECT SUM(size_bytes) FROM files").fetchone()
    total_size  = total_size or 0

    scans = conn.execute(
        "SELECT id, label, root, scanned_at, file_count, total_human FROM scans ORDER BY id"
    ).fetchall()

    print(f"\n{'═'*60}")
    if len(scans) > 1:
        print(f"  📦  Scans in database: {len(scans)}")
        for sid, slabel, sroot, sat, sfc, sth in scans:
            print(f"    [{sid}] {slabel or sroot}  —  {sfc:,} files  {sth}  ({sat})")
        print()

    print(f"  📁  Total files indexed : {total:,}")
    print(f"  💾  Total size          : {human_size(total_size)}")
    print(f"\n  Files by category:")
    for cat, cnt, sz in conn.execute(
        "SELECT category, COUNT(*), SUM(size_bytes) FROM files "
        "GROUP BY category ORDER BY 2 DESC"
    ):
        print(f"    {cat:20s} {cnt:>6,} files   {human_size(sz or 0):>10s}")

    print(f"\n  Top 10 most common extensions:")
    for ext, cnt in conn.execute(
        "SELECT extension, COUNT(*) AS cnt FROM files "
        "GROUP BY extension ORDER BY 2 DESC LIMIT 10"
    ):
        print(f"    {ext:12s}  {cnt:>6,}")

    print(f"\n  Top 10 tags:")
    all_tags = conn.execute("SELECT tags FROM files WHERE tags != ''").fetchall()
    tag_counter: Counter = Counter()
    for (tag_str,) in all_tags:
        for t in tag_str.split(", "):
            tag_counter[t.strip()] += 1
    for tag, cnt in tag_counter.most_common(10):
        print(f"    {tag:30s}  {cnt:>6,}")

    print(f"\n  Top 10 largest folders (cumulative):")
    for fpath_str, tb, fc in conn.execute(
        "SELECT path, SUM(total_bytes), SUM(file_count) FROM folders "
        "GROUP BY path ORDER BY 2 DESC LIMIT 10"
    ):
        print(f"    {human_size(tb):>10s}  ({fc:,} files)  {fpath_str}")

    print(f"{'═'*60}\n")
    conn.close()
