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
import zipfile
from collections.abc import Callable
from pathlib import Path
from sqlalchemy import create_engine, select, insert, func
from sqlalchemy.exc import DatabaseError

from .bootstrap import ensure_schema
from .filters import (
    FILTER_KEYS,
    file_is_skipped,
    path_contains_skipped_dir,
    path_has_skipped_dir,
)
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
    include_thumbnails: bool = True,
    include_samples: bool = True,
    scan_ids: list[int] | None = None,
    filter_options: dict | None = None,
    on_skip: Callable[[str, str], None] | None = None,
    write_blobs_zip: Path | str | None = None,
    read_blobs_zip: Path | str | None = None,
) -> dict:
    """Copy scan data from *src_url* to *dst_url*, remapping primary keys.

    ``on_progress(msg)`` is called with terminal stage-completion lines.
    ``on_stage_progress(stage, done, total)`` is called repeatedly during
    each table copy and is expected to throttle/render its own progress bar.
    ``scan_ids`` restricts the transfer to specific scan IDs; None copies all.
    ``filter_options`` is a dict of skip-* flags (see filters.FILTER_KEYS) that
    drops files/folders matching the scan-style skip rules during the copy.
    ``on_skip(kind, path)`` is called for each dropped row, where kind is
    "file" or "folder"; pass to list every item filter_options excluded.
    ``write_blobs_zip`` writes thumbnail/sample blobs to a ZIP file keyed by
    destination file ID instead of (or in addition to) storing them in SQLite.
    ``read_blobs_zip`` reads thumbnail/sample blobs from a ZIP file keyed by
    source file ID and inserts them into the destination with remapped IDs.

    Returns a dict with counts: scans, files, folders, thumbnails, samples,
    and optionally analysis_runs / cache_entries.
    """
    ensure_schema(dst_url)
    src_engine = create_engine(src_url)
    dst_engine = create_engine(dst_url)
    stats: dict[str, int] = {
        "scans": 0, "files": 0, "folders": 0, "thumbnails": 0, "samples": 0,
    }

    filter_opts = {k: bool(filter_options.get(k)) for k in FILTER_KEYS} \
        if filter_options else {}
    filter_active = any(filter_opts.values())
    if filter_active:
        stats["files_skipped"] = 0
        stats["folders_skipped"] = 0
    # Thumbnails/samples queries must constrain to surviving file IDs whenever
    # the file set is a strict subset of the source — either because of scan_ids
    # or because rows were dropped by filter_options.
    file_set_reduced = scan_ids is not None or filter_active

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
        scan_q = select(scans)
        if scan_ids is not None:
            scan_q = scan_q.where(scans.c.id.in_(scan_ids))
        total = sc.execute(select(func.count()).select_from(scan_q.subquery())).scalar() or 0
        scan_id_map: dict[int, int] = {}
        for row in sc.execute(scan_q.execution_options(**src_opts)):
            m = row._mapping
            d = {k: m[k] for k in _SCAN_COLS}
            new_id = dc.execute(insert(scans).values(**d)).inserted_primary_key[0]
            scan_id_map[m["id"]] = new_id
            stats["scans"] += 1
            _stage("scans", stats["scans"], total)
        _stage("scans", stats["scans"], stats["scans"])
        _emit(f"  scans:          {stats['scans']:>8,}")

        # ── files ─────────────────────────────────────────────────────────────
        src_scan_ids = list(scan_id_map.keys())
        file_q = select(files)
        if scan_ids is not None:
            file_q = file_q.where(files.c.scan_id.in_(src_scan_ids))
        total = sc.execute(select(func.count()).select_from(file_q.subquery())).scalar() or 0
        file_id_map: dict[int, int] = {}
        for row in sc.execute(file_q.execution_options(**src_opts)):
            m = row._mapping
            if filter_active and (
                file_is_skipped(m["filename"] or "",
                                (m["extension"] or "").lower(),
                                filter_opts)
                or path_has_skipped_dir(m["path"] or "", filter_opts)
            ):
                stats["files_skipped"] += 1
                if on_skip:
                    on_skip("file", m["path"] or "")
                continue
            d = {k: m[k] for k in _FILE_COLS}
            d["scan_id"] = scan_id_map[d["scan_id"]]
            new_id = dc.execute(insert(files).values(**d)).inserted_primary_key[0]
            file_id_map[m["id"]] = new_id
            stats["files"] += 1
            _stage("files", stats["files"], total)
        _stage("files", stats["files"], stats["files"])
        _emit(f"  files:          {stats['files']:>8,}")
        if filter_active and stats["files_skipped"]:
            _emit(f"  files skipped:  {stats['files_skipped']:>8,}  (filtered)")

        # ── folders ───────────────────────────────────────────────────────────
        folder_q = select(folders)
        if scan_ids is not None:
            folder_q = folder_q.where(folders.c.scan_id.in_(src_scan_ids))
        total = sc.execute(select(func.count()).select_from(folder_q.subquery())).scalar() or 0
        for row in sc.execute(folder_q.execution_options(**src_opts)):
            m = row._mapping
            if filter_active and path_contains_skipped_dir(m["path"] or "", filter_opts):
                stats["folders_skipped"] += 1
                if on_skip:
                    on_skip("folder", m["path"] or "")
                continue
            d = {k: m[k] for k in _FOLDER_COLS}
            d["scan_id"] = scan_id_map[d["scan_id"]]
            dc.execute(insert(folders).values(**d))
            stats["folders"] += 1
            _stage("folders", stats["folders"], total)
        _stage("folders", stats["folders"], stats["folders"])
        _emit(f"  folders:        {stats['folders']:>8,}")
        if filter_active and stats["folders_skipped"]:
            _emit(f"  folders skipped:{stats['folders_skipped']:>8,}  (filtered)")

        # ── thumbnails ────────────────────────────────────────────────────────
        # Thumbnails and media samples hold only regenerable GUI assets, so a
        # read failure here (e.g. a corrupt source DB) is non-fatal: salvage
        # what was readable, warn, and keep the critical scan/file/folder data.
        src_file_ids = list(file_id_map.keys())
        if include_thumbnails:
            try:
                thumb_q = select(thumbnails)
                if file_set_reduced:
                    thumb_q = thumb_q.where(thumbnails.c.file_id.in_(src_file_ids))
                total = sc.execute(select(func.count()).select_from(thumb_q.subquery())).scalar() or 0
                for row in sc.execute(thumb_q.execution_options(**src_opts)):
                    m = row._mapping
                    new_fid = file_id_map.get(m["file_id"])
                    if new_fid is None:
                        continue
                    d = {k: m[k] for k in _THUMB_COLS}
                    dc.execute(insert(thumbnails).values(file_id=new_fid, **d))
                    stats["thumbnails"] += 1
                    _stage("thumbnails", stats["thumbnails"], total)
            except DatabaseError as e:
                _emit(f"  ⚠ thumbnails: read failed after {stats['thumbnails']:,} "
                      f"row(s) — skipping the rest (source likely corrupt): {e.orig}")
            _stage("thumbnails", stats["thumbnails"], stats["thumbnails"])
            _emit(f"  thumbnails:     {stats['thumbnails']:>8,}")

        # ── media samples ─────────────────────────────────────────────────────
        if include_samples:
            try:
                sample_q = select(media_samples)
                if file_set_reduced:
                    sample_q = sample_q.where(media_samples.c.file_id.in_(src_file_ids))
                total = sc.execute(select(func.count()).select_from(sample_q.subquery())).scalar() or 0
                for row in sc.execute(sample_q.execution_options(**src_opts)):
                    m = row._mapping
                    new_fid = file_id_map.get(m["file_id"])
                    if new_fid is None:
                        continue
                    d = {k: m[k] for k in _SAMPLE_COLS}
                    dc.execute(insert(media_samples).values(file_id=new_fid, **d))
                    stats["samples"] += 1
                    _stage("samples", stats["samples"], total)
            except DatabaseError as e:
                _emit(f"  ⚠ samples: read failed after {stats['samples']:,} "
                      f"row(s) — skipping the rest (source likely corrupt): {e.orig}")
            _stage("samples", stats["samples"], stats["samples"])
            _emit(f"  samples:        {stats['samples']:>8,}")

        # ── blob zip write (optional) ─────────────────────────────────────────
        if write_blobs_zip is not None:
            with zipfile.ZipFile(Path(write_blobs_zip), "w", zipfile.ZIP_DEFLATED) as zf:
                thumb_q = select(thumbnails)
                if file_set_reduced:
                    thumb_q = thumb_q.where(thumbnails.c.file_id.in_(src_file_ids))
                total = sc.execute(select(func.count()).select_from(thumb_q.subquery())).scalar() or 0
                n = 0
                for row in sc.execute(thumb_q.execution_options(**src_opts)):
                    m = row._mapping
                    dst_fid = file_id_map.get(m["file_id"])
                    if dst_fid is None:
                        continue
                    zf.writestr(f"thumbnails/{dst_fid}", bytes(m["data"]))
                    meta = {k: m[k] for k in ("width", "height") if m[k] is not None}
                    if meta:
                        zf.writestr(f"thumbnails/{dst_fid}.json", json.dumps(meta))
                    stats["thumbnails"] += 1
                    n += 1
                    _stage("thumbnails", n, total)
                _stage("thumbnails", n, n)
                _emit(f"  thumbnails:     {stats['thumbnails']:>8,}  (zip)")

                sample_q = select(media_samples)
                if file_set_reduced:
                    sample_q = sample_q.where(media_samples.c.file_id.in_(src_file_ids))
                total = sc.execute(select(func.count()).select_from(sample_q.subquery())).scalar() or 0
                n = 0
                for row in sc.execute(sample_q.execution_options(**src_opts)):
                    m = row._mapping
                    dst_fid = file_id_map.get(m["file_id"])
                    if dst_fid is None:
                        continue
                    zf.writestr(f"samples/{dst_fid}", bytes(m["data"]))
                    meta = {k: m[k] for k in ("format", "duration") if m[k] is not None}
                    if meta:
                        zf.writestr(f"samples/{dst_fid}.json", json.dumps(meta))
                    stats["samples"] += 1
                    n += 1
                    _stage("samples", n, total)
                _stage("samples", n, n)
                _emit(f"  samples:        {stats['samples']:>8,}  (zip)")

        # ── blob zip read (optional) ──────────────────────────────────────────
        if read_blobs_zip is not None:
            zip_path = Path(read_blobs_zip)
            if not zip_path.exists():
                _emit(f"  ⚠ blob zip not found: {zip_path} — skipping")
            else:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zip_names = set(zf.namelist())
                    thumb_entries = [
                        (name, int(name[len("thumbnails/"):]))
                        for name in zip_names
                        if name.startswith("thumbnails/") and not name.endswith(".json")
                        and name[len("thumbnails/"):].isdigit()
                    ]
                    total = len(thumb_entries)
                    for i, (name, src_fid) in enumerate(thumb_entries):
                        dst_fid = file_id_map.get(src_fid)
                        if dst_fid is None:
                            continue
                        data = zf.read(name)
                        meta_name = f"thumbnails/{src_fid}.json"
                        meta = json.loads(zf.read(meta_name)) if meta_name in zip_names else {}
                        dc.execute(insert(thumbnails).values(
                            file_id=dst_fid, data=data,
                            width=meta.get("width"), height=meta.get("height"),
                        ))
                        stats["thumbnails"] += 1
                        _stage("thumbnails", i + 1, total)
                    _stage("thumbnails", stats["thumbnails"], stats["thumbnails"])
                    _emit(f"  thumbnails:     {stats['thumbnails']:>8,}  (zip)")

                    sample_entries = [
                        (name, int(name[len("samples/"):]))
                        for name in zip_names
                        if name.startswith("samples/") and not name.endswith(".json")
                        and name[len("samples/"):].isdigit()
                    ]
                    total = len(sample_entries)
                    for i, (name, src_fid) in enumerate(sample_entries):
                        dst_fid = file_id_map.get(src_fid)
                        if dst_fid is None:
                            continue
                        data = zf.read(name)
                        meta_name = f"samples/{src_fid}.json"
                        meta = json.loads(zf.read(meta_name)) if meta_name in zip_names else {}
                        dc.execute(insert(media_samples).values(
                            file_id=dst_fid, data=data,
                            format=meta.get("format"), duration=meta.get("duration"),
                        ))
                        stats["samples"] += 1
                        _stage("samples", i + 1, total)
                    _stage("samples", stats["samples"], stats["samples"])
                    _emit(f"  samples:        {stats['samples']:>8,}  (zip)")

        # ── analysis runs (optional) ──────────────────────────────────────────
        if include_analysis:
            stats["analysis_runs"] = 0
            analysis_q = select(analysis_runs)
            total = sc.execute(select(func.count()).select_from(analysis_q.subquery())).scalar() or 0
            for row in sc.execute(analysis_q.execution_options(**src_opts)):
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
