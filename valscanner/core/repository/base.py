from __future__ import annotations

from sqlalchemy.engine import Engine

from ..db_config import get_engine
from ..schema import create_all

_INITIALIZED_ATTR = "_valscanner_schema_initialized"


class RepositoryBase:
    """Shared engine + dialect access for every domain mixin.

    Runs `create_all` exactly once per engine, even if multiple Repository
    instances wrap the same engine. The engine cache in `db_config` keeps
    this efficient across URL-based Repository constructions.
    """

    def __init__(self, engine_or_url: Engine | str) -> None:
        if isinstance(engine_or_url, str):
            self._engine: Engine = get_engine(engine_or_url)
        else:
            self._engine = engine_or_url
        if not getattr(self._engine, _INITIALIZED_ATTR, False):
            create_all(self._engine)
            setattr(self._engine, _INITIALIZED_ATTR, True)

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def dialect(self) -> str:
        return self._engine.dialect.name
