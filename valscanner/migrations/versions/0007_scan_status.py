"""Add status column to scans for crash-resume support

Tracks whether a scan finished cleanly ('complete') or was interrupted
('running'). Existing rows default to 'complete' since they were written
by older code that only persisted finished scans.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-23 00:00:00.000000

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa_inspect(bind).get_columns("scans")]
    if "status" not in cols:
        op.add_column("scans", sa.Column("status", sa.Text, server_default="complete"))


def downgrade() -> None:
    op.drop_column("scans", "status")
