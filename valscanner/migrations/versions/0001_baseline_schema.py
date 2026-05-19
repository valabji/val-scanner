"""Baseline schema (creates all tables + FTS objects)

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00.000000

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op

from valscanner.core.schema import metadata, apply_sqlite_fts

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind, checkfirst=True)
    # Explicit call (in addition to the event listener) so that running this
    # migration against a DB whose `files` table already exists still gets
    # the FTS5 objects. The event listener only fires when `files` itself
    # is being created.
    apply_sqlite_fts(bind)


def downgrade() -> None:
    metadata.drop_all(op.get_bind())
