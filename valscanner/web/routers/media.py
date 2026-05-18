from __future__ import annotations
import hashlib
import sqlite3
from typing import Optional, Tuple
from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter(prefix="/api", tags=["media"])


def _fetch_blob(db_path: str, table: str, file_id: int) -> Tuple[Optional[bytes], Optional[str]]:
    """Return (data, format) where format is None for thumbnails (always JPEG)."""
    conn = sqlite3.connect(db_path)
    try:
        if table == "thumbnails":
            row = conn.execute(
                "SELECT data FROM thumbnails WHERE file_id = ?", (file_id,)
            ).fetchone()
            return (row[0], None) if row else (None, None)
        row = conn.execute(
            "SELECT data, format FROM media_samples WHERE file_id = ?", (file_id,)
        ).fetchone()
        return (row[0], row[1]) if row else (None, None)
    finally:
        conn.close()


def _serve(data: bytes, mime: str) -> Response:
    etag = '"' + hashlib.sha1(data).hexdigest()[:16] + '"'
    return Response(
        content=data,
        media_type=mime,
        headers={
            "Cache-Control": "max-age=86400, immutable",
            "ETag": etag,
        },
    )


@router.get("/thumbnail/{file_id}")
def get_thumbnail(file_id: int, request: Request) -> Response:
    data, _ = _fetch_blob(request.app.state.db_path, "thumbnails", file_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "no_thumbnail", "detail": f"no thumbnail for file {file_id}"},
        )
    return _serve(data, "image/jpeg")


_SAMPLE_MIME = {
    "mp3": "audio/mpeg", "ogg": "audio/ogg", "wav": "audio/wav",
    "m4a": "audio/mp4", "aac": "audio/aac",
    "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
}


@router.get("/sample/{file_id}")
def get_sample(file_id: int, request: Request) -> Response:
    data, fmt = _fetch_blob(request.app.state.db_path, "media_samples", file_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "no_sample", "detail": f"no sample for file {file_id}"},
        )
    mime = _SAMPLE_MIME.get((fmt or "").lower(), "application/octet-stream")
    return _serve(data, mime)
