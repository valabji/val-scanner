from __future__ import annotations
import sqlite3
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Request

from valscanner.core.schema import human_size
from ..models import FileRow, FilePage

router = APIRouter(prefix="/api", tags=["files"])

CATEGORIES = {"image", "audio", "video", "document", "archive", "code", "other"}


@router.get("/files", response_model=FilePage)
def get_files(
    request: Request,
    scan_id: int = Query(..., ge=1),
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
) -> FilePage:
    if category and category not in CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_category",
                    "detail": f"category must be one of {sorted(CATEGORIES)}"},
        )

    conn = sqlite3.connect(request.app.state.db_path)
    conn.row_factory = sqlite3.Row
    try:
        where = ["f.scan_id = ?"]
        params: List = [scan_id]

        if category:
            where.append("f.category = ?")
            params.append(category)

        fts_ids: Optional[List[int]] = None
        if search:
            try:
                rows = conn.execute(
                    "SELECT rowid FROM files_fts WHERE files_fts MATCH ? LIMIT 10000",
                    (search,),
                ).fetchall()
                fts_ids = [r["rowid"] for r in rows]
                if not fts_ids:
                    return FilePage(total=0, page=page, page_size=page_size, items=[])
            except sqlite3.OperationalError:
                # FTS missing or malformed query — fall back to LIKE
                where.append("(f.path LIKE ? OR f.tags LIKE ?)")
                like = f"%{search}%"
                params.extend([like, like])

        if fts_ids is not None:
            placeholders = ",".join("?" * len(fts_ids))
            where.append(f"f.id IN ({placeholders})")
            params.extend(fts_ids)

        where_sql = " AND ".join(where)
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM files f WHERE {where_sql}", params
        ).fetchone()["n"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT f.id, f.path, f.filename, f.size_bytes, f.size_human, "
            f"       f.category, f.tags, "
            f"       (SELECT 1 FROM thumbnails t WHERE t.file_id = f.id) AS has_thumb "
            f"FROM files f WHERE {where_sql} ORDER BY f.path "
            f"LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()

        items = [
            FileRow(
                id=r["id"],
                path=r["path"],
                name=r["filename"],
                size=r["size_bytes"] or 0,
                size_human=r["size_human"] or human_size(r["size_bytes"] or 0),
                category=r["category"] or "other",
                tags=[t for t in (r["tags"] or "").split(",") if t],
                has_thumbnail=bool(r["has_thumb"]),
            )
            for r in rows
        ]
        return FilePage(total=total, page=page, page_size=page_size, items=items)
    finally:
        conn.close()
