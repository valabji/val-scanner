from __future__ import annotations
import csv
import io
import json
import sqlite3
from typing import List, Dict
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api", tags=["export"])


def _rows(db_path: str, scan_id: int) -> List[Dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM files WHERE scan_id = ? ORDER BY path", (scan_id,)
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@router.get("/export/csv")
def export_csv(request: Request, scan_id: int = Query(..., ge=1)) -> StreamingResponse:
    rows = _rows(request.app.state.db_path, scan_id)
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    body = buf.getvalue().encode()
    return StreamingResponse(
        iter([body]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="scan_{scan_id}.csv"'},
    )


@router.get("/export/json")
def export_json(request: Request, scan_id: int = Query(..., ge=1)) -> StreamingResponse:
    rows = _rows(request.app.state.db_path, scan_id)
    body = json.dumps(rows, ensure_ascii=False, indent=2).encode()
    return StreamingResponse(
        iter([body]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="scan_{scan_id}.json"'},
    )
