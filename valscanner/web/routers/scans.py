from __future__ import annotations
import json
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from valscanner.core.scanner import scan as run_scan

from ..models import ScanRow, ScanRequest, ScanStartResponse
from ..scan_registry import REGISTRY, ScanState

router = APIRouter(prefix="/api", tags=["scans"])


@router.get("/scans", response_model=List[ScanRow])
def get_scans(request: Request) -> List[ScanRow]:
    rows = request.app.state.repo.list_scans()
    return [ScanRow(**r) for r in rows]


@router.post("/scan", response_model=ScanStartResponse, status_code=202)
def start_scan(req: ScanRequest, request: Request) -> ScanStartResponse:
    root = Path(req.root).expanduser()
    if not root.exists() or not root.is_dir():
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_root", "detail": f"{root} is not a directory"},
        )

    active = REGISTRY.active_id()
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail={"error": "scan_in_progress", "detail": f"scan {active} is already running"},
        )

    repo   = request.app.state.repo
    db_url = request.app.state.db_url

    label   = req.label.strip() or root.name
    scan_id = repo.create_scan(
        root=str(root),
        label=label,
        scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    state = REGISTRY.start(scan_id)

    def worker() -> None:
        try:
            stats = run_scan(
                root=root,
                db_path=db_url,
                compute_hash=not req.no_hash,
                label=label,
                cancel_event=state.cancel_event,
                scan_id=scan_id,
                on_progress=state.push,
            )
            if stats.get("cancelled"):
                state.push({"cancelled": True, "scan_id": scan_id})
            else:
                state.push({"done": True, "scan_id": scan_id,
                            "scanned": stats.get("scanned", 0)})
        except Exception as exc:  # noqa: BLE001
            state.push({"error": "scan_failed", "detail": str(exc)})
        finally:
            REGISTRY.finish(scan_id)

    t = threading.Thread(target=worker, daemon=True)
    state.thread = t
    t.start()

    return ScanStartResponse(scan_id=scan_id)


@router.get("/scan/{scan_id}/stream")
def stream_scan(scan_id: int, request: Request) -> StreamingResponse:
    state = REGISTRY.get(scan_id)
    if state is None:
        raise HTTPException(status_code=404, detail={"error": "not_found",
                                                     "detail": f"no scan {scan_id}"})
    last_event_id = request.headers.get("last-event-id")
    start_index = int(last_event_id) + 1 if last_event_id and last_event_id.isdigit() else 0
    q: queue.Queue = queue.Queue(maxsize=1000)
    state.listeners.append(q)

    def gen():
        idx = start_index
        for ev in state.events[max(0, start_index - max(0, len(state.events) - state.BUFFER)):]:
            yield f"id: {idx}\ndata: {json.dumps(ev)}\n\n".encode()
            idx += 1
        while True:
            try:
                ev = q.get(timeout=15)
            except queue.Empty:
                yield b": keepalive\n\n"
                continue
            yield f"id: {idx}\ndata: {json.dumps(ev)}\n\n".encode()
            idx += 1
            if ev.get("done") or ev.get("cancelled") or ev.get("error"):
                return

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/scan/{scan_id}/cancel", status_code=204)
def cancel_scan(scan_id: int) -> Response:
    state = REGISTRY.get(scan_id)
    if state is None or state.done:
        raise HTTPException(status_code=404, detail={"error": "not_found",
                                                     "detail": f"no active scan {scan_id}"})
    state.cancel_event.set()
    return Response(status_code=204)


@router.delete("/scan/{scan_id}", status_code=204)
def remove_scan(scan_id: int, request: Request) -> Response:
    if REGISTRY.active_id() == scan_id:
        raise HTTPException(status_code=409, detail={"error": "scan_in_progress",
                                                     "detail": "cannot delete running scan"})
    request.app.state.repo.delete_scan(scan_id)
    return Response(status_code=204)
