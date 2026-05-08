from __future__ import annotations
import sqlite3
from collections import Counter

from .schema import human_size


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
