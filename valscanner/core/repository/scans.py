from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, insert, select, update

from ..schema import scans
from .base import RepositoryBase


class ScansMixin(RepositoryBase):
    def list_scans(self) -> list[dict]:
        from sqlalchemy.exc import OperationalError
        try:
            with self._engine.connect() as conn:
                stmt = select(
                    scans.c.id, scans.c.label, scans.c.root, scans.c.scanned_at,
                    scans.c.file_count, scans.c.total_bytes, scans.c.total_human,
                    scans.c.status,
                ).order_by(scans.c.id)
                return [dict(r._mapping) for r in conn.execute(stmt)]
        except OperationalError:
            pass
        # status column absent on pre-migration DB — retry without it
        try:
            with self._engine.connect() as conn:
                stmt = select(
                    scans.c.id, scans.c.label, scans.c.root, scans.c.scanned_at,
                    scans.c.file_count, scans.c.total_bytes, scans.c.total_human,
                ).order_by(scans.c.id)
                rows = [dict(r._mapping) for r in conn.execute(stmt)]
                for r in rows:
                    r["status"] = None
                return rows
        except OperationalError:
            return []

    def get_scan(self, scan_id: int) -> dict | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(scans).where(scans.c.id == scan_id)).fetchone()
        return dict(row._mapping) if row else None

    def create_scan(self, root: str, label: str = "",
                    scanned_at: str | None = None) -> int:
        now = scanned_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._engine.begin() as conn:
            result = conn.execute(
                insert(scans).values(label=label, root=root, scanned_at=now)
            )
        return result.inserted_primary_key[0]

    def update_scan_totals(self, scan_id: int, file_count: int,
                           total_bytes: int, total_human: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(scans).where(scans.c.id == scan_id).values(
                    file_count=file_count,
                    total_bytes=total_bytes,
                    total_human=total_human,
                )
            )

    def update_scan_label(self, scan_id: int, label: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(update(scans).where(scans.c.id == scan_id).values(label=label))

    def set_scan_status(self, scan_id: int, status: str) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(update(scans).where(scans.c.id == scan_id).values(status=status))
        except Exception:
            pass  # column absent on old DBs not yet migrated

    def find_interrupted_scan(self, root: str) -> int | None:
        """Return the most recent scan_id for root that never completed, or None."""
        stmt = (
            select(scans.c.id)
            .where((scans.c.root == root) & (scans.c.status == "running"))
            .order_by(scans.c.id.desc())
            .limit(1)
        )
        try:
            with self._engine.connect() as conn:
                row = conn.execute(stmt).fetchone()
            return row[0] if row else None
        except Exception:
            return None  # status column absent on old DB

    def delete_scan(self, scan_id: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(scans).where(scans.c.id == scan_id))
