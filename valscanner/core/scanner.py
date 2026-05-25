from __future__ import annotations
import json
import logging
import mimetypes
import os
import time
from collections.abc import Callable
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

    stats: dict = {
        "scanned": 0, "errors": 0, "skipped": 0,
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

    for dirpath, dirnames, filenames in os.walk(root):
        if cancel_event is not None and cancel_event.is_set():
            stats["cancelled"] = True
            return stats

        dirnames[:] = [d for d in dirnames if _keep_dir(d)]

        for fname in filenames:
            if cancel_event is not None and cancel_event.is_set():
                stats["cancelled"] = True
                return stats
            ext_check = Path(fname).suffix.lower()
            if not _keep_file(fname, ext_check):
                stats["skipped"] += 1
                continue
            fpath = Path(dirpath) / fname
            try:
                st       = fpath.stat()
                size     = st.st_size
                ext      = fpath.suffix.lower()
                mime, _  = mimetypes.guess_type(str(fpath))
                category = EXT_CATEGORY.get(ext)
                if not category and mime:
                    category = MIME_CATEGORY.get(mime.split("/")[0], "other")
                if not category:
                    category = "other"

                extra: dict = {}
                if category == "photo":
                    extra.update(extract_image_metadata(fpath))
                elif category == "audio":
                    extra.update(extract_audio_metadata(fpath))
                elif ext == ".pdf":
                    extra.update(extract_pdf_metadata(fpath))

                tags    = generate_tags(fpath, category, size)
                sha     = file_sha256(fpath) if compute_hash else ""
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

                try:
                    file_id = repo.insert_file(row)
                except DuplicateRecordError:
                    stats["skipped"] += 1
                    _skip_emit_counter += 1
                    # Emit progress every 10 skipped files to show activity without excessive callbacks
                    if _skip_emit_counter >= 10:
                        _emit({"scanned": stats["scanned"], "skipped": stats["skipped"], "path": str(fpath)})
                        _skip_emit_counter = 0
                    continue

                if store_thumbnails:
                    thumb = None
                    if category in ("photo", "image"):
                        thumb = _thumb_image(fpath, thumb_size, thumb_quality)
                    elif category == "video":
                        thumb = _thumb_video(fpath, thumb_size, thumb_quality)
                    if thumb:
                        repo.save_thumbnail(file_id, thumb, 0, 0)

                if store_samples and category in ("audio", "video"):
                    sample = _sample_media(fpath, category, sample_duration)
                    if sample:
                        data, fmt = sample
                        repo.save_media_sample(file_id, data, fmt, float(sample_duration))

                stats["scanned"]     += 1
                stats["total_bytes"] += size

                folder = Path(dirpath).resolve()
                while True:
                    key = str(folder)
                    if key not in folder_totals:
                        folder_totals[key] = [0, 0]
                    folder_totals[key][0] += 1
                    folder_totals[key][1] += size
                    if folder == root_resolved:
                        break
                    parent = folder.parent
                    if parent == folder:
                        break
                    folder = parent

                if verbose:
                    print(f"  [{category:14s}] {fpath}")

                _emit({"scanned": stats["scanned"], "skipped": stats["skipped"], "path": str(fpath)})

            except (PermissionError, FileNotFoundError, OSError) as e:
                stats["errors"] += 1
                if verbose:
                    print(f"  [ERROR] {fpath}: {e}")

    # On resume the in-memory folder_totals only covers newly-indexed files;
    # rebuild from DB so every ancestor folder reflects the full picture.
    if actually_resumed:
        folder_totals = _rebuild_folder_totals_from_db(repo, scan_id, root_resolved)

    indexed_at = ts(time.time())
    for fpath_str, (fc, tb) in folder_totals.items():
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
    _log.info("[scan] Scan #%d finished — status=%s, files=%d, bytes=%d",
              scan_id, final_status, final_count, final_bytes)
    _emit({"done": True, "scan_id": scan_id, "scanned": stats["scanned"]})
    return stats
