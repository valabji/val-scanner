"""
GUI worker contract. Every QThread subclass in this module MUST:

  1. Expose ``stop(self) -> None`` that sets an interruption flag and returns
     immediately. The body checks the flag between emits and exits within 250 ms.
  2. Call ``ProcessRegistry.instance().register(...)`` at the START of ``run()``;
     pass ``cancel_cb=self.stop``. Store the returned pid as ``self._pid``.
  3. Call ``ProcessRegistry.instance().mark_done(self._pid)`` or
     ``mark_error(...)`` on EVERY exit path. Wrap the worker body in
     try/finally to guarantee this even on unexpected exceptions.
  4. Emit a heartbeat (any signal or explicit ``heartbeat()``) at least every
     2 s during long phases so the process monitor does not appear frozen.
  5. Emit ``error = Signal(str)`` on failure; do not raise out of ``run()``
     (Qt will print and swallow); do not silently ``except: pass``.

The owning panel MUST surface every error via ``_set_status(..., level='error')``
and, if the error blocks further interaction, also show an inline sticky error state.
"""
from __future__ import annotations
import os
import threading
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QImage
from sqlalchemy import text

from ..core.db import repo_for, save_analysis_run
from ..core.scanner import scan
from ..core.similarity import find_similar_groups

PAGE_SIZE = 2_000


class ScanWorker(QThread):
    progress = Signal(dict)   # {"scanned": int, "path": str} per file
    done     = Signal(dict)   # final stats dict
    error    = Signal(str)

    def __init__(self, root: str, db_path: str, compute_hash: bool,
                 label: str = "", options: dict | None = None):
        super().__init__()
        self.root          = Path(root)
        self.db_path       = db_path
        self.compute_hash  = compute_hash
        self.label         = label
        self.options       = options or {}
        self._stop         = False
        self._cancel_event = threading.Event()
        self._pid          = ""

    def _count_files(self) -> int:
        total = 0
        try:
            for dirpath, dirnames, filenames in os.walk(self.root):
                if self._stop:
                    return total
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                total += len(filenames)
                if self._pid and total % 500 == 0:
                    from .panels.process import ProcessRegistry
                    ProcessRegistry.instance().heartbeat(self._pid)
        except Exception:
            pass
        return total

    def run(self) -> None:
        try:
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().push_log(self._pid, "Counting files…")
            estimated_total = self._count_files()
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().push_log(
                    self._pid, f"Estimated files: {estimated_total:,}"
                )

            last_emit_t = 0.0
            last_emit_n = -50

            def _on_progress(ev: dict) -> None:
                nonlocal last_emit_t, last_emit_n
                if "path" not in ev:
                    return
                n = ev.get("scanned", 0)
                now = time.monotonic()
                if (n - last_emit_n) < 50 and (now - last_emit_t) < 0.1:
                    return
                last_emit_n = n
                last_emit_t = now
                self.progress.emit(ev)
                if self._pid:
                    from .panels.process import ProcessRegistry
                    reg = ProcessRegistry.instance()
                    reg.set_progress_detailed(self._pid, n, estimated_total)
                    reg.push_log(
                        self._pid,
                        f"Scanned {n:,} / {estimated_total:,} — {Path(ev['path']).parent.name}",
                    )

            stats = scan(
                self.root, self.db_path, self.compute_hash,
                label=self.label,
                cancel_event=self._cancel_event,
                on_progress=_on_progress,
                resume=self.options.pop("resume", False),
                **self.options,
            )
            repo = repo_for(self.db_path)
            repo.invalidate_gui_cache()
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().push_log(self._pid, "Warming cache…")
            repo.warm_gui_cache()
            self.done.emit(stats)
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().mark_done(self._pid)
        except Exception as e:
            self.done.emit({"scanned": 0, "errors": 1, "skipped": 0})
            self.error.emit(str(e))
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().mark_error(self._pid, str(e))

    def stop(self) -> None:
        self._stop = True
        self._cancel_event.set()


class AnalysisWorker(QThread):
    finished  = Signal(list)
    error     = Signal(str)
    run_saved = Signal(int)

    def __init__(self, db_path: str, min_files: int, threshold: float,
                 scan_ids: list | None = None, scope_label: str = "",
                 filters: dict | None = None):
        super().__init__()
        self.db_path     = db_path
        self.min_files   = min_files
        self.threshold   = threshold
        self.scan_ids    = scan_ids
        self.scope_label = scope_label
        self.filters     = filters or {}
        self._stop       = False
        self._pid        = ""

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().heartbeat(self._pid)

            if self._stop:
                if self._pid:
                    from .panels.process import ProcessRegistry
                    ProcessRegistry.instance().mark_done(self._pid)
                self.finished.emit([])
                return

            def _progress(i: int, n: int) -> None:
                if self._pid:
                    from .panels.process import ProcessRegistry
                    ProcessRegistry.instance().set_progress_detailed(self._pid, i, n)

            t0 = time.monotonic()
            results = find_similar_groups(
                self.db_path,
                min_files=self.min_files,
                threshold=self.threshold,
                scan_ids=self.scan_ids,
                filters=self.filters,
                stop_flag=lambda: self._stop,
                progress_cb=_progress,
            )
            duration_ms = int((time.monotonic() - t0) * 1000)

            if not self._stop:
                try:
                    run_id = save_analysis_run(
                        self.db_path,
                        min_files=self.min_files,
                        threshold=self.threshold,
                        scope_scan_ids=self.scan_ids,
                        scope_label=self.scope_label,
                        duration_ms=duration_ms,
                        results=results,
                        filters=self.filters,
                    )
                    self.run_saved.emit(run_id)
                except Exception:
                    pass

            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().mark_done(self._pid)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().mark_error(self._pid, str(e))


class DbLoadWorker(QThread):
    """Background worker for initial database load."""
    db_loaded = Signal(dict)  # {"total": N, "total_size": M, "rows": [...]}
    error     = Signal(str)

    def __init__(self, db_path: str, scan_id: int | None, page_size: int = PAGE_SIZE):
        super().__init__()
        self.db_path    = db_path
        self.scan_id    = scan_id
        self.page_size  = page_size
        self._interrupt = threading.Event()
        self._pid: str  = ""

    def stop(self) -> None:
        self._interrupt.set()

    def run(self) -> None:
        from .panels.process import ProcessRegistry
        reg = ProcessRegistry.instance()
        self._pid = reg.register(name="Loading database", cancel_cb=self.stop)
        ok = False
        try:
            repo = repo_for(self.db_path)
            sid  = self.scan_id

            # Only cache the unfiltered initial load (scan_id None/0, offset 0)
            cache_key = f"file_list:{'all' if not sid else f'scan_{sid}'}"
            version   = repo.db_version()
            if version:
                cached = repo.get_gui_cache(cache_key, version)
                if cached is not None:
                    self.db_loaded.emit(cached)
                    ok = True
                    return

            if self._interrupt.is_set():
                return

            engine = repo.engine
            with engine.connect() as conn:
                if self._interrupt.is_set():
                    return
                if sid:
                    total, = conn.execute(
                        text("SELECT COUNT(*) FROM files WHERE scan_id=:sid"), {"sid": sid}
                    ).fetchone()
                    total_size, = conn.execute(
                        text("SELECT SUM(size_bytes) FROM files WHERE scan_id=:sid"), {"sid": sid}
                    ).fetchone()
                    if self._interrupt.is_set():
                        return
                    rows = conn.execute(
                        text(
                            "SELECT path, filename, category, size_bytes, size_human, "
                            "modified_at, tags, sha256, extra_meta "
                            "FROM files WHERE scan_id=:sid ORDER BY filename LIMIT :lim OFFSET :off"
                        ),
                        {"sid": sid, "lim": self.page_size, "off": 0},
                    ).fetchall()
                else:
                    total, = conn.execute(text("SELECT COUNT(*) FROM files")).fetchone()
                    total_size, = conn.execute(
                        text("SELECT SUM(size_bytes) FROM files")
                    ).fetchone()
                    if self._interrupt.is_set():
                        return
                    rows = conn.execute(
                        text(
                            "SELECT path, filename, category, size_bytes, size_human, "
                            "modified_at, tags, sha256, extra_meta "
                            "FROM files ORDER BY filename LIMIT :lim OFFSET :off"
                        ),
                        {"lim": self.page_size, "off": 0},
                    ).fetchall()

            payload = {
                "total":      total,
                "total_size": total_size or 0,
                "rows":       [list(r) for r in rows],
            }
            if version:
                repo.set_gui_cache(cache_key, version, payload)
            self.db_loaded.emit(payload)
            ok = True
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self._interrupt.is_set():
                reg.mark_done(self._pid)
            elif ok:
                reg.mark_done(self._pid)
            else:
                reg.mark_error(self._pid)


class LazyLoadWorker(QThread):
    """Background worker for paginated file loading from database."""
    rows_ready = Signal(list)
    error      = Signal(str)

    def __init__(self, db_path: str, scan_id: int | None, offset: int,
                 page_size: int = PAGE_SIZE):
        super().__init__()
        self.db_path    = db_path
        self.scan_id    = scan_id
        self.offset     = offset
        self.page_size  = page_size
        self._interrupt = threading.Event()
        self._pid: str  = ""

    def stop(self) -> None:
        self._interrupt.set()

    def run(self) -> None:
        from .panels.process import ProcessRegistry
        reg = ProcessRegistry.instance()
        self._pid = reg.register(name="Loading more files", cancel_cb=self.stop)
        ok = False
        try:
            if self._interrupt.is_set():
                return
            engine = repo_for(self.db_path).engine
            with engine.connect() as conn:
                if self.scan_id:
                    rows = conn.execute(
                        text(
                            "SELECT path, filename, category, size_bytes, size_human, "
                            "modified_at, tags, sha256, extra_meta "
                            "FROM files WHERE scan_id=:sid ORDER BY filename LIMIT :lim OFFSET :off"
                        ),
                        {"sid": self.scan_id, "lim": self.page_size, "off": self.offset},
                    ).fetchall()
                else:
                    rows = conn.execute(
                        text(
                            "SELECT path, filename, category, size_bytes, size_human, "
                            "modified_at, tags, sha256, extra_meta "
                            "FROM files ORDER BY filename LIMIT :lim OFFSET :off"
                        ),
                        {"lim": self.page_size, "off": self.offset},
                    ).fetchall()
            self.rows_ready.emit(list(rows))
            ok = True
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if ok or self._interrupt.is_set():
                reg.mark_done(self._pid)
            else:
                reg.mark_error(self._pid)


class BrowserLoadWorker(QThread):
    """Loads folders + files at a specific path level (immediate children only)."""
    contents_ready = Signal(dict)  # {"folders": [...], "files": [...], "path": str, "scan_id": int}
    error          = Signal(str)

    def __init__(self, db_path: str, scan_id: int | None, path: str, recursive: bool = False):
        super().__init__()
        self.db_path    = db_path
        self.scan_id    = scan_id
        self.path       = path
        self.recursive  = recursive
        self._interrupt = threading.Event()
        self._pid: str  = ""

    def stop(self) -> None:
        self._interrupt.set()

    def run(self) -> None:
        from .panels.process import ProcessRegistry
        reg = ProcessRegistry.instance()
        label = Path(self.path).name if self.path else "root"
        self._pid = reg.register(name=f"Loading: {label}", cancel_cb=self.stop)
        ok = False
        try:
            if self._interrupt.is_set():
                return
            engine = repo_for(self.db_path).engine
            sid = self.scan_id
            with engine.connect() as conn:
                if not self.path:
                    if sid:
                        rows = conn.execute(
                            text("SELECT id, root, label, file_count, total_bytes "
                                 "FROM scans WHERE id=:sid"),
                            {"sid": sid},
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            text("SELECT id, root, label, file_count, total_bytes FROM scans")
                        ).fetchall()
                    folders = [
                        (r[1], r[3] or 0, r[4] or 0, r[0])
                        for r in rows
                    ]
                    files = []
                else:
                    like_prefix = self.path.rstrip("/") + "/%"
                    if self.recursive:
                        # All files under this path (flat, no folder rows)
                        if sid:
                            folder_rows = []
                            file_rows = conn.execute(
                                text(
                                    "SELECT path, filename, category, size_bytes, size_human, "
                                    "modified_at, tags, extra_meta "
                                    "FROM files WHERE scan_id=:sid AND path LIKE :pre ORDER BY filename"
                                ),
                                {"sid": sid, "pre": like_prefix},
                            ).fetchall()
                        else:
                            folder_rows = []
                            file_rows = conn.execute(
                                text(
                                    "SELECT path, filename, category, size_bytes, size_human, "
                                    "modified_at, tags, extra_meta "
                                    "FROM files WHERE path LIKE :pre ORDER BY filename"
                                ),
                                {"pre": like_prefix},
                            ).fetchall()
                    else:
                        like_deeper = self.path.rstrip("/") + "/%/%"
                        if sid:
                            folder_rows = conn.execute(
                                text(
                                    "SELECT path, file_count, total_bytes, scan_id FROM folders "
                                    "WHERE scan_id=:sid AND path LIKE :pre AND path NOT LIKE :deep "
                                    "ORDER BY path"
                                ),
                                {"sid": sid, "pre": like_prefix, "deep": like_deeper},
                            ).fetchall()
                            file_rows = conn.execute(
                                text(
                                    "SELECT path, filename, category, size_bytes, size_human, "
                                    "modified_at, tags, extra_meta "
                                    "FROM files WHERE scan_id=:sid AND path LIKE :pre AND path NOT LIKE :deep "
                                    "ORDER BY filename"
                                ),
                                {"sid": sid, "pre": like_prefix, "deep": like_deeper},
                            ).fetchall()
                        else:
                            folder_rows = conn.execute(
                                text(
                                    "SELECT path, file_count, total_bytes, scan_id FROM folders "
                                    "WHERE path LIKE :pre AND path NOT LIKE :deep ORDER BY path"
                                ),
                                {"pre": like_prefix, "deep": like_deeper},
                            ).fetchall()
                            file_rows = conn.execute(
                                text(
                                    "SELECT path, filename, category, size_bytes, size_human, "
                                    "modified_at, tags, extra_meta "
                                    "FROM files WHERE path LIKE :pre AND path NOT LIKE :deep "
                                    "ORDER BY filename"
                                ),
                                {"pre": like_prefix, "deep": like_deeper},
                            ).fetchall()
                    folders = list(folder_rows)
                    files   = list(file_rows)

            self.contents_ready.emit({
                "folders":  folders,
                "files":    files,
                "path":     self.path,
                "scan_id":  sid or 0,
            })
            ok = True
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if ok or self._interrupt.is_set():
                reg.mark_done(self._pid)
            else:
                reg.mark_error(self._pid)


class FolderLoadWorker(QThread):
    """Queries folder data from DB in background for FolderPanel.

    Emits ``data_ready`` with a dict:
      - mode "combined": {"mode": "combined", "rows": [(path, bytes, count), ...]}
      - mode "separate": {"mode": "separate",
                          "scans": [(id, label, total_bytes, file_count), ...],
                          "scan_data": {scan_id: {path: (bytes, count)}}}
    """
    data_ready = Signal(dict)
    error      = Signal(str)

    def __init__(self, db_path: str, scan_id: int, separate_scans: bool):
        super().__init__()
        self.db_path        = db_path
        self.scan_id        = scan_id
        self.separate_scans = separate_scans
        self._interrupt     = threading.Event()
        self._pid: str      = ""

    def stop(self) -> None:
        self._interrupt.set()

    def run(self) -> None:
        from .panels.process import ProcessRegistry
        reg = ProcessRegistry.instance()
        self._pid = reg.register(name="Loading folders", cancel_cb=self.stop)
        ok = False
        try:
            repo = repo_for(self.db_path)

            # Determine cache key and try the cache first
            if self.separate_scans and self.scan_id == 0:
                cache_key = "folder_tree:separate"
            elif self.scan_id:
                cache_key = f"folder_tree:scan_{self.scan_id}"
            else:
                cache_key = "folder_tree:all"

            version = repo.db_version()
            if version:
                cached = repo.get_gui_cache(cache_key, version)
                if cached is not None:
                    # JSON stores int dict keys as strings; restore them
                    if cached.get("mode") == "separate" and "scan_data" in cached:
                        cached["scan_data"] = {int(k): v for k, v in cached["scan_data"].items()}
                    self.data_ready.emit(cached)
                    ok = True
                    return

            if self._interrupt.is_set():
                return

            engine = repo.engine

            if self.separate_scans and self.scan_id == 0:
                with engine.connect() as conn:
                    scans = conn.execute(
                        text("SELECT id, label, total_bytes, file_count FROM scans ORDER BY label")
                    ).fetchall()
                    if self._interrupt.is_set():
                        return
                    # single query instead of one per scan
                    all_rows = conn.execute(
                        text(
                            "SELECT scan_id, path, SUM(total_bytes), SUM(file_count) "
                            "FROM folders GROUP BY scan_id, path ORDER BY path"
                        )
                    ).fetchall()
                    cat_rows = conn.execute(
                        text(
                            "SELECT category, SUM(size_bytes) FROM files "
                            "GROUP BY category ORDER BY SUM(size_bytes) DESC"
                        )
                    ).fetchall()

                scan_data: dict[int, dict] = {}
                for r in all_rows:
                    scan_data.setdefault(r[0], {})[r[1]] = (r[2], r[3])

                payload: dict = {
                    "mode":             "separate",
                    "scans":            [list(r) for r in scans],
                    "scan_data":        scan_data,
                    "category_bytes":   {r[0]: r[1] for r in cat_rows if r[0]},
                }
            else:
                with engine.connect() as conn:
                    if self.scan_id:
                        rows = conn.execute(
                            text(
                                "SELECT path, SUM(total_bytes), SUM(file_count) "
                                "FROM folders WHERE scan_id=:sid GROUP BY path ORDER BY path"
                            ),
                            {"sid": self.scan_id},
                        ).fetchall()
                        cat_rows = conn.execute(
                            text(
                                "SELECT category, SUM(size_bytes) FROM files "
                                "WHERE scan_id=:sid GROUP BY category ORDER BY SUM(size_bytes) DESC"
                            ),
                            {"sid": self.scan_id},
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            text(
                                "SELECT path, SUM(total_bytes), SUM(file_count) "
                                "FROM folders GROUP BY path ORDER BY path"
                            )
                        ).fetchall()
                        cat_rows = conn.execute(
                            text(
                                "SELECT category, SUM(size_bytes) FROM files "
                                "GROUP BY category ORDER BY SUM(size_bytes) DESC"
                            )
                        ).fetchall()

                payload = {
                    "mode":           "combined",
                    "rows":           [list(r) for r in rows],
                    "category_bytes": {r[0]: r[1] for r in cat_rows if r[0]},
                }

            if version:
                repo.set_gui_cache(cache_key, version, payload)
            self.data_ready.emit(payload)
            ok = True
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if ok or self._interrupt.is_set():
                reg.mark_done(self._pid)
            else:
                reg.mark_error(self._pid)


class ThumbnailLoadWorker(QThread):
    """Long-lived queue-driven worker that fetches thumbnail blobs from SQLite.

    Producers call ``enqueue(path, size)`` from the GUI thread; this worker
    pops requests, runs the JOIN, and emits ``thumb_ready(path, QImage, size)``
    on the GUI thread (QImage is thread-safe; the GUI converts to QPixmap).

    Requests for paths already loaded (or known to have no blob) are skipped
    by the cache before they reach the queue.
    """
    thumb_ready = Signal(str, QImage, int)  # path, image (may be null), size
    error       = Signal(str)

    def __init__(self, db_path: str):
        super().__init__()
        self._db_path = db_path
        self._queue: deque[tuple[str, int]] = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop_flag = False

    def set_db(self, db_path: str) -> None:
        """Swap DB; drops any pending requests for the old DB."""
        with self._lock:
            self._db_path = db_path
            self._queue.clear()

    def enqueue(self, path: str, size: int) -> None:
        with self._lock:
            self._queue.append((path, size))
        self._wake.set()

    def stop(self) -> None:
        self._stop_flag = True
        self._wake.set()
        self.wait(500)

    def run(self) -> None:
        while not self._stop_flag:
            self._wake.wait(timeout=1.0)
            if self._stop_flag:
                return
            self._wake.clear()
            while not self._stop_flag:
                with self._lock:
                    if not self._queue:
                        break
                    path, size = self._queue.popleft()
                    db_path = self._db_path
                if not db_path:
                    continue
                try:
                    engine = repo_for(db_path).engine
                    with engine.connect() as conn:
                        row = conn.execute(
                            text("SELECT t.data FROM thumbnails t"
                                 " JOIN files f ON f.id = t.file_id WHERE f.path=:p"),
                            {"p": path},
                        ).fetchone()
                    img = QImage()
                    if row and row[0]:
                        img.loadFromData(bytes(row[0]))
                    self.thumb_ready.emit(path, img, size)
                except Exception as e:
                    # Emit empty image on error so the cache can mark as resolved
                    self.thumb_ready.emit(path, QImage(), size)
                    self.error.emit(str(e))


class DetailLoadWorker(QThread):
    """One-shot worker: fetches the file's thumbnail blob and sample existence
    in a single DB connection. Cancellation is implicit via supersession in
    the GUI (the panel discards results whose ``path`` no longer matches).
    """
    loaded = Signal(str, QImage, bool)  # path, image (may be null), has_sample
    error  = Signal(str)

    def __init__(self, db_path: str, path: str, want_thumb: bool, want_sample: bool):
        super().__init__()
        self._db_path = db_path
        self._path = path
        self._want_thumb = want_thumb
        self._want_sample = want_sample
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        img = QImage()
        has_sample = False
        try:
            if not self._db_path:
                self.loaded.emit(self._path, img, has_sample)
                return
            engine = repo_for(self._db_path).engine
            with engine.connect() as conn:
                if self._stop:
                    return
                if self._want_thumb:
                    row = conn.execute(
                        text("SELECT t.data FROM thumbnails t"
                             " JOIN files f ON f.id = t.file_id WHERE f.path=:p"),
                        {"p": self._path},
                    ).fetchone()
                    if row and row[0]:
                        img.loadFromData(bytes(row[0]))
                if self._stop:
                    return
                if self._want_sample:
                    has = conn.execute(
                        text("SELECT 1 FROM media_samples ms"
                             " JOIN files f ON f.id = ms.file_id WHERE f.path=:p"),
                        {"p": self._path},
                    ).fetchone()
                    has_sample = bool(has)
            if not self._stop:
                self.loaded.emit(self._path, img, has_sample)
        except Exception as e:
            self.error.emit(str(e))
            if not self._stop:
                self.loaded.emit(self._path, img, has_sample)


# Filter constants (re-exported for the worker)
from ..core.scanner import _SYSTEM_DIRS, _CACHE_DIRS, _VCS_DIRS, _BINARY_EXTS, _TEMP_EXTS, _LOG_EXTS  # noqa: E402


class FilterWorker(QThread):
    """Runs the (search + category + view-filter) sweep over ``rows`` off the
    GUI thread. Emits ``done(generation, filtered_rows, parts_cache_updates)``.

    The generation counter lets the caller drop stale results when the user
    types/toggles filters rapidly.
    """
    done  = Signal(int, list, dict)
    error = Signal(str)

    _FOLDER_SENTINEL = "__folder__"

    def __init__(
        self,
        generation: int,
        rows: list,
        term: str,
        cat: str,
        view_filters: dict,
        parts_cache: dict,
    ):
        super().__init__()
        self._gen = generation
        self._rows = rows
        self._term = term
        self._cat = cat
        self._vf = view_filters or {}
        self._parts_cache = parts_cache
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            term = self._term
            cat = self._cat
            FOLDER = self._FOLDER_SENTINEL

            filtered: list = []
            for r in self._rows:
                if self._stop:
                    return
                # Folder rows: only search-term filter
                if len(r) > 2 and r[2] == FOLDER:
                    if term and term not in f"{r[1]} {r[0]}".lower():
                        continue
                    filtered.append(r)
                    continue
                if cat and r[2] != cat:
                    continue
                if term and term not in f"{r[1]} {r[2]} {r[6]} {r[7] if len(r) > 7 else ''} {r[0]}".lower():
                    continue
                filtered.append(r)

            vf = self._vf
            new_parts: dict = {}
            if vf:
                hidden_cats       = vf.get("hidden_categories", set())
                min_bytes         = vf.get("min_bytes", 0)
                max_bytes         = vf.get("max_bytes", 0)
                exts              = vf.get("extensions", set())
                hide_hidden_dirs  = vf.get("hide_hidden_dirs",  False)
                hide_vcs          = vf.get("hide_vcs",          False)
                hide_system       = vf.get("hide_system",       False)
                hide_caches       = vf.get("hide_caches",       False)
                hide_hidden_files = vf.get("hide_hidden_files", False)
                hide_binaries     = vf.get("hide_binaries",     False)
                hide_temp         = vf.get("hide_temp",         False)
                hide_logs         = vf.get("hide_logs",         False)

                any_path_filter = (hide_hidden_dirs or hide_vcs or hide_system or hide_caches)
                any_active = (hidden_cats or min_bytes or max_bytes or exts
                              or any_path_filter
                              or hide_hidden_files or hide_binaries or hide_temp or hide_logs)

                if any_active:
                    out: list = []
                    cache = self._parts_cache
                    for r in filtered:
                        if self._stop:
                            return
                        path, filename, _cat, size_b = r[0], r[1], r[2], r[3]
                        ext = Path(filename).suffix.lower()

                        if _cat in hidden_cats:
                            continue
                        if min_bytes and size_b < min_bytes:
                            continue
                        if max_bytes and size_b > max_bytes:
                            continue
                        if exts and ext.lstrip(".") not in exts:
                            continue
                        if hide_hidden_files and filename.startswith("."):
                            continue
                        if hide_binaries and ext in _BINARY_EXTS:
                            continue
                        if hide_temp and ext in _TEMP_EXTS:
                            continue
                        if hide_logs and ext in _LOG_EXTS:
                            continue

                        if any_path_filter:
                            parts = cache.get(path)
                            if parts is None:
                                parts = frozenset(Path(path).parts)
                                new_parts[path] = parts
                            if hide_hidden_dirs and any(p.startswith(".") for p in parts):
                                continue
                            if hide_vcs and (parts & _VCS_DIRS):
                                continue
                            if hide_system and (parts & _SYSTEM_DIRS):
                                continue
                            if hide_caches and (parts & _CACHE_DIRS):
                                continue

                        out.append(r)
                    filtered = out

            if self._stop:
                return
            self.done.emit(self._gen, filtered, new_parts)
        except Exception as e:
            self.error.emit(str(e))


class ConnectWorker(QThread):
    """Non-blocking database connect + initial summary load.

    Signals
    -------
    connected : emitted with {"url": str, "summary": dict} on success
    error     : emitted with a masked error message string on failure
    """
    connected = Signal(dict)
    error     = Signal(str)

    def __init__(self, url: str, timeout_sec: float = 10.0):
        super().__init__()
        self.url         = url
        self._timeout    = timeout_sec
        self._interrupt  = threading.Event()
        self._pid: str   = ""

    def stop(self) -> None:
        self._interrupt.set()

    def run(self) -> None:
        from .panels.process import ProcessRegistry
        reg = ProcessRegistry.instance()
        self._pid = reg.register(name="Connecting to database", cancel_cb=self.stop)
        ok = False
        try:
            from ..core.bootstrap import ensure_schema
            from ..core.db import repo_for

            done: threading.Event = threading.Event()
            result: dict = {}

            def _go() -> None:
                try:
                    # Bring DB up to head before any read query — a fresh
                    # PostgreSQL DB fails summary() with "relation 'files' does not exist".
                    ensure_schema(self.url)
                    repo = repo_for(self.url)
                    result["summary"] = repo.summary()
                except Exception as exc:
                    result["error"] = exc
                finally:
                    done.set()

            t = threading.Thread(target=_go, daemon=True)
            t.start()
            # If the engine thread does not return (e.g. wrong host), the
            # thread leaks but the GUI is freed — acceptable trade-off.
            if not done.wait(self._timeout) or self._interrupt.is_set():
                if not self._interrupt.is_set():
                    self.error.emit(
                        f"Connection timed out after {self._timeout:.0f} s. "
                        "Check host and credentials."
                    )
                return

            if "error" in result:
                from ..core.app_settings import mask_url
                self.error.emit(mask_url(str(result["error"])))
                return

            self.connected.emit({"url": self.url, "summary": result["summary"]})
            ok = True
        except Exception as exc:
            from ..core.app_settings import mask_url
            self.error.emit(mask_url(str(exc)))
        finally:
            if ok or self._interrupt.is_set():
                reg.mark_done(self._pid)
            else:
                reg.mark_error(self._pid)
