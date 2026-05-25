from __future__ import annotations
import json
import logging
import mimetypes
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from pathlib import Path

_log = logging.getLogger(__name__)

from .app_settings import active_url
from .bootstrap import ensure_schema
from .categories import EXT_CATEGORY, MIME_CATEGORY
from .db import repo_for
from .exceptions import DuplicateRecordError
from .filters import (
    SYSTEM_DIRS as _SYSTEM_DIRS,
    CACHE_DIRS as _CACHE_DIRS,
    VCS_DIRS as _VCS_DIRS,
    BINARY_EXTS as _BINARY_EXTS,
    TEMP_EXTS as _TEMP_EXTS,
    LOG_EXTS as _LOG_EXTS,
)
from .metadata import (
    extract_image_metadata, extract_audio_metadata, extract_pdf_metadata,
    file_sha256, _thumb_image, _thumb_video, _sample_media,
)
from .schema import human_size, ts
from .tagging import generate_tags


def count_files(
    root: Path,
    skip_hidden_dirs: bool = True,
    skip_vcs: bool = False,
    skip_system: bool = False,
    skip_caches: bool = False,
    skip_hidden_files: bool = False,
    skip_binaries: bool = False,
    skip_temp: bool = False,
    skip_logs: bool = False,
) -> int:
    """Quick pre-count of files that scan() will index (same filters, no I/O per file)."""
    def _keep_dir(name: str) -> bool:
        if skip_hidden_dirs and name.startswith("."):
            return False
        if skip_vcs and name in _VCS_DIRS:
            return False
        if skip_system and name in _SYSTEM_DIRS:
            return False
        if skip_caches and name in _CACHE_DIRS:
            return False
        return True

    def _keep_file(name: str, ext: str) -> bool:
        if skip_hidden_files and name.startswith("."):
            return False
        if skip_binaries and ext in _BINARY_EXTS:
            return False
        if skip_temp and (ext in _TEMP_EXTS or name == ".DS_Store"):
            return False
        if skip_logs and ext in _LOG_EXTS:
            return False
        return True

    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if _keep_dir(d)]
        for fname in filenames:
            if _keep_file(fname, Path(fname).suffix.lower()):
                total += 1
    return total


def _rebuild_folder_totals_from_db(repo, scan_id: int, root: Path) -> dict:
    """Recompute the full folder hierarchy from DB rows for a resumed scan."""
    totals: dict = {}
    for row in repo.iter_files_for_export(scan_id):
        size = row["size_bytes"] or 0
        folder = Path(row["path"]).parent
        while True:
            key = str(folder)
            entry = totals.setdefault(key, [0, 0])
            entry[0] += 1
            entry[1] += size
            if folder == root:
                break
            parent = folder.parent
            if parent == folder:
                break
            folder = parent
    return totals


def scan(
    root: Path,
    db_path: str,
    compute_hash: bool = True,
    verbose: bool = False,
    label: str = "",
    store_thumbnails: bool = False,
    thumb_size: int = 128,
    thumb_quality: int = 75,
    store_samples: bool = False,
    sample_duration: int = 5,
    skip_hidden_files: bool = False,
    skip_hidden_dirs:  bool = True,
    skip_system:       bool = False,
    skip_caches:       bool = False,
    skip_vcs:          bool = False,
    skip_binaries:     bool = False,
    skip_temp:         bool = False,
    skip_logs:         bool = False,
    cancel_event=None,
    scan_id: int | None = None,
    resume: bool = False,
    on_progress: Callable[[dict], None] | None = None,
    file_timeout: int = 120,
) -> dict:
    # `scan()` is the top-level entry for indexing. CLI/web/GUI callers run
    # `ensure_schema` at startup, but tests and direct API users call us with
    # a bare URL — make sure the schema exists either way. Idempotent.
    ensure_schema(active_url(db_path))
    repo = repo_for(db_path)

    now        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scan_label = label.strip() or root.name
    root_resolved = root.resolve()

    actually_resumed = False
    if resume and scan_id is None:
        _log.info("[resume] Looking for interrupted scan at root: %s", root_resolved)
        found = repo.find_interrupted_scan(str(root_resolved))
        _log.info("[resume] find_interrupted_scan returned: %s", found)
        if found is not None:
            scan_id = found
            actually_resumed = True

    if scan_id is None:
        scan_id = repo.create_scan(root=str(root_resolved), label=scan_label, scanned_at=now)
        _log.info("[scan] Started NEW scan #%d for root: %s", scan_id, root_resolved)
    elif actually_resumed:
        _log.info("[scan] RESUMING existing scan #%d for root: %s", scan_id, root_resolved)
    else:
        _log.info("[scan] Continuing scan #%d (explicit scan_id) for root: %s", scan_id, root_resolved)

    repo.set_scan_status(scan_id, "running")
    _log.info("[scan] Set scan #%d status → running", scan_id)
    _log.info("[scan] File timeout: %d seconds", file_timeout)

    stats: dict = {
        "scanned": 0, "errors": 0, "skipped": 0, "timed_out": 0,
        "scan_id": scan_id, "total_bytes": 0,
        "resumed": actually_resumed,
    }
    folder_totals: dict = {}
    _skip_emit_counter = 0  # Only emit progress every N skipped files to reduce callback frequency

    def _emit(event: dict) -> None:
        if on_progress is not None:
            try:
                on_progress(event)
            except Exception:
                pass  # never let UI callbacks abort a scan

    def _keep_dir(name: str) -> bool:
        if skip_hidden_dirs and name.startswith("."):
            return False
        if skip_vcs and name in _VCS_DIRS:
            return False
        if skip_system and name in _SYSTEM_DIRS:
            return False
        if skip_caches and name in _CACHE_DIRS:
            return False
        return True

    def _keep_file(name: str, ext: str) -> bool:
        if skip_hidden_files and name.startswith("."):
            return False
        if skip_binaries and ext in _BINARY_EXTS:
            return False
        if skip_temp and (ext in _TEMP_EXTS or name == ".DS_Store"):
            return False
        if skip_logs and ext in _LOG_EXTS:
            return False
        return True

    def _process_file(fpath: Path, fname: str, now: str) -> dict | None:
        """Process a single file and return result dict, or None on timeout."""
        _log.debug("[process] Starting to process file: %s", fpath)
        st       = fpath.stat()
        size     = st.st_size
        ext      = fpath.suffix.lower()
        _log.debug("[process] File size: %d bytes, extension: %s", size, ext)

        mime, _  = mimetypes.guess_type(str(fpath))
        category = EXT_CATEGORY.get(ext)
        if not category and mime:
            category = MIME_CATEGORY.get(mime.split("/")[0], "other")
        if not category:
            category = "other"
        _log.debug("[process] Detected category: %s, mime_type: %s", category, mime)

        extra: dict = {}
        if category == "photo":
            _log.debug("[metadata] Extracting image metadata for: %s", fpath)
            extra.update(extract_image_metadata(fpath))
        elif category == "audio":
            _log.debug("[metadata] Extracting audio metadata for: %s", fpath)
            extra.update(extract_audio_metadata(fpath))
        elif ext == ".pdf":
            _log.debug("[metadata] Extracting PDF metadata for: %s", fpath)
            extra.update(extract_pdf_metadata(fpath))

        if extra:
            _log.debug("[metadata] Extracted metadata: %s", extra)

        _log.debug("[tagging] Generating tags for: %s", fpath)
        tags    = generate_tags(fpath, category, size)
        _log.debug("[tagging] Generated tags: %s", tags)

        if compute_hash:
            _log.debug("[hash] Computing SHA-256 hash for: %s", fpath)
            sha     = file_sha256(fpath)
            _log.debug("[hash] Hash computed: %s", sha)
        else:
            sha = ""
            _log.debug("[hash] Hash computation skipped")

        created = getattr(st, "st_birthtime", st.st_ctime)

        row = {
            "scan_id":     scan_id,
            "path":        str(fpath.resolve()),
            "filename":    fname,
            "extension":   ext or "(none)",
            "category":    category,
            "mime_type":   mime or "",
            "size_bytes":  size,
            "size_human":  human_size(size),
            "sha256":      sha,
            "created_at":  ts(created),
            "modified_at": ts(st.st_mtime),
            "accessed_at": ts(st.st_atime),
            "is_hidden":   int(fname.startswith(".")),
            "tags":        ", ".join(tags),
            "extra_meta":  json.dumps(extra) if extra else "",
            "indexed_at":  now,
        }

        _log.debug("[process] Completed processing file: %s", fpath)
        return {"row": row, "fpath": fpath, "size": size, "category": category}

    executor = ThreadPoolExecutor(max_workers=1) if file_timeout is not None else None

    for dirpath, dirnames, filenames in os.walk(root):
        if cancel_event is not None and cancel_event.is_set():
            stats["cancelled"] = True
            _log.info("[scan] Scan cancelled by user")
            return stats

        _log.debug("[walk] Traversing directory: %s (%d files, %d subdirs)", dirpath, len(filenames), len(dirnames))
        dirnames[:] = [d for d in dirnames if _keep_dir(d)]
        _log.debug("[walk] After filtering: %d subdirs to traverse", len(dirnames))

        for fname in filenames:
            if cancel_event is not None and cancel_event.is_set():
                stats["cancelled"] = True
                _log.info("[scan] Scan cancelled by user")
                return stats
            ext_check = Path(fname).suffix.lower()
            if not _keep_file(fname, ext_check):
                _log.debug("[skip] File filtered out: %s (ext: %s)", fname, ext_check)
                stats["skipped"] += 1
                continue
            fpath = Path(dirpath) / fname
            try:
                if executor:
                    future = executor.submit(_process_file, fpath, fname, now)
                    result = future.result(timeout=file_timeout)
                else:
                    result = _process_file(fpath, fname, now)

                if result is None:
                    stats["timed_out"] += 1
                    if verbose:
                        print(f"  [TIMEOUT] {fpath}")
                    continue

                row = result["row"]
                size = result["size"]
                category = result["category"]

                try:
                    _log.debug("[db] Inserting file into database: %s", fpath)
                    file_id = repo.insert_file(row)
                    _log.debug("[db] File inserted with ID: %d", file_id)
                except DuplicateRecordError:
                    _log.debug("[db] File already exists in database: %s", fpath)
                    stats["skipped"] += 1
                    _skip_emit_counter += 1
                    if _skip_emit_counter >= 10:
                        _emit({"scanned": stats["scanned"], "skipped": stats["skipped"], "path": str(fpath)})
                        _skip_emit_counter = 0
                    continue

                if store_thumbnails:
                    thumb = None
                    if category in ("photo", "image"):
                        _log.debug("[thumb] Generating image thumbnail for: %s", fpath)
                        thumb = _thumb_image(fpath, thumb_size, thumb_quality)
                        if thumb:
                            _log.debug("[thumb] Thumbnail generated, saving to DB")
                    elif category == "video":
                        _log.debug("[thumb] Generating video thumbnail for: %s", fpath)
                        thumb = _thumb_video(fpath, thumb_size, thumb_quality)
                        if thumb:
                            _log.debug("[thumb] Thumbnail generated, saving to DB")
                    if thumb:
                        repo.save_thumbnail(file_id, thumb, 0, 0)

                if store_samples and category in ("audio", "video"):
                    _log.debug("[sample] Extracting media sample for: %s (%s)", fpath, category)
                    sample = _sample_media(fpath, category, sample_duration)
                    if sample:
                        data, fmt = sample
                        _log.debug("[sample] Sample extracted (%s format), saving to DB", fmt)
                        repo.save_media_sample(file_id, data, fmt, float(sample_duration))
                    else:
                        _log.debug("[sample] No sample extracted from: %s", fpath)

                stats["scanned"]     += 1
                stats["total_bytes"] += size
                _log.debug("[stats] Updated scan stats: scanned=%d, total_bytes=%d", stats["scanned"], stats["total_bytes"])

                folder = Path(dirpath).resolve()
                _log.debug("[folders] Updating folder totals for ancestors of: %s", folder)
                while True:
                    key = str(folder)
                    if key not in folder_totals:
                        folder_totals[key] = [0, 0]
                    folder_totals[key][0] += 1
                    folder_totals[key][1] += size
                    _log.debug("[folders] Updated folder: %s (files=%d, bytes=%d)", key, folder_totals[key][0], folder_totals[key][1])
                    if folder == root_resolved:
                        break
                    parent = folder.parent
                    if parent == folder:
                        break
                    folder = parent

                if verbose:
                    print(f"  [{category:14s}] {fpath}")

                _emit({"scanned": stats["scanned"], "skipped": stats["skipped"], "path": str(fpath)})

            except FuturesTimeoutError:
                stats["timed_out"] += 1
                _log.warning("[timeout] File exceeded timeout: %s", fpath)
                if verbose:
                    print(f"  [TIMEOUT] {fpath}")
            except (PermissionError, FileNotFoundError, OSError) as e:
                stats["errors"] += 1
                _log.error("[error] Failed to process file %s: %s", fpath, e)
                if verbose:
                    print(f"  [ERROR] {fpath}: {e}")

    if executor:
        executor.shutdown(wait=True)

    # On resume the in-memory folder_totals only covers newly-indexed files;
    # rebuild from DB so every ancestor folder reflects the full picture.
    if actually_resumed:
        folder_totals = _rebuild_folder_totals_from_db(repo, scan_id, root_resolved)

    indexed_at = ts(time.time())
    _log.debug("[db] Upserting %d folder records", len(folder_totals))
    for fpath_str, (fc, tb) in folder_totals.items():
        _log.debug("[db] Upserting folder: %s (files=%d, bytes=%d)", fpath_str, fc, tb)
        repo.upsert_folder(
            scan_id=scan_id, path=fpath_str,
            file_count=fc, total_bytes=tb,
            total_human=human_size(tb),
            indexed_at=indexed_at,
        )

    root_key = str(root_resolved)
    if root_key in folder_totals:
        final_count = folder_totals[root_key][0]
        final_bytes = folder_totals[root_key][1]
    else:
        final_count = stats["scanned"]
        final_bytes = stats["total_bytes"]

    repo.update_scan_totals(scan_id, final_count, final_bytes, human_size(final_bytes))
    final_status = "resumed" if actually_resumed else "complete"
    repo.set_scan_status(scan_id, final_status)
    _log.info("[scan] Scan #%d finished — status=%s, files=%d, bytes=%d, errors=%d, skipped=%d, timed_out=%d",
              scan_id, final_status, final_count, final_bytes, stats["errors"], stats["skipped"], stats["timed_out"])
    _emit({"done": True, "scan_id": scan_id, "scanned": stats["scanned"]})
    return stats
