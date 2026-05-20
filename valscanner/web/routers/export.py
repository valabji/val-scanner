from __future__ import annotations
import csv
import io
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api", tags=["export"])


@router.get("/export/csv")
def export_csv(request: Request, scan_id: int = Query(..., ge=1)) -> StreamingResponse:
    rows = list(request.app.state.repo.iter_files_for_export(scan_id=scan_id))
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
    rows = list(request.app.state.repo.iter_files_for_export(scan_id=scan_id))
    body = json.dumps(rows, ensure_ascii=False, indent=2).encode()
    return StreamingResponse(
        iter([body]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="scan_{scan_id}.json"'},
    )
