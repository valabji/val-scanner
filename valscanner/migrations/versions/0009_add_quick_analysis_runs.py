"""Add quick_analysis_runs table

Persists the rows produced by `--quick-analyze` (heuristic folder
classifier with media-library rollup and cross-drive mirror grouping)
so the CLI and GUI can browse run history instead of recomputing.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-07 00:00:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "quick_analysis_runs" in sa_inspect(bind).get_table_names():
        return
    op.create_table(
        "quick_analysis_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ran_at", sa.Text, nullable=False),
        sa.Column("scope_label", sa.Text, nullable=False, server_default=""),
        sa.Column("min_files", sa.Integer, nullable=False, server_default="3"),
        sa.Column("include_mixed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer, server_default="0"),
        sa.Column("row_count", sa.Integer, server_default="0"),
        sa.Column("filters_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("results_json", sa.Text, nullable=False, server_default="[]"),
    )
    op.create_index(
        "idx_quick_analysis_ran_at", "quick_analysis_runs", ["ran_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_quick_analysis_ran_at", table_name="quick_analysis_runs")
    op.drop_table("quick_analysis_runs")
