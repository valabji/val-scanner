"""Add btree indexes on files.path and folders.path

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-30 00:00:00.000000

Speeds up the "open folder" path-prefix queries (WHERE path LIKE 'X/%'
[AND path NOT LIKE 'X/%/%']) which were full-table scans of 5M+ rows on
the All-Scans browser path. Postgres uses C collation so a plain btree
supports LIKE 'prefix%' index range scans.
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indexes(bind, table: str) -> set[str]:
    return {i["name"] for i in inspect(bind).get_indexes(table)}


def _create_index(bind, name: str, table: str, column: str) -> None:
    if name in _indexes(bind, table):
        return
    dialect = bind.dialect.name
    if dialect == "postgresql":
        # CONCURRENTLY can't run inside a transaction. Alembic opens an
        # implicit one, so we commit first, run the CREATE, and rely on
        # the next statement to start a fresh transaction.
        op.execute("COMMIT")
        op.execute(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{name}" '
            f'ON "{table}" ("{column}")'
        )
        op.execute("BEGIN")
    else:
        op.create_index(name, table, [column])


def _drop_index(bind, name: str, table: str) -> None:
    if name not in _indexes(bind, table):
        return
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute("COMMIT")
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"')
        op.execute("BEGIN")
    else:
        op.drop_index(name, table_name=table)


def upgrade() -> None:
    bind = op.get_bind()
    _create_index(bind, "ix_files_path",   "files",   "path")
    _create_index(bind, "ix_folders_path", "folders", "path")


def downgrade() -> None:
    bind = op.get_bind()
    _drop_index(bind, "ix_folders_path", "folders")
    _drop_index(bind, "ix_files_path",   "files")
