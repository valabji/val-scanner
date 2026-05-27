from __future__ import annotations
import json
import logging
import mimetypes
import os
import sys
import time
from collections import deque
from collections.abc import Callable, Iterable
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


# Phase identifiers — accepted by scan(phases=…) and the CLI's --phases flag.
PHASE_ENUMERATE  = "enumerate"
PHASE_METADATA   = "metadata"
PHASE_THUMBNAILS = "thumbnails"
PHASE_HASH       = "hash"
PHASE_SAMPLES    = "samples"
ALL_PHASES = (
    PHASE_ENUMERATE, PHASE_METADATA, PHASE_THUMBNAILS,
    PHASE_HASH, PHASE_SAMPLES,
)


# ---------------------------------------------------------------------- #
# Per-file work helpers (pure; no DB access; safe to run in threads)     #
# ---------------------------------------------------------------------- #

def _extract_metadata_for_file(fpath: Path, category: str, ext: str) -> dict:
    if category == "photo":
        return dict(extract_image_metadata(fpath))
    if category == "audio":
        return dict(extract_audio_metadata(fpath))
    if ext == ".pdf":
        return dict(extract_pdf_metadata(fpath))
    return {}


def _make_thumbnail(fpath: Path, category: str, size: int, quality: int):
    if category in ("photo", "image"):
        return _thumb_image(fpath, size, quality)
    if category == "video":
        return _thumb_video(fpath, size, quality)
    return None


def _make_sample(fpath: Path, category: str, duration: int):
    if category in ("audio", "video"):
        return _sample_media(fpath, category, duration)
    return None


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


# ---------------------------------------------------------------------- #
# Bounded-window thread pool                                              #
# ---------------------------------------------------------------------- #

def _run_pool(
    items: Iterable,
    work_fn: Callable,
    commit_fn: Callable,
    *,
    workers: int,
    file_timeout: int,
    cancel_event,
    stats: dict,
    verbose_print: Callable | None = None,
) -> None:
    """Run *work_fn(item)* concurrently; call *commit_fn(item, result)* on the
    main thread. FIFO drain preserves submission order. work_fn returning None
    silently skips the item (no commit, no error).
    """
    workers = max(1, int(workers))
    in_flight: deque = deque()
    executor = ThreadPoolExecutor(max_workers=workers)

    def _vp(msg: str) -> None:
        if verbose_print is not None:
            try:
                verbose_print(msg)
            except Exception:
                pass

    def _drain_one() -> None:
        if not in_flight:
            return
        future_, item_, submit_t_ = in_flight.popleft()
        remaining = (submit_t_ + file_timeout) - time.time() if file_timeout else None
        if remaining is not None:
            remaining = max(0.001, remaining)
        try:
            result = future_.result(timeout=remaining)
            if result is None:
                stats["noop"] = stats.get("noop", 0) + 1
                return
            commit_fn(item_, result)
        except FuturesTimeoutError:
            stats["timed_out"] = stats.get("timed_out", 0) + 1
            _log.warning("[timeout] %r", item_)
            _vp(f"  [TIMEOUT] {item_!r}")
        except (PermissionError, FileNotFoundError, OSError) as e:
            stats["errors"] = stats.get("errors", 0) + 1
            _log.error("[error] %r: %s", item_, e)
            _vp(f"  [ERROR] {item_!r}: {e}")
        except Exception as e:
            stats["errors"] = stats.get("errors", 0) + 1
            _log.error("[error] unexpected processing %r: %s", item_, e)

    try:
        for item in items:
            if cancel_event is not None and cancel_event.is_set():
                stats["cancelled"] = True
                break
            while len(in_flight) >= workers:
                _drain_one()
                if cancel_event is not None and cancel_event.is_set():
                    stats["cancelled"] = True
                    break
            if stats.get("cancelled"):
                break
            future = executor.submit(work_fn, item)
            in_flight.append((future, item, time.time()))

        while in_flight:
            _drain_one()
    finally:
        executor.shutdown(wait=False)


def _make_verbose_printer(verbose: bool, has_progress_cb: bool) -> Callable[[str], None]:
    def _vp(msg: str) -> None:
        if not verbose:
            return
        if sys.stdout.isatty() and has_progress_cb:
            print(f"\r{' ' * 79}\r{msg}")
        else:
            print(msg)
    return _vp


def _emit_factory(on_progress):
    def _emit(event: dict) -> None:
        if on_progress is not None:
            try:
                on_progress(event)
            except Exception:
                pass  # never let UI callbacks abort a scan
    return _emit


# ====================================================================== #
# Phase 1 — enumerate_only                                               #
# ====================================================================== #

def enumerate_only(
    root: Path,
    db_path: str,
    *,
    verbose: bool = False,
    label: str = "",
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
    """Phase 1: walk *root*, insert one minimal `files` row per kept file.

    Inserts rows with empty `sha256` and `extra_meta`; no thumbnails or
    media samples are produced. Use the enrich_* functions afterwards.
    """
    import fnmatch as _fnmatch

    ensure_schema(active_url(db_path))
    repo = repo_for(db_path)
    workers = max(1, int(workers))

    now           = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scan_label    = label.strip() or root.name
    root_resolved = root.resolve()

    actually_resumed = False
    if resume and scan_id is None:
        _log.info("[resume] Looking for interrupted scan at root: %s", root_resolved)
        found = repo.find_interrupted_scan(str(root_resolved))
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
    _log.info("[scan] File timeout: %d seconds, workers: %d", file_timeout, workers)

    stats: dict = {
        "phase": PHASE_ENUMERATE,
        "scanned": 0, "errors": 0, "skipped": 0, "timed_out": 0,
        "scan_id": scan_id, "total_bytes": 0,
        "resumed": actually_resumed,
    }
    folder_totals: dict = {}
    _skip_emit_counter = [0]

    _emit = _emit_factory(on_progress)
    _vp = _make_verbose_printer(verbose, on_progress is not None)

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

    def _process_one(item: dict) -> dict | None:
        """Stat + categorize + tag (no metadata/hash/thumb/sample). Thread-safe."""
        fpath = item["fpath"]
        fname = item["fname"]
        fpath_resolved = item["fpath_resolved"]

        st       = fpath.stat()
        size     = st.st_size
        ext      = fpath.suffix.lower()

        mime, _  = mimetypes.guess_type(str(fpath))
        category = EXT_CATEGORY.get(ext)
        if not category and mime:
            category = MIME_CATEGORY.get(mime.split("/")[0], "other")
        if not category:
            category = "other"

        tags = generate_tags(fpath, category, size)
        created = getattr(st, "st_birthtime", st.st_ctime)

        row = {
            "scan_id":     scan_id,
            "path":        str(fpath_resolved),
            "filename":    fname,
            "extension":   ext or "(none)",
            "category":    category,
            "mime_type":   mime or "",
            "size_bytes":  size,
            "size_human":  human_size(size),
            "sha256":      "",
            "created_at":  ts(created),
            "modified_at": ts(st.st_mtime),
            "accessed_at": ts(st.st_atime),
            "is_hidden":   int(fname.startswith(".")),
            "tags":        ", ".join(tags),
            "extra_meta":  "",
            "indexed_at":  now,
        }
        return {"row": row, "size": size, "category": category}

    def _commit_one(item: dict, result: dict) -> None:
        fpath_ = item["fpath"]
        dirpr_ = item["dirpath_resolved"]
        row    = result["row"]
        size_  = result["size"]
        category_ = result["category"]

        try:
            repo.insert_file(row)
        except DuplicateRecordError:
            stats["skipped"] += 1
            _skip_emit_counter[0] += 1
            if _skip_emit_counter[0] >= 10:
                _emit({"phase": PHASE_ENUMERATE,
                       "scanned": stats["scanned"], "skipped": stats["skipped"],
                       "path": str(fpath_)})
                _skip_emit_counter[0] = 0
            return

        stats["scanned"]     += 1
        stats["total_bytes"] += size_

        for key in _get_ancestors(dirpr_):
            entry = folder_totals.setdefault(key, [0, 0])
            entry[0] += 1
            entry[1] += size_

        if verbose:
            _vp(f"  [{category_:14s}] {fpath_}")

        _emit({"phase": PHASE_ENUMERATE,
               "scanned": stats["scanned"], "skipped": stats["skipped"],
               "path": str(fpath_)})

    def _iter_walk_items():
        for dirpath, dirnames, filenames in os.walk(root):
            if cancel_event is not None and cancel_event.is_set():
                return
            dirnames[:] = [d for d in dirnames if _keep_dir(d)]
            dirpath_resolved = Path(dirpath).resolve()

            for fname in filenames:
                if cancel_event is not None and cancel_event.is_set():
                    return

                ext_check = Path(fname).suffix.lower()
                if not _keep_file(fname, ext_check):
                    stats["skipped"] += 1
                    continue

                fpath = Path(dirpath) / fname
                fpath_resolved = fpath.resolve()

                if exclude_patterns:
                    try:
                        rel = str(fpath_resolved.relative_to(root_resolved))
                    except ValueError:
                        rel = fname
                    if any(_fnmatch.fnmatch(rel, pat) for pat in exclude_patterns):
                        stats["skipped"] += 1
                        continue

                if repo.file_exists(scan_id, str(fpath_resolved)):
                    stats["skipped"] += 1
                    _skip_emit_counter[0] += 1
                    if _skip_emit_counter[0] >= 10:
                        _emit({"phase": PHASE_ENUMERATE,
                               "scanned": stats["scanned"], "skipped": stats["skipped"],
                               "path": str(fpath_resolved)})
                        _skip_emit_counter[0] = 0
                    continue

                yield {
                    "fpath": fpath,
                    "fname": fname,
                    "fpath_resolved": fpath_resolved,
                    "dirpath_resolved": dirpath_resolved,
                }

    _run_pool(
        _iter_walk_items(), _process_one, _commit_one,
        workers=workers, file_timeout=file_timeout,
        cancel_event=cancel_event, stats=stats, verbose_print=_vp,
    )

    # Update folder totals
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
    # Status remains "running" until the orchestrator (scan()) flips it to
    # "complete" after the final phase. Standalone enumerate_only callers
    # who want to finalize should set status themselves.
    _log.info("[scan] #%d enumerate done — files=%d, bytes=%d",
              scan_id, final_count, final_bytes)
    return stats


# ====================================================================== #
# Generic enrichment phase runner                                         #
# ====================================================================== #

def _run_enrichment_phase(
    phase: str,
    scan_id: int,
    db_path: str,
    *,
    item_iter_fn,
    work_fn,
    commit_fn,
    cancel_event,
    on_progress,
    workers: int,
    file_timeout: int,
    verbose: bool = False,
) -> dict:
    """Drive a per-phase enrichment pass.

    *item_iter_fn(repo, scan_id)* yields work items (file rows).
    *work_fn(item)* runs in a worker thread; returning None skips silently.
    *commit_fn(repo, item, result)* runs on the main thread.
    """
    ensure_schema(active_url(db_path))
    repo = repo_for(db_path)

    stats: dict = {
        "phase": phase, "scan_id": scan_id,
        "processed": 0, "errors": 0, "skipped": 0, "timed_out": 0,
        "noop": 0, "seen": 0,
    }
    _emit = _emit_factory(on_progress)
    _vp = _make_verbose_printer(verbose, on_progress is not None)

    def _work_wrapper(item: dict):
        fpath = Path(item["path"])
        try:
            if not fpath.exists():
                stats["skipped"] += 1
                return None
        except OSError:
            stats["skipped"] += 1
            return None
        return work_fn(item, fpath)

    def _commit_wrapper(item: dict, result) -> None:
        commit_fn(repo, item, result)
        stats["processed"] += 1
        _emit({"phase": phase, "processed": stats["processed"],
               "path": item["path"]})
        if verbose:
            _vp(f"  [{phase:11s}] {item['path']}")

    def _counting_iter():
        for item in item_iter_fn(repo, scan_id):
            stats["seen"] += 1
            yield item

    _run_pool(
        _counting_iter(), _work_wrapper, _commit_wrapper,
        workers=workers, file_timeout=file_timeout,
        cancel_event=cancel_event, stats=stats, verbose_print=_vp,
    )
    _log.info(
        "[scan] #%d %s done — seen=%d, processed=%d, noop=%d, "
        "errors=%d, skipped=%d, timed_out=%d",
        scan_id, phase, stats["seen"], stats["processed"], stats["noop"],
        stats["errors"], stats["skipped"], stats["timed_out"],
    )
    return stats


# ====================================================================== #
# Phase 2 — enrich_metadata                                              #
# ====================================================================== #

def enrich_metadata(
    scan_id: int,
    db_path: str,
    *,
    cancel_event=None,
    on_progress=None,
    workers: int = 4,
    file_timeout: int = 120,
    verbose: bool = False,
) -> dict:
    def _work(item, fpath: Path):
        extra = _extract_metadata_for_file(
            fpath, item["category"] or "", (item["extension"] or "").lower()
        )
        return json.dumps(extra) if extra else "{}"

    def _commit(repo, item, payload: str):
        repo.update_file_extra_meta(item["id"], payload)

    return _run_enrichment_phase(
        PHASE_METADATA, scan_id, db_path,
        item_iter_fn=lambda repo, sid: repo.iter_files_missing_metadata(sid),
        work_fn=_work, commit_fn=_commit,
        cancel_event=cancel_event, on_progress=on_progress,
        workers=workers, file_timeout=file_timeout, verbose=verbose,
    )


# ====================================================================== #
# Phase 3 — enrich_thumbnails                                            #
# ====================================================================== #

def enrich_thumbnails(
    scan_id: int,
    db_path: str,
    *,
    thumb_size: int = 128,
    thumb_quality: int = 75,
    cancel_event=None,
    on_progress=None,
    workers: int = 4,
    file_timeout: int = 120,
    verbose: bool = False,
) -> dict:
    def _work(item, fpath: Path):
        thumb = _make_thumbnail(fpath, item["category"] or "", thumb_size, thumb_quality)
        return thumb  # None → silently skip (no thumbnail extractable)

    def _commit(repo, item, thumb: bytes):
        repo.save_thumbnail(item["id"], thumb, 0, 0)

    return _run_enrichment_phase(
        PHASE_THUMBNAILS, scan_id, db_path,
        item_iter_fn=lambda repo, sid: repo.iter_files_missing_thumbnail(sid),
        work_fn=_work, commit_fn=_commit,
        cancel_event=cancel_event, on_progress=on_progress,
        workers=workers, file_timeout=file_timeout, verbose=verbose,
    )


# ====================================================================== #
# Phase 4 — enrich_hashes                                                #
# ====================================================================== #

def enrich_hashes(
    scan_id: int,
    db_path: str,
    *,
    cancel_event=None,
    on_progress=None,
    workers: int = 4,
    file_timeout: int = 120,
    verbose: bool = False,
) -> dict:
    def _work(item, fpath: Path):
        return file_sha256(fpath)

    def _commit(repo, item, sha: str):
        if sha:
            repo.update_file_hash(item["id"], sha)

    return _run_enrichment_phase(
        PHASE_HASH, scan_id, db_path,
        item_iter_fn=lambda repo, sid: repo.iter_files_missing_hash(sid),
        work_fn=_work, commit_fn=_commit,
        cancel_event=cancel_event, on_progress=on_progress,
        workers=workers, file_timeout=file_timeout, verbose=verbose,
    )


# ====================================================================== #
# Phase 5 — enrich_samples                                               #
# ====================================================================== #

def enrich_samples(
    scan_id: int,
    db_path: str,
    *,
    sample_duration: int = 5,
    cancel_event=None,
    on_progress=None,
    workers: int = 4,
    file_timeout: int = 120,
    verbose: bool = False,
) -> dict:
    def _work(item, fpath: Path):
        return _make_sample(fpath, item["category"] or "", sample_duration)

    def _commit(repo, item, sample):
        data, fmt = sample
        repo.save_media_sample(item["id"], data, fmt, float(sample_duration))

    return _run_enrichment_phase(
        PHASE_SAMPLES, scan_id, db_path,
        item_iter_fn=lambda repo, sid: repo.iter_files_missing_sample(sid),
        work_fn=_work, commit_fn=_commit,
        cancel_event=cancel_event, on_progress=on_progress,
        workers=workers, file_timeout=file_timeout, verbose=verbose,
    )


# ====================================================================== #
# Orchestrator: scan()                                                    #
# ====================================================================== #

def _resolve_phases(
    phases: "Iterable[str] | None",
    *, compute_hash: bool, store_thumbnails: bool, store_samples: bool,
) -> tuple:
    """Determine the effective phase set.

    If *phases* is given explicitly, it is used as-is (after dedup +
    validation). Otherwise the legacy boolean flags decide which of the
    optional phases run, preserving back-compat for existing callers.
    """
    if phases is None:
        chosen = [PHASE_ENUMERATE, PHASE_METADATA, PHASE_THUMBNAILS, PHASE_HASH, PHASE_SAMPLES]
        if not compute_hash:
            chosen.remove(PHASE_HASH)
        if not store_thumbnails:
            chosen.remove(PHASE_THUMBNAILS)
        if not store_samples:
            chosen.remove(PHASE_SAMPLES)
        return tuple(chosen)

    valid = set(ALL_PHASES)
    seen: set = set()
    out: list = []
    for p in phases:
        p = p.strip().lower()
        if p not in valid:
            raise ValueError(f"unknown phase: {p!r} (valid: {sorted(valid)})")
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    # Preserve canonical ordering regardless of input order
    return tuple(p for p in ALL_PHASES if p in seen)


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
    phases: "Iterable[str] | None" = None,
) -> dict:
    """Phased scan orchestrator.

    Runs the selected *phases* in canonical order
    (enumerate → metadata → thumbnails → hash → samples). With *phases=None*
    (the default), the legacy boolean flags decide which optional phases run,
    which keeps existing callers byte-for-byte compatible.

    When *scan_id* is provided and PHASE_ENUMERATE is not in the selected
    phases, the orchestrator skips the walk and runs enrichments against
    the existing scan.
    """
    effective_phases = _resolve_phases(
        phases,
        compute_hash=compute_hash,
        store_thumbnails=store_thumbnails,
        store_samples=store_samples,
    )

    aggregated: dict = {
        "phases": list(effective_phases),
        "scanned": 0, "errors": 0, "skipped": 0, "timed_out": 0,
        "total_bytes": 0, "resumed": False,
        "per_phase": {},
        "scan_id": scan_id,
    }
    _emit = _emit_factory(on_progress)

    if PHASE_ENUMERATE in effective_phases:
        enum_stats = enumerate_only(
            root, db_path,
            verbose=verbose, label=label,
            skip_hidden_files=skip_hidden_files, skip_hidden_dirs=skip_hidden_dirs,
            skip_system=skip_system, skip_caches=skip_caches, skip_vcs=skip_vcs,
            skip_binaries=skip_binaries, skip_temp=skip_temp, skip_logs=skip_logs,
            cancel_event=cancel_event, scan_id=scan_id, resume=resume,
            on_progress=on_progress, file_timeout=file_timeout, workers=workers,
            exclude_patterns=exclude_patterns,
        )
        aggregated["scan_id"]    = enum_stats["scan_id"]
        aggregated["scanned"]    = enum_stats["scanned"]
        aggregated["skipped"]    = enum_stats["skipped"]
        aggregated["errors"]    += enum_stats["errors"]
        aggregated["timed_out"] += enum_stats["timed_out"]
        aggregated["total_bytes"] = enum_stats["total_bytes"]
        aggregated["resumed"]    = enum_stats["resumed"]
        aggregated["per_phase"][PHASE_ENUMERATE] = enum_stats
        if enum_stats.get("cancelled"):
            aggregated["cancelled"] = True

    if aggregated.get("cancelled"):
        _emit({"done": True, "scan_id": aggregated["scan_id"], "scanned": aggregated["scanned"]})
        return aggregated

    sid = aggregated["scan_id"]
    if sid is None:
        # Enrichment-only call with no scan_id: nothing to do.
        _log.warning("[scan] No scan_id provided and enumerate phase was skipped — nothing to enrich")
        _emit({"done": True, "scan_id": None, "scanned": 0})
        return aggregated

    enrichment_specs = [
        (PHASE_METADATA, enrich_metadata, {}),
        (PHASE_THUMBNAILS, enrich_thumbnails,
            {"thumb_size": thumb_size, "thumb_quality": thumb_quality}),
        (PHASE_HASH, enrich_hashes, {}),
        (PHASE_SAMPLES, enrich_samples,
            {"sample_duration": sample_duration}),
    ]

    for phase_name, fn, extra_kwargs in enrichment_specs:
        if phase_name not in effective_phases:
            continue
        repo = repo_for(db_path)
        repo.set_scan_status(sid, "running")
        pstats = fn(
            sid, db_path,
            cancel_event=cancel_event, on_progress=on_progress,
            workers=workers, file_timeout=file_timeout, verbose=verbose,
            **extra_kwargs,
        )
        aggregated["per_phase"][phase_name] = pstats
        aggregated["errors"]    += pstats["errors"]
        aggregated["timed_out"] += pstats["timed_out"]
        if pstats.get("cancelled"):
            aggregated["cancelled"] = True
            break

    # Finalize scan status
    repo = repo_for(db_path)
    final_status = "resumed" if aggregated.get("resumed") else "complete"
    if aggregated.get("cancelled"):
        # leave as "running" so it can be resumed; matches pre-phased behavior
        pass
    else:
        repo.set_scan_status(sid, final_status)
        _log.info("[scan] #%d finished — phases=%s, status=%s",
                  sid, list(effective_phases), final_status)

    _emit({"done": True, "scan_id": sid, "scanned": aggregated["scanned"]})
    return aggregated
