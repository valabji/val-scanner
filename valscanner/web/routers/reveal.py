from __future__ import annotations
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["reveal"])


class RevealRequest(BaseModel):
    file_id: int


def _resolve(request: Request, file_id: int) -> Path:
    pair = request.app.state.repo.get_file_with_scan_root(file_id)
    if pair is None:
        raise HTTPException(status_code=404,
                            detail={"error": "not_found",
                                    "detail": f"no file {file_id}"})
    file_path = Path(pair[0]).resolve()
    scan_root = Path(pair[1]).resolve()
    try:
        file_path.relative_to(scan_root)
    except ValueError:
        raise HTTPException(status_code=403,
                            detail={"error": "outside_scan_root",
                                    "detail": "file path escapes scan root"})
    if not file_path.exists():
        raise HTTPException(status_code=410,
                            detail={"error": "gone",
                                    "detail": "file no longer exists on disk"})
    return file_path


def _reveal_in_os(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", str(path)], check=False)
    elif sys.platform.startswith("win"):
        subprocess.run(["explorer", f"/select,{path}"], check=False, shell=False)
    else:
        subprocess.run(["xdg-open", str(path.parent)], check=False)


@router.post("/reveal", status_code=204)
def reveal(req: RevealRequest, request: Request) -> Response:
    bound_host = getattr(request.client, "host", "127.0.0.1")
    if bound_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(status_code=403,
                            detail={"error": "remote_forbidden",
                                    "detail": "reveal is localhost-only"})
    path = _resolve(request, req.file_id)
    _reveal_in_os(path)
    return Response(status_code=204)
