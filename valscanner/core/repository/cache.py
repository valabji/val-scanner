from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError

from ..schema import gui_cache
from .base import RepositoryBase


class CacheMixin(RepositoryBase):
    def db_version(self) -> str:
        """Cheap fingerprint of the scans table; used to validate cache entries."""
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text("SELECT COUNT(*), MAX(id), MAX(indexed_at) FROM scans")
                ).fetchone()
            count, max_id, max_at = row
            return f"{count or 0}:{max_id or 0}:{max_at or ''}"
        except Exception:
            return ""

    def get_gui_cache(self, key: str, version: str) -> dict | None:
        """Return cached payload if the version fingerprint still matches."""
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(gui_cache.c.value_json)
                    .where(gui_cache.c.key == key)
                    .where(gui_cache.c.version == version)
                ).fetchone()
            if row is None:
                return None
            return json.loads(row[0])
        except Exception:
            return None

    def set_gui_cache(self, key: str, version: str, payload: dict) -> None:
        """Write or overwrite a cache entry. Silently no-ops on any error."""
        try:
            value_json = json.dumps(payload)
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if self.dialect == "sqlite":
                sql = (
                    "INSERT INTO gui_cache (key, value_json, version, created_at) "
                    "VALUES (:key, :val, :ver, :at) "
                    "ON CONFLICT(key) DO UPDATE SET "
                    "value_json=excluded.value_json, version=excluded.version, created_at=excluded.created_at"
                )
            else:
                sql = (
                    "INSERT INTO gui_cache (key, value_json, version, created_at) "
                    "VALUES (:key, :val, :ver, :at) "
                    "ON CONFLICT (key) DO UPDATE SET "
                    "value_json=EXCLUDED.value_json, version=EXCLUDED.version, created_at=EXCLUDED.created_at"
                )
            with self._engine.begin() as conn:
                conn.execute(text(sql), {"key": key, "val": value_json, "ver": version, "at": created_at})
        except Exception:
            pass

    def invalidate_gui_cache(self) -> None:
        """Delete all gui_cache rows (called after any scan completes)."""
        try:
            with self._engine.begin() as conn:
                conn.execute(delete(gui_cache))
        except (OperationalError, Exception):
            pass
