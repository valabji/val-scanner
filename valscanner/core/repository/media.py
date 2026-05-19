from __future__ import annotations

from sqlalchemy import select, text

from ..schema import media_samples, thumbnails
from .base import RepositoryBase


class MediaMixin(RepositoryBase):
    def save_thumbnail(self, file_id: int, data: bytes, width: int, height: int) -> None:
        if self.dialect == "sqlite":
            sql = (
                "INSERT INTO thumbnails (file_id, data, width, height) "
                "VALUES (:fid, :data, :w, :h) "
                "ON CONFLICT(file_id) DO UPDATE SET data=excluded.data"
            )
        else:
            sql = (
                "INSERT INTO thumbnails (file_id, data, width, height) "
                "VALUES (:fid, :data, :w, :h) "
                "ON CONFLICT (file_id) DO UPDATE SET data=EXCLUDED.data"
            )
        with self._engine.begin() as conn:
            conn.execute(text(sql), {"fid": file_id, "data": data, "w": width, "h": height})

    def get_thumbnail(self, file_id: int) -> bytes | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(thumbnails.c.data).where(thumbnails.c.file_id == file_id)
            ).fetchone()
        return row[0] if row else None

    def save_media_sample(self, file_id: int, data: bytes, fmt: str, duration: float) -> None:
        if self.dialect == "sqlite":
            sql = (
                "INSERT INTO media_samples (file_id, data, format, duration) "
                "VALUES (:fid, :data, :fmt, :dur) "
                "ON CONFLICT(file_id) DO UPDATE SET data=excluded.data, format=excluded.format, duration=excluded.duration"
            )
        else:
            sql = (
                "INSERT INTO media_samples (file_id, data, format, duration) "
                "VALUES (:fid, :data, :fmt, :dur) "
                "ON CONFLICT (file_id) DO UPDATE SET data=EXCLUDED.data, format=EXCLUDED.format, duration=EXCLUDED.duration"
            )
        with self._engine.begin() as conn:
            conn.execute(text(sql), {"fid": file_id, "data": data, "fmt": fmt, "dur": duration})

    def get_media_sample(self, file_id: int) -> tuple[bytes, str] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(media_samples.c.data, media_samples.c.format)
                .where(media_samples.c.file_id == file_id)
            ).fetchone()
        return (row[0], row[1]) if row else None
