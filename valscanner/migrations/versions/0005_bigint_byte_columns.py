"""Widen byte-count columns to BIGINT

PostgreSQL's `INTEGER` is `int4` (max ~2.1 GB), which overflows the moment a
scan touches a folder or file larger than that. SQLite stores all integers
with variable width, so this migration is a no-op there.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-20 00:00:00.000000

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TARGETS = (
    ("scans",   "total_bytes"),
    ("files",   "size_bytes"),
    ("folders", "total_bytes"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite INTEGER is already variable-width; nothing to do.
        return
    for table, column in _TARGETS:
        op.alter_column(table, column, type_=sa.BigInteger(), existing_nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    for table, column in _TARGETS:
        # Narrowing is unsafe if real data already exceeds int4, but keep it
        # symmetric for completeness. Will fail loudly on overflow.
        op.alter_column(table, column, type_=sa.Integer(), existing_nullable=True)
