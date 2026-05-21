"""Add gui_cache table for GUI result caching

Stores serialised payloads (folder tree, file list first page) keyed by a
lightweight DB-version fingerprint so repeat opens skip expensive queries.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-21 00:00:00.000000

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # migration 0001 calls metadata.create_all() which already includes
    # gui_cache for DBs bootstrapped after this migration was added, so
    # only create the table when it doesn't already exist.
    bind = op.get_bind()
    if "gui_cache" not in sa_inspect(bind).get_table_names():
        op.create_table(
            "gui_cache",
            sa.Column("key", sa.Text, primary_key=True),
            sa.Column("value_json", sa.Text, nullable=False),
            sa.Column("version", sa.Text, nullable=False),
            sa.Column("created_at", sa.Text, nullable=False),
        )


def downgrade() -> None:
    op.drop_table("gui_cache")
