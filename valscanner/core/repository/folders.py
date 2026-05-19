from __future__ import annotations

from sqlalchemy import select, text

from ..schema import folders
from .base import RepositoryBase


class FoldersMixin(RepositoryBase):
    def list_folders_for_scan(self, scan_id: int) -> list[dict]:
        stmt = (
            select(folders.c.path, folders.c.file_count, folders.c.total_bytes)
            .where(folders.c.scan_id == scan_id)
            .order_by(folders.c.path)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [
            {"path": r[0], "file_count": r[1] or 0, "total_bytes": r[2] or 0}
            for r in rows
        ]

    def upsert_folder(self, scan_id: int, path: str, file_count: int,
                      total_bytes: int, total_human: str, indexed_at: str) -> None:
        if self.dialect == "sqlite":
            sql = (
                "INSERT INTO folders (scan_id, path, file_count, total_bytes, total_human, indexed_at) "
                "VALUES (:sid, :path, :fc, :tb, :th, :ia) "
                "ON CONFLICT(scan_id, path) DO UPDATE SET "
                "file_count=excluded.file_count, total_bytes=excluded.total_bytes, "
                "total_human=excluded.total_human"
            )
        else:
            sql = (
                "INSERT INTO folders (scan_id, path, file_count, total_bytes, total_human, indexed_at) "
                "VALUES (:sid, :path, :fc, :tb, :th, :ia) "
                "ON CONFLICT (scan_id, path) DO UPDATE SET "
                "file_count=EXCLUDED.file_count, total_bytes=EXCLUDED.total_bytes, "
                "total_human=EXCLUDED.total_human"
            )
        with self._engine.begin() as conn:
            conn.execute(text(sql), {
                "sid": scan_id, "path": path, "fc": file_count,
                "tb": total_bytes, "th": total_human, "ia": indexed_at,
            })
