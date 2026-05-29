"""
Database transfer — copy all scan data between any two SQLAlchemy URLs.

Handles SQLite ↔ PostgreSQL in either direction. Primary keys are remapped
so the destination can already contain data without conflicts.

By default only scan/file/folder/thumbnail/sample data is copied.
Pass include_analysis=True to also transfer analysis_runs (scan IDs in the
embedded JSON are remapped automatically). Pass include_cache=True to copy
gui_cache (pure UI state; normally not worth transferring).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from sqlalchemy import create_engine, select, insert, func

from .bootstrap import ensure_schema
from .schema import scans, files, folders, thumbnails, media_samples, gui_cache, analysis_runs

_log = logging.getLogger(__name__)

# Column names to copy, excluding auto-assigned PKs.
_SCAN_COLS     = [c.key for c in scans.c          if c.key != "id"]
_FILE_COLS     = [c.key for c in files.c           if c.key != "id"]
_FOLDER_COLS   = [c.key for c in folders.c         if c.key != "id"]
_THUMB_COLS    = [c.key for c in thumbnails.c      if c.key != "file_id"]
_SAMPLE_COLS   = [c.key for c in media_samples.c   if c.key != "file_id"]
_ANALYSIS_COLS = [c.key for c in analysis_runs.c   if c.key != "id"]
_CACHE_COLS    = list(gui_cache.c.keys())


def _remap_scan_ids(obj: object, scan_id_map: dict[int, int]) -> None:
    """Walk a decoded JSON object in-place, remapping all scan_id values."""
    if isinstance(obj, dict):
        for key in ("scan_id", "scan_id_a", "scan_id_b"):
            if key in obj:
                obj[key] = scan_id_map.get(obj[key], obj[key])
        for v in obj.values():
            _remap_scan_ids(v, scan_id_map)
    elif isinstance(obj, list):
        for item in obj:
            _remap_scan_ids(item, scan_id_map)


def transfer_db(
    src_url: str,
    dst_url: str,
    on_progress: Callable[[str], None] | None = None,
    on_stage_progress: Callable[[str, int, int], None] | None = None,
    include_analysis: bool = False,
    include_cache: bool = False,
) -> dict:
    """Copy scan data from *src_url* to *dst_url*, remapping primary keys.

    ``on_progress(msg)`` is called with terminal stage-completion lines.
    ``on_stage_progress(stage, done, total)`` is called repeatedly during
    each table copy and is expected to throttle/render its own progress bar.

    Returns a dict with counts: scans, files, folders, thumbnails, samples,
    and optionally analysis_runs / cache_entries.
    """
    ensure_schema(dst_url)
    src_engine = create_engine(src_url)
    dst_engine = create_engine(dst_url)
    stats: dict[str, int] = {
        "scans": 0, "files": 0, "folders": 0, "thumbnails": 0, "samples": 0,
    }

    def _emit(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        else:
            _log.info(msg)

    def _stage(name: str, done: int, total: int) -> None:
        if on_stage_progress and total > 0:
            on_stage_progress(name, done, total)

    def _count(conn, table) -> int:
        return conn.execute(select(func.count()).select_from(table)).scalar() or 0

    src_opts = {"stream_results": True, "yield_per": 500}

    with src_engine.connect() as sc, dst_engine.begin() as dc:

        # ── scans ─────────────────────────────────────────────────────────────
        total = _count(sc, scans)
        scan_id_map: dict[int, int] = {}
        for row in sc.execute(select(scans).execution_options(**src_opts)):
            m = row._mapping
            d = {k: m[k] for k in _SCAN_COLS}
            new_id = dc.execute(insert(scans).values(**d)).inserted_primary_key[0]
            scan_id_map[m["id"]] = new_id
            stats["scans"] += 1
            _stage("scans", stats["scans"], total)
        _stage("scans", stats["scans"], stats["scans"])
        _emit(f"  scans:          {stats['scans']:>8,}")

        # ── files ─────────────────────────────────────────────────────────────
        total = _count(sc, files)
        file_id_map: dict[int, int] = {}
        for row in sc.execute(select(files).execution_options(**src_opts)):
            m = row._mapping
            d = {k: m[k] for k in _FILE_COLS}
            d["scan_id"] = scan_id_map[d["scan_id"]]
            new_id = dc.execute(insert(files).values(**d)).inserted_primary_key[0]
            file_id_map[m["id"]] = new_id
            stats["files"] += 1
            _stage("files", stats["files"], total)
        _stage("files", stats["files"], stats["files"])
        _emit(f"  files:          {stats['files']:>8,}")

        # ── folders ───────────────────────────────────────────────────────────
        total = _count(sc, folders)
        for row in sc.execute(select(folders).execution_options(**src_opts)):
            m = row._mapping
            d = {k: m[k] for k in _FOLDER_COLS}
            d["scan_id"] = scan_id_map[d["scan_id"]]
            dc.execute(insert(folders).values(**d))
            stats["folders"] += 1
            _stage("folders", stats["folders"], total)
        _stage("folders", stats["folders"], stats["folders"])
        _emit(f"  folders:        {stats['folders']:>8,}")

        # ── thumbnails ────────────────────────────────────────────────────────
        total = _count(sc, thumbnails)
        for row in sc.execute(select(thumbnails).execution_options(**src_opts)):
            m = row._mapping
            new_fid = file_id_map.get(m["file_id"])
            if new_fid is None:
                continue
            d = {k: m[k] for k in _THUMB_COLS}
            dc.execute(insert(thumbnails).values(file_id=new_fid, **d))
            stats["thumbnails"] += 1
            _stage("thumbnails", stats["thumbnails"], total)
        _stage("thumbnails", stats["thumbnails"], stats["thumbnails"])
        _emit(f"  thumbnails:     {stats['thumbnails']:>8,}")

        # ── media samples ─────────────────────────────────────────────────────
        total = _count(sc, media_samples)
        for row in sc.execute(select(media_samples).execution_options(**src_opts)):
            m = row._mapping
            new_fid = file_id_map.get(m["file_id"])
            if new_fid is None:
                continue
            d = {k: m[k] for k in _SAMPLE_COLS}
            dc.execute(insert(media_samples).values(file_id=new_fid, **d))
            stats["samples"] += 1
            _stage("samples", stats["samples"], total)
        _stage("samples", stats["samples"], stats["samples"])
        _emit(f"  samples:        {stats['samples']:>8,}")

        # ── analysis runs (optional) ──────────────────────────────────────────
        if include_analysis:
            stats["analysis_runs"] = 0
            total = _count(sc, analysis_runs)
            for row in sc.execute(select(analysis_runs).execution_options(**src_opts)):
                m = row._mapping
                d = {k: m[k] for k in _ANALYSIS_COLS}

                filters = json.loads(d["filters_json"] or "{}")
                if "scope_scan_ids" in filters:
                    filters["scope_scan_ids"] = [
                        scan_id_map.get(sid, sid) for sid in filters["scope_scan_ids"]
                    ]
                d["filters_json"] = json.dumps(filters)

                results = json.loads(d["results_json"] or "[]")
                _remap_scan_ids(results, scan_id_map)
                d["results_json"] = json.dumps(results)

                dc.execute(insert(analysis_runs).values(**d))
                stats["analysis_runs"] += 1
                _stage("analysis", stats["analysis_runs"], total)
            _stage("analysis", stats["analysis_runs"], stats["analysis_runs"])
            _emit(f"  analysis runs:  {stats['analysis_runs']:>8,}")

        # ── gui cache (optional) ──────────────────────────────────────────────
        if include_cache:
            stats["cache_entries"] = 0
            total = _count(sc, gui_cache)
            for row in sc.execute(select(gui_cache).execution_options(**src_opts)):
                m = row._mapping
                d = {k: m[k] for k in _CACHE_COLS}
                dc.execute(insert(gui_cache).values(**d).prefix_with("OR REPLACE"))
                stats["cache_entries"] += 1
                _stage("cache", stats["cache_entries"], total)
            _stage("cache", stats["cache_entries"], stats["cache_entries"])
            _emit(f"  cache entries:  {stats['cache_entries']:>8,}")

    return stats
