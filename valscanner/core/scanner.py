from __future__ import annotations
import json
import mimetypes
import os
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

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
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    # `scan()` is the top-level entry for indexing. CLI/web/GUI callers run
    # `ensure_schema` at startup, but tests and direct API users call us with
    # a bare URL — make sure the schema exists either way. Idempotent.
    ensure_schema(active_url(db_path))
    repo = repo_for(db_path)

    now        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scan_label = label.strip() or root.name

    if scan_id is None:
        scan_id = repo.create_scan(root=str(root), label=scan_label, scanned_at=now)

    stats: dict = {"scanned": 0, "errors": 0, "skipped": 0, "scan_id": scan_id, "total_bytes": 0}
    folder_totals: dict = {}

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
                    if folder == root:
                        break
                    parent = folder.parent
                    if parent == folder:
                        break
                    folder = parent

                if verbose:
                    print(f"  [{category:14s}] {fpath}")

                _emit({"scanned": stats["scanned"], "path": str(fpath)})

            except (PermissionError, FileNotFoundError, OSError) as e:
                stats["errors"] += 1
                if verbose:
                    print(f"  [ERROR] {fpath}: {e}")

    indexed_at = ts(time.time())
    for fpath_str, (fc, tb) in folder_totals.items():
        repo.upsert_folder(
            scan_id=scan_id, path=fpath_str,
            file_count=fc, total_bytes=tb,
            total_human=human_size(tb),
            indexed_at=indexed_at,
        )

    repo.update_scan_totals(
        scan_id, stats["scanned"], stats["total_bytes"],
        human_size(stats["total_bytes"]),
    )
    _emit({"done": True, "scan_id": scan_id, "scanned": stats["scanned"]})
    return stats
