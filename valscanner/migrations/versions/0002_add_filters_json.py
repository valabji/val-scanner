"""Add filters_json column to analysis_runs (if missing)

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-02 00:00:00.000000

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "analysis_runs", "filters_json"):
        if bind.dialect.name == "sqlite":
            bind.execute(text(
                "ALTER TABLE analysis_runs "
                "ADD COLUMN filters_json TEXT NOT NULL DEFAULT '{}'"
            ))
        else:
            bind.execute(text(
                "ALTER TABLE analysis_runs "
                "ADD COLUMN IF NOT EXISTS filters_json TEXT NOT NULL DEFAULT '{}'"
            ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # leave the column — has a default, harmless
    bind.execute(text("ALTER TABLE analysis_runs DROP COLUMN IF EXISTS filters_json"))
