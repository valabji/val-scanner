from __future__ import annotations

from threading import Lock

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

_engines: dict[str, Engine] = {}
_lock = Lock()


def make_engine(url: str) -> Engine:
    """Create a new, *uncached* engine for the given URL."""
    if url.startswith("sqlite"):
        engine = create_engine(url, echo=False, future=True)
        _configure_sqlite(engine)
    else:
        engine = create_engine(url, echo=False, pool_pre_ping=True, future=True)
    return engine


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA busy_timeout = 5000")
        # ~64 MiB of page cache (negative => KiB) reduces I/O on scans.
        cursor.execute("PRAGMA cache_size = -65536")
        cursor.execute("PRAGMA temp_store = MEMORY")
        # 256 MiB memory-mapped read window — fast random reads on warm pages.
        cursor.execute("PRAGMA mmap_size = 268435456")
        cursor.close()


def get_engine(url: str) -> Engine:
    """Cached engine. Call reset_engines() when settings change."""
    with _lock:
        eng = _engines.get(url)
        if eng is None:
            eng = make_engine(url)
            _engines[url] = eng
        return eng


def reset_engines() -> None:
    """Dispose and forget every cached engine. Call after settings change."""
    with _lock:
        for eng in _engines.values():
            try:
                eng.dispose()
            except Exception:  # noqa: BLE001
                pass
        _engines.clear()


def cached_urls() -> list[str]:
    """Snapshot of currently cached URLs (used by tests / diagnostics)."""
    with _lock:
        return list(_engines.keys())
