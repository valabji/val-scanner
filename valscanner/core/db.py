from __future__ import annotations

from threading import Lock

from .app_settings import active_url
from .repository import Repository
from .schema import human_size

_repos: dict[str, Repository] = {}
_repo_lock = Lock()


def repo_for(db_path_or_url: str | None = None) -> Repository:
    """Cached Repository keyed by SQLAlchemy URL."""
    url = active_url(db_path_or_url)
    with _repo_lock:
        r = _repos.get(url)
        if r is None:
            r = Repository(url)
            _repos[url] = r
        return r


def reset_repos() -> None:
    with _repo_lock:
        _repos.clear()


# Legacy wrappers — same names + signatures as the old sqlite3 versions.

def list_scans(db_path: str) -> list[dict]:
    return repo_for(db_path).list_scans()


def delete_scan(db_path: str, scan_id: int) -> None:
    repo_for(db_path).delete_scan(scan_id)


def save_analysis_run(db_path: str, min_files: int, threshold: float,
                      scope_scan_ids: list[int] | None, scope_label: str,
                      duration_ms: int, results: list,
                      filters: dict | None = None) -> int:
    return repo_for(db_path).save_analysis_run(
        min_files, threshold, scope_scan_ids, scope_label,
        duration_ms, results, filters,
    )


def list_analysis_runs(db_path: str) -> list[dict]:
    return repo_for(db_path).list_analysis_runs()


def load_analysis_run(db_path: str, run_id: int) -> dict | None:
    return repo_for(db_path).load_analysis_run(run_id)


def delete_analysis_run(db_path: str, run_id: int) -> None:
    repo_for(db_path).delete_analysis_run(run_id)


def query_db(db_path: str, term: str) -> None:
    results = repo_for(db_path).search_files(term)
    print(f"\n🔍 Searching for: '{term}'\n{'─'*60}")
    for row in results:
        print(f"  {row['category']:14s}  {row['size_human']:>10s}  {row['path']}")
        print(f"  {'':14s}  tags: {row['tags']}\n")
    print(f"{'─'*60}\n  Found {len(results)} result(s).")


def print_summary(db_path: str) -> None:
    s = repo_for(db_path).summary()
    print(f"\n{'═'*60}")
    if len(s["scans"]) > 1:
        print(f"  📦  Scans in database: {len(s['scans'])}")
        for sc in s["scans"]:
            print(f"    [{sc['id']}] {sc['label'] or sc['root']}  —  "
                  f"{sc['file_count']:,} files  {sc['total_human']}  ({sc['scanned_at']})")
        print()
    print(f"  📁  Total files indexed : {s['total_files']:,}")
    print(f"  💾  Total size          : {human_size(s['total_bytes'])}")
    print(f"\n  Files by category:")
    for row in s["by_category"]:
        print(f"    {row['category']:20s} {row['count']:>6,} files   "
              f"{human_size(row['bytes'] or 0):>10s}")
    print(f"\n  Top 10 most common extensions:")
    for row in s["top_extensions"]:
        print(f"    {row['extension']:12s}  {row['count']:>6,}")
    print(f"\n  Top 10 tags:")
    for tag, cnt in s["top_tags"]:
        print(f"    {tag:30s}  {cnt:>6,}")
    print(f"\n  Top 10 largest folders (cumulative):")
    for row in s["top_folders"]:
        print(f"    {human_size(row['bytes'] or 0):>10s}  "
              f"({row['file_count']:,} files)  {row['path']}")
    print(f"{'═'*60}\n")
