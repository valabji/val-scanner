from __future__ import annotations
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal
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
                    self._pid, f"Total files to index: {estimated_total:,}"
                )

            def _on_progress(ev: dict) -> None:
                if "path" not in ev:
                    return
                self.progress.emit(ev)
                if self._pid:
                    n = ev.get("scanned", 0)
                    if n % 50 == 0:
                        from .panels.process import ProcessRegistry
                        reg = ProcessRegistry.instance()
                        reg.set_progress_detailed(self._pid, n, estimated_total)
                        reg.push_log(
                            self._pid,
                            f"Indexed {n:,} / {estimated_total:,} — {Path(ev['path']).parent.name}",
                        )

            stats = scan(
                self.root, self.db_path, self.compute_hash,
                label=self.label,
                cancel_event=self._cancel_event,
                on_progress=_on_progress,
                **self.options,
            )
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
        self.db_path   = db_path
        self.scan_id   = scan_id
        self.page_size = page_size

    def run(self) -> None:
        try:
            engine = repo_for(self.db_path).engine
            sid = self.scan_id
            with engine.connect() as conn:
                if sid:
                    total, = conn.execute(
                        text("SELECT COUNT(*) FROM files WHERE scan_id=:sid"), {"sid": sid}
                    ).fetchone()
                    total_size, = conn.execute(
                        text("SELECT SUM(size_bytes) FROM files WHERE scan_id=:sid"), {"sid": sid}
                    ).fetchone()
                    rows = conn.execute(
                        text(
                            "SELECT path, filename, category, size_bytes, size_human, "
                            "modified_at, tags, extra_meta "
                            "FROM files WHERE scan_id=:sid ORDER BY filename LIMIT :lim OFFSET :off"
                        ),
                        {"sid": sid, "lim": self.page_size, "off": 0},
                    ).fetchall()
                else:
                    total, = conn.execute(text("SELECT COUNT(*) FROM files")).fetchone()
                    total_size, = conn.execute(
                        text("SELECT SUM(size_bytes) FROM files")
                    ).fetchone()
                    rows = conn.execute(
                        text(
                            "SELECT path, filename, category, size_bytes, size_human, "
                            "modified_at, tags, extra_meta "
                            "FROM files ORDER BY filename LIMIT :lim OFFSET :off"
                        ),
                        {"lim": self.page_size, "off": 0},
                    ).fetchall()

            self.db_loaded.emit({
                "total":      total,
                "total_size": total_size or 0,
                "rows":       list(rows),
            })
        except Exception as e:
            self.error.emit(str(e))


class LazyLoadWorker(QThread):
    """Background worker for paginated file loading from database."""
    rows_ready = Signal(list)
    error      = Signal(str)

    def __init__(self, db_path: str, scan_id: int | None, offset: int,
                 page_size: int = PAGE_SIZE):
        super().__init__()
        self.db_path   = db_path
        self.scan_id   = scan_id
        self.offset    = offset
        self.page_size = page_size

    def run(self) -> None:
        try:
            engine = repo_for(self.db_path).engine
            with engine.connect() as conn:
                if self.scan_id:
                    rows = conn.execute(
                        text(
                            "SELECT path, filename, category, size_bytes, size_human, "
                            "modified_at, tags, extra_meta "
                            "FROM files WHERE scan_id=:sid ORDER BY filename LIMIT :lim OFFSET :off"
                        ),
                        {"sid": self.scan_id, "lim": self.page_size, "off": self.offset},
                    ).fetchall()
                else:
                    rows = conn.execute(
                        text(
                            "SELECT path, filename, category, size_bytes, size_human, "
                            "modified_at, tags, extra_meta "
                            "FROM files ORDER BY filename LIMIT :lim OFFSET :off"
                        ),
                        {"lim": self.page_size, "off": self.offset},
                    ).fetchall()
            self.rows_ready.emit(list(rows))
        except Exception as e:
            self.error.emit(str(e))


class BrowserLoadWorker(QThread):
    """Loads folders + files at a specific path level (immediate children only)."""
    contents_ready = Signal(dict)  # {"folders": [...], "files": [...], "path": str, "scan_id": int}
    error          = Signal(str)

    def __init__(self, db_path: str, scan_id: int | None, path: str):
        super().__init__()
        self.db_path = db_path
        self.scan_id = scan_id
        self.path    = path

    def run(self) -> None:
        try:
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

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self) -> None:
        try:
            from ..core.bootstrap import ensure_schema
            from ..core.db import repo_for
            # Bring the target DB up to head before any read query — otherwise
            # a fresh PostgreSQL database fails the smoke summary() call with
            # "relation 'files' does not exist".
            ensure_schema(self.url)
            repo    = repo_for(self.url)
            summary = repo.summary()
            self.connected.emit({"url": self.url, "summary": summary})
        except Exception as exc:
            from ..core.app_settings import mask_url
            self.error.emit(mask_url(str(exc)))
