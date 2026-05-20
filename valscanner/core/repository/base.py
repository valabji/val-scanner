from __future__ import annotations

from sqlalchemy.engine import Engine

from ..db_config import get_engine


class RepositoryBase:
    """Shared engine + dialect access for every domain mixin.

    Schema creation is owned by `core.bootstrap.ensure_schema` (Alembic) in
    production paths and by the test fixtures that construct a Repository
    against an in-memory engine directly. The Repository itself never calls
    `create_all` — doing so used to silently bypass Alembic and leave
    `alembic_version` unpopulated for any caller that skipped bootstrap.
    """

    def __init__(self, engine_or_url: Engine | str) -> None:
        if isinstance(engine_or_url, str):
            self._engine: Engine = get_engine(engine_or_url)
        else:
            self._engine = engine_or_url

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def dialect(self) -> str:
        return self._engine.dialect.name
