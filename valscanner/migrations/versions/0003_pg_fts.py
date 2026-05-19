"""PostgreSQL: add tsvector fts column + GIN index + backfill

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-03 00:00:00.000000

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

from valscanner.core.schema import apply_pg_fts

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    apply_pg_fts(bind)
    bind.execute(text("""
        UPDATE files SET fts =
            setweight(to_tsvector('english', coalesce(filename, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(category, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(tags, '')),     'B') ||
            setweight(to_tsvector('english', coalesce(path, '')),     'C')
        WHERE fts IS NULL
    """))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("DROP TRIGGER IF EXISTS files_fts_trigger ON files"))
    bind.execute(text("DROP FUNCTION IF EXISTS files_fts_update()"))
    bind.execute(text("DROP INDEX IF EXISTS idx_files_fts"))
    bind.execute(text("ALTER TABLE files DROP COLUMN IF EXISTS fts"))
