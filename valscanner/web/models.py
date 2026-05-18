from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    db: str
    version: str


class ErrorResponse(BaseModel):
    error: str
    detail: str


class ScanRow(BaseModel):
    id: int
    label: str
    root: str
    scanned_at: str
    file_count: Optional[int] = None
    total_bytes: Optional[int] = None
    total_human: Optional[str] = None


class ScanRequest(BaseModel):
    root: str
    label: str = ""
    no_hash: bool = False


class ScanStartResponse(BaseModel):
    scan_id: int


class FileRow(BaseModel):
    id: int
    path: str
    name: str
    size: int
    size_human: str
    category: str
    tags: List[str]
    has_thumbnail: bool


class FilePage(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[FileRow]


class FolderNode(BaseModel):
    path: str
    name: str
    total_size: int
    size_human: str
    file_count: int
    children: List["FolderNode"]


FolderNode.model_rebuild()


class SimilarPair(BaseModel):
    folder_a: str
    folder_b: str
    scan_id_a: int
    scan_id_b: int
    scan_label_a: str
    scan_label_b: str
    score: float
    label: str
    name_score: float
    size_score: float
    ext_score: float
    hash_score: float
    files_a: int
    files_b: int
    bytes_a: int
    bytes_b: int
    shared_names: int
    shared_hashes: int
    children: List["SimilarPair"] = []


SimilarPair.model_rebuild()
