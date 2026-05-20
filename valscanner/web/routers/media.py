from __future__ import annotations
import hashlib

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter(prefix="/api", tags=["media"])

_SAMPLE_MIME = {
    "mp3": "audio/mpeg", "ogg": "audio/ogg", "wav": "audio/wav",
    "m4a": "audio/mp4", "aac": "audio/aac",
    "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
}


def _serve(data: bytes, mime: str) -> Response:
    etag = '"' + hashlib.sha1(data).hexdigest()[:16] + '"'
    return Response(
        content=data, media_type=mime,
        headers={"Cache-Control": "max-age=86400, immutable", "ETag": etag},
    )


@router.get("/thumbnail/{file_id}")
def get_thumbnail(file_id: int, request: Request) -> Response:
    data = request.app.state.repo.get_thumbnail(file_id)
    if data is None:
        raise HTTPException(status_code=404,
                            detail={"error": "no_thumbnail",
                                    "detail": f"no thumbnail for file {file_id}"})
    return _serve(data, "image/jpeg")


@router.get("/sample/{file_id}")
def get_sample(file_id: int, request: Request) -> Response:
    pair = request.app.state.repo.get_media_sample(file_id)
    if pair is None:
        raise HTTPException(status_code=404,
                            detail={"error": "no_sample",
                                    "detail": f"no sample for file {file_id}"})
    data, fmt = pair
    mime = _SAMPLE_MIME.get((fmt or "").lower(), "application/octet-stream")
    return _serve(data, mime)
