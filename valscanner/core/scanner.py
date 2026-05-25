from __future__ import annotations
import json
import logging
import mimetypes
import os
import sys
import time
from collections import deque
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
    exclude_patterns: "list[str] | None" = None,
) -> int:
    """Quick pre-count of files that scan() will index (same filters, no I/O per file)."""
    import fnmatch as _fnmatch
    root_resolved = Path(root).resolve()

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
        dirpath_resolved = Path(dirpath).resolve()
        for fname in filenames:
            ext = Path(fname).suffix.lower()
            if not _keep_file(fname, ext):
                continue
            if exclude_patterns:
                try:
                    rel = str((dirpath_resolved / fname).relative_to(root_resolved))
                except ValueError:
                    rel = fname
                if any(_fnmatch.fnmatch(rel, pat) for pat in exclude_patterns):
                    continue
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
    workers: int = 4,
    exclude_patterns: "list[str] | None" = None,
) -> dict:
    """Scan *root*, indexing every file into the database at *db_path*.

    Parameters
    ----------
    workers:
        Number of threads used for per-file I/O (hashing, metadata, thumbnails).
        DB writes always happen on the calling thread.  ``workers=1`` replicates
        the old single-threaded behaviour.
    exclude_patterns:
        List of glob patterns matched against each file's path relative to
        *root*.  Matching files are skipped (not counted in errors).
    """
    import fnmatch as _fnmatch

    # `scan()` is the top-level entry for indexing. CLI/web/GUI callers run
    # `ensure_schema` at startup, but tests and direct API users call us with
    # a bare URL — make sure the schema exists either way. Idempotent.
    ensure_schema(active_url(db_path))
    repo = repo_for(db_path)

    workers = max(1, int(workers))

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
    _log.info("[scan] File timeout: %d seconds, workers: %d", file_timeout, workers)

    stats: dict = {
        "scanned": 0, "errors": 0, "skipped": 0, "timed_out": 0,
        "scan_id": scan_id, "total_bytes": 0,
        "resumed": actually_resumed,
    }
    folder_totals: dict = {}
    _skip_emit_counter = [0]  # list so closures can mutate without nonlocal

    def _emit(event: dict) -> None:
        if on_progress is not None:
            try:
                on_progress(event)
            except Exception:
                pass  # never let UI callbacks abort a scan

    # ------------------------------------------------------------------ #
    # Filters                                                              #
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # Ancestor-chain cache (keyed by resolved dir string)                 #
    # Maps each resolved directory to the ordered list of ancestor keys   #
    # from that dir up to (and including) root_resolved.  Built lazily    #
    # on first access; reused for every file in the same directory.       #
    # ------------------------------------------------------------------ #
    _ancestor_cache: dict = {}

    def _get_ancestors(dirpath_resolved: Path) -> list:
        key = str(dirpath_resolved)
        if key not in _ancestor_cache:
            ancestors: list = []
            p = dirpath_resolved
            while True:
                ancestors.append(str(p))
                if p == root_resolved:
                    break
                parent = p.parent
                if parent == p:
                    break
                p = parent
            _ancestor_cache[key] = ancestors
        return _ancestor_cache[key]

    # ------------------------------------------------------------------ #
    # Per-file worker (runs in thread pool — no DB access here)           #
    # ------------------------------------------------------------------ #

    def _process_file(fpath: Path, fname: str, now: str,
                      fpath_resolved: Path) -> dict | None:
        """Process a single file and return result dict. No DB writes."""
        _log.debug("[process] Starting: %s", fpath)
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

        tags = generate_tags(fpath, category, size)

        if compute_hash:
            sha = file_sha256(fpath)
        else:
            sha = ""

        created = getattr(st, "st_birthtime", st.st_ctime)

        row = {
            "scan_id":     scan_id,
            "path":        str(fpath_resolved),   # already resolved — no second call
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

        _log.debug("[process] Done: %s", fpath)
        return {"row": row, "fpath": fpath, "size": size, "category": category}

    # ------------------------------------------------------------------ #
    # Verbose helper — clears the progress bar line on TTY               #
    # ------------------------------------------------------------------ #

    def _verbose_print(msg: str) -> None:
        if sys.stdout.isatty() and on_progress is not None:
            print(f"\r{' ' * 79}\r{msg}")
        else:
            print(msg)

    # ------------------------------------------------------------------ #
    # DB commit helper (main thread only)                                 #
    # ------------------------------------------------------------------ #

    def _commit_result(result: dict, fpath_: Path,
                       dirpath_resolved_: Path) -> None:
        """Write a processed file to DB. Must be called from the main thread."""
        row       = result["row"]
        size_     = result["size"]
        category_ = result["category"]

        try:
            _log.debug("[db] Inserting: %s", fpath_)
            file_id = repo.insert_file(row)
            _log.debug("[db] Inserted file_id=%d", file_id)
        except DuplicateRecordError:
            _log.debug("[db] Duplicate (race): %s", fpath_)
            stats["skipped"] += 1
            _skip_emit_counter[0] += 1
            if _skip_emit_counter[0] >= 10:
                _emit({"scanned": stats["scanned"], "skipped": stats["skipped"],
                       "path": str(fpath_)})
                _skip_emit_counter[0] = 0
            return

        if store_thumbnails:
            thumb = None
            if category_ in ("photo", "image"):
                _log.debug("[thumb] image: %s", fpath_)
                thumb = _thumb_image(fpath_, thumb_size, thumb_quality)
            elif category_ == "video":
                _log.debug("[thumb] video: %s", fpath_)
                thumb = _thumb_video(fpath_, thumb_size, thumb_quality)
            if thumb:
                repo.save_thumbnail(file_id, thumb, 0, 0)

        if store_samples and category_ in ("audio", "video"):
            _log.debug("[sample] %s (%s)", fpath_, category_)
            sample = _sample_media(fpath_, category_, sample_duration)
            if sample:
                data, fmt = sample
                repo.save_media_sample(file_id, data, fmt, float(sample_duration))

        stats["scanned"]     += 1
        stats["total_bytes"] += size_

        # Update folder totals using the cached ancestor chain
        for key in _get_ancestors(dirpath_resolved_):
            entry = folder_totals.setdefault(key, [0, 0])
            entry[0] += 1
            entry[1] += size_

        if verbose:
            _verbose_print(f"  [{category_:14s}] {fpath_}")

        _emit({"scanned": stats["scanned"], "skipped": stats["skipped"],
               "path": str(fpath_)})

    # ------------------------------------------------------------------ #
    # Bounded in-flight queue + drain helper                              #
    # ------------------------------------------------------------------ #
    #
    # Each element: (future, fpath, dirpath_resolved, submit_time)
    # The window is capped at `workers` entries; the main thread drains
    # the oldest (FIFO) future before submitting a new one.
    #
    in_flight: deque = deque()

    def _drain_one() -> None:
        """Pop the oldest future and process its result (or handle timeout/error)."""
        if not in_flight:
            return
        future_, fpath_, dirpr_, submit_time_ = in_flight.popleft()
        remaining = (submit_time_ + file_timeout) - time.time() if file_timeout else None
        if remaining is not None:
            remaining = max(0.001, remaining)
        try:
            result = future_.result(timeout=remaining)
            if result is None:
                stats["timed_out"] += 1
                if verbose:
                    _verbose_print(f"  [TIMEOUT] {fpath_}")
                return
            _commit_result(result, fpath_, dirpr_)
        except FuturesTimeoutError:
            stats["timed_out"] += 1
            _log.warning("[timeout] %s", fpath_)
            if verbose:
                _verbose_print(f"  [TIMEOUT] {fpath_}")
        except (PermissionError, FileNotFoundError, OSError) as e:
            stats["errors"] += 1
            _log.error("[error] %s: %s", fpath_, e)
            if verbose:
                _verbose_print(f"  [ERROR] {fpath_}: {e}")
        except Exception as e:
            stats["errors"] += 1
            _log.error("[error] unexpected processing %s: %s", fpath_, e)

    # ------------------------------------------------------------------ #
    # Main walk loop                                                       #
    # ------------------------------------------------------------------ #

    executor = ThreadPoolExecutor(max_workers=workers)

    for dirpath, dirnames, filenames in os.walk(root):
        if cancel_event is not None and cancel_event.is_set():
            stats["cancelled"] = True
            _log.info("[scan] Cancelled by user")
            break

        _log.debug("[walk] %s (%d files, %d subdirs)", dirpath, len(filenames), len(dirnames))
        dirnames[:] = [d for d in dirnames if _keep_dir(d)]

        # Resolve the directory once; used for ancestor caching and as
        # the parent for relative-path exclude matching.
        dirpath_resolved = Path(dirpath).resolve()

        for fname in filenames:
            if cancel_event is not None and cancel_event.is_set():
                stats["cancelled"] = True
                _log.info("[scan] Cancelled by user")
                break

            ext_check = Path(fname).suffix.lower()
            if not _keep_file(fname, ext_check):
                _log.debug("[skip] filter: %s", fname)
                stats["skipped"] += 1
                continue

            # Resolve path once here; passed straight into _process_file
            # so the worker never needs to call .resolve() again.
            fpath = Path(dirpath) / fname
            fpath_resolved = fpath.resolve()

            # Exclude-pattern check (relative to scan root)
            if exclude_patterns:
                try:
                    rel = str(fpath_resolved.relative_to(root_resolved))
                except ValueError:
                    rel = fname
                if any(_fnmatch.fnmatch(rel, pat) for pat in exclude_patterns):
                    _log.debug("[skip] excluded: %s", fpath_resolved)
                    stats["skipped"] += 1
                    continue

            # Skip already-indexed files (resume optimisation)
            if repo.file_exists(scan_id, str(fpath_resolved)):
                _log.debug("[skip] already indexed: %s", fpath_resolved)
                stats["skipped"] += 1
                _skip_emit_counter[0] += 1
                if _skip_emit_counter[0] >= 10:
                    _emit({"scanned": stats["scanned"], "skipped": stats["skipped"],
                           "path": str(fpath_resolved)})
                    _skip_emit_counter[0] = 0
                continue

            # Keep window bounded: drain oldest before adding a new future
            while len(in_flight) >= workers:
                _drain_one()
                if cancel_event is not None and cancel_event.is_set():
                    stats["cancelled"] = True
                    break

            if stats.get("cancelled"):
                break

            future = executor.submit(_process_file, fpath, fname, now, fpath_resolved)
            in_flight.append((future, fpath, dirpath_resolved, time.time()))

        if stats.get("cancelled"):
            break

    # Drain all remaining in-flight futures
    while in_flight:
        _drain_one()

    # Threads that exceeded their timeout may still be running; don't block
    # the main thread waiting for them — they'll eventually finish or be GC'd.
    executor.shutdown(wait=False)

    # On resume the in-memory folder_totals only covers newly-indexed files;
    # rebuild from DB so every ancestor folder reflects the full picture.
    if actually_resumed:
        folder_totals = _rebuild_folder_totals_from_db(repo, scan_id, root_resolved)

    indexed_at = ts(time.time())
    _log.debug("[db] Upserting %d folder records", len(folder_totals))
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
    _log.info(
        "[scan] #%d finished — status=%s, files=%d, bytes=%d, "
        "errors=%d, skipped=%d, timed_out=%d",
        scan_id, final_status, final_count, final_bytes,
        stats["errors"], stats["skipped"], stats["timed_out"],
    )
    _emit({"done": True, "scan_id": scan_id, "scanned": stats["scanned"]})
    return stats
