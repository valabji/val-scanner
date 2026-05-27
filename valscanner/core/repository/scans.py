from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import PurePath, PurePosixPath, PureWindowsPath

from sqlalchemy import delete, insert, select, update
from sqlalchemy.sql import bindparam

from ..schema import files as files_t, folders as folders_t, scans
from .base import RepositoryBase

_log = logging.getLogger(__name__)


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
            result = row[0] if row else None
            _log.info("[find_interrupted_scan] root=%r → scan_id=%s", root, result)
            return result
        except Exception as exc:
            _log.warning("[find_interrupted_scan] query failed (status column absent?): %s", exc)
            return None

    def delete_scan(self, scan_id: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(scans).where(scans.c.id == scan_id))

    def remap_scan_root(self, scan_id: int, new_root: str) -> dict:
        """
        Rewrite scans.root and every files.path / folders.path under one scan
        so they point at a drive's new mount location. Handles cross-OS moves
        (e.g. Windows ``D:\\Photos`` → macOS ``/Volumes/Photos``) by detecting
        each side's path flavor and rebuilding paths from the flavor-agnostic
        ``.parts`` tuple.

        Returns a summary dict::

            {old_root, new_root, files_updated, folders_updated,
             files_skipped: [path, ...], folders_skipped: [path, ...]}
        """
        current = self.get_scan(scan_id)
        if current is None:
            raise ValueError(f"no scan with id={scan_id}")
        old_root_raw = current["root"]

        old_pure = _pure_from_str(old_root_raw)
        new_pure = _pure_from_str(new_root)

        if _normalized(old_pure) == _normalized(new_pure):
            return {
                "old_root": old_root_raw, "new_root": str(new_pure),
                "files_updated": 0, "folders_updated": 0,
                "files_skipped": [], "folders_skipped": [],
            }

        with self._engine.begin() as conn:
            files_updated, files_skipped = _rewrite_paths(
                conn, files_t, scan_id, old_pure, new_pure,
            )
            folders_updated, folders_skipped = _rewrite_paths(
                conn, folders_t, scan_id, old_pure, new_pure,
            )
            conn.execute(
                update(scans).where(scans.c.id == scan_id).values(root=str(new_pure))
            )

        _log.info(
            "[remap_scan_root] scan_id=%d  %r → %r  files=%d folders=%d "
            "skipped_files=%d skipped_folders=%d",
            scan_id, old_root_raw, str(new_pure),
            files_updated, folders_updated,
            len(files_skipped), len(folders_skipped),
        )
        return {
            "old_root": old_root_raw, "new_root": str(new_pure),
            "files_updated": files_updated, "folders_updated": folders_updated,
            "files_skipped": files_skipped, "folders_skipped": folders_skipped,
        }


_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _pure_from_str(p: str) -> PurePath:
    """Pick PureWindowsPath or PurePosixPath based on the string's shape."""
    s = (p or "").rstrip("\\/")
    if _WIN_DRIVE_RE.match(s) or ("\\" in s and "/" not in s):
        return PureWindowsPath(s)
    return PurePosixPath(s)


def _normalized(p: PurePath) -> str:
    """Comparison key — case-insensitive for Windows paths."""
    s = str(p)
    return s.lower() if isinstance(p, PureWindowsPath) else s


def _is_under(child: PurePath, root: PurePath) -> bool:
    """Flavor-aware prefix check (case-insensitive on Windows)."""
    try:
        child.relative_to(root)
        return True
    except ValueError:
        # PureWindowsPath.relative_to is already case-insensitive on `parts`,
        # but be defensive: compare normalized prefixes manually.
        cs = _normalized(child)
        rs = _normalized(root)
        sep = "\\" if isinstance(root, PureWindowsPath) else "/"
        return cs == rs or cs.startswith(rs + sep)


def _translate(path_str: str, old_root: PurePath, new_root: PurePath) -> str | None:
    """
    Translate one absolute path from old_root's flavor to new_root's flavor.
    Returns the new path string, or None if path_str is not under old_root.
    """
    pure = _pure_from_str(path_str)
    if not _is_under(pure, old_root):
        return None
    # Strip the root prefix manually so we can preserve cross-flavor parts.
    old_parts = old_root.parts
    child_parts = pure.parts
    if isinstance(old_root, PureWindowsPath):
        # Case-insensitive match on the prefix.
        if [p.lower() for p in child_parts[:len(old_parts)]] != \
           [p.lower() for p in old_parts]:
            return None
    else:
        if child_parts[:len(old_parts)] != old_parts:
            return None
    rel = child_parts[len(old_parts):]
    rebuilt = new_root.joinpath(*rel) if rel else new_root
    return str(rebuilt)


def _rewrite_paths(conn, table, scan_id: int,
                   old_root: PurePath, new_root: PurePath,
                   batch_size: int = 1000) -> tuple[int, list[str]]:
    """Read all paths for the scan, translate, batch-UPDATE by id."""
    sel = select(table.c.id, table.c.path).where(table.c.scan_id == scan_id)
    rows = conn.execute(sel).fetchall()

    updates: list[dict] = []
    skipped: list[str] = []
    for row_id, path in rows:
        new_path = _translate(path, old_root, new_root)
        if new_path is None:
            skipped.append(path)
            continue
        if new_path == path:
            continue
        updates.append({"row_id": row_id, "new_path": new_path})

    if updates:
        stmt = (
            update(table)
            .where(table.c.id == bindparam("row_id"))
            .values(path=bindparam("new_path"))
        )
        for i in range(0, len(updates), batch_size):
            conn.execute(stmt, updates[i:i + batch_size])

    return len(updates), skipped
