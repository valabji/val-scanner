"""Add composite (scan_id, category, path) index; drop redundant idx_scan_id

Revision ID: 0004
Revises: 0003
Create Date: 2026-01-04 00:00:00.000000

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indexes(bind, table: str) -> set[str]:
    return {i["name"] for i in inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    idx = _indexes(bind, "files")
    if "idx_files_scan_cat_path" not in idx:
        op.create_index(
            "idx_files_scan_cat_path", "files",
            ["scan_id", "category", "path"],
        )
    if "idx_scan_id" in idx:
        op.drop_index("idx_scan_id", table_name="files")


def downgrade() -> None:
    bind = op.get_bind()
    idx = _indexes(bind, "files")
    if "idx_files_scan_cat_path" in idx:
        op.drop_index("idx_files_scan_cat_path", table_name="files")
    if "idx_scan_id" not in idx:
        op.create_index("idx_scan_id", "files", ["scan_id"])
