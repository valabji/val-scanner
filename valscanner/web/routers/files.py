from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

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

    result = request.app.state.repo.search_paged(
        scan_id=scan_id, search=search, category=category,
        page=page, page_size=page_size,
    )
    items = [
        FileRow(
            id=r["id"], path=r["path"], name=r["filename"],
            size=r["size_bytes"], size_human=r["size_human"],
            category=r["category"], tags=r["tags"],
            has_thumbnail=r["has_thumbnail"],
        )
        for r in result["items"]
    ]
    return FilePage(
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        items=items,
    )
