from __future__ import annotations
from pathlib import PurePosixPath, PureWindowsPath
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Query, Request

from valscanner.core.schema import human_size
from valscanner.core.similarity import find_similar_folders
from ..models import FolderNode, SimilarPair

router = APIRouter(prefix="/api", tags=["folders"])


def _parts(path: str) -> Tuple[str, ...]:
    if "\\" in path and "/" not in path:
        return PureWindowsPath(path).parts
    return PurePosixPath(path).parts


def _build_tree(rows: List[Dict]) -> Optional[FolderNode]:
    if not rows:
        return None
    by_path: Dict[str, Dict] = {}
    for r in rows:
        by_path[r["path"]] = {
            "path": r["path"],
            "name": _parts(r["path"])[-1] if _parts(r["path"]) else r["path"],
            "total_size": r["total_bytes"] or 0,
            "size_human": human_size(r["total_bytes"] or 0),
            "file_count": r["file_count"] or 0,
            "children": [],
        }
    root_path = min(by_path.keys(), key=len)
    for p in sorted(by_path.keys(), key=len):
        if p == root_path:
            continue
        parts = _parts(p)
        for k in range(len(parts) - 1, 0, -1):
            cand = (str(PurePosixPath(*parts[:k])) if "/" in p
                    else str(PureWindowsPath(*parts[:k])))
            if cand in by_path:
                by_path[cand]["children"].append(by_path[p])
                break
        else:
            by_path[root_path]["children"].append(by_path[p])

    def to_node(d: Dict) -> FolderNode:
        return FolderNode(
            path=d["path"], name=d["name"],
            total_size=d["total_size"], size_human=d["size_human"],
            file_count=d["file_count"],
            children=[to_node(c) for c in d["children"]],
        )

    return to_node(by_path[root_path])


@router.get("/folders", response_model=Optional[FolderNode])
def get_folders(request: Request, scan_id: int = Query(..., ge=1)) -> Optional[FolderNode]:
    rows = request.app.state.repo.list_folders_for_scan(scan_id)
    return _build_tree(rows)


@router.get("/similar", response_model=List[SimilarPair])
def get_similar(request: Request, scan_id: int = Query(..., ge=1)) -> List[SimilarPair]:
    pairs = find_similar_folders(request.app.state.db_url, scan_ids=[scan_id])
    return [SimilarPair(**p) for p in pairs]
