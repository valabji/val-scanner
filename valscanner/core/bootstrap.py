from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from alembic import command
from alembic.config import Config

from .app_settings import mask_url
from .db_config import get_engine
from .exceptions import DBConnectionError

log = logging.getLogger(__name__)


def _package_root() -> Path:
    """Locate the installed `valscanner/` package directory.

    Prefers `importlib.resources.files` (3.9+) so this works for editable
    installs, regular wheels, and namespace-style layouts. Falls back to a
    `__file__`-based lookup on Python 3.8.
    """
    try:
        from importlib.resources import files as _pkg_files  # type: ignore[attr-defined]
        return Path(str(_pkg_files("valscanner")))
    except ImportError:
        # Python 3.8: importlib.resources.files does not exist. `__file__`
        # always points to the real installed location of this module, so
        # walking two parents up lands on the package root.
        return Path(__file__).resolve().parent.parent


def _alembic_resource_paths() -> tuple[Path, Path]:
    """Return (alembic.ini path, migrations dir path).

    Resolves editable installs, wheels, and PyInstaller frozen bundles
    (which lay files under sys._MEIPASS).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS) / "valscanner"
        return base / "alembic.ini", base / "migrations"

    pkg_root = _package_root()
    return pkg_root / "alembic.ini", pkg_root / "migrations"


def _alembic_config(url: str) -> Config:
    ini_path, migrations_path = _alembic_resource_paths()
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(migrations_path))
    return cfg


def ensure_schema(url: str) -> None:
    """Bring the database at *url* up to Alembic head.

    - Fresh DB (no tables): upgrade head creates everything.
    - v0.1.x DB (tables exist, no alembic_version): stamp 0001, then
      upgrade head so migrations 0002/0004 run.
    - Already-current DB: upgrade head is a fast no-op.

    Any connection failure is re-raised as `DBConnectionError`, with the URL
    passed through `mask_url` so passwords never reach logs or tracebacks.
    """
    if url.startswith("sqlite:///"):
        db_file = url[len("sqlite:///"):]
        if db_file:
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)

    masked = mask_url(url)
    try:
        engine = get_engine(url)
        insp = inspect(engine)
        existing = set(insp.get_table_names())

        cfg = _alembic_config(url)

        has_alembic = "alembic_version" in existing
        has_schema  = "files" in existing or "scans" in existing

        if has_schema and not has_alembic:
            log.info("Stamping existing DB at baseline revision 0001 (%s)", masked)
            command.stamp(cfg, "0001")

        command.upgrade(cfg, "head")
    except (OperationalError, SQLAlchemyError, ImportError) as exc:
        # Strip the SQLAlchemy/driver message of any embedded URL before
        # re-raising. ImportError covers the "psycopg2 not installed" path
        # surfaced when SQLAlchemy lazy-loads the dialect.
        raise DBConnectionError(
            f"could not initialize database at {masked}: {exc.__class__.__name__}: {exc}"
        ) from None
