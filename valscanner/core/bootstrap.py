from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import inspect

from alembic import command
from alembic.config import Config

from .app_settings import mask_url
from .db_config import get_engine

log = logging.getLogger(__name__)


def _alembic_resource_paths() -> tuple[Path, Path]:
    """Return (alembic.ini path, migrations dir path).

    Handles editable installs, pip wheels, and PyInstaller bundles.
    We rely on __file__ rather than importlib.resources.as_file so this works
    on Python 3.8 (as_file requires 3.9+).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS) / "valscanner"
        return base / "alembic.ini", base / "migrations"

    # In editable installs and pip wheels, __file__ is
    # valscanner/core/bootstrap.py, so parent.parent is the valscanner/
    # package directory that contains alembic.ini and migrations/.
    pkg = Path(__file__).parent.parent
    return pkg / "alembic.ini", pkg / "migrations"


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

    Passwords are never logged raw — all log lines use mask_url().
    """
    if url.startswith("sqlite:///"):
        db_file = url[len("sqlite:///"):]
        if db_file:
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)

    engine = get_engine(url)
    insp = inspect(engine)
    existing = set(insp.get_table_names())

    cfg = _alembic_config(url)

    has_alembic = "alembic_version" in existing
    has_schema  = "files" in existing or "scans" in existing

    if has_schema and not has_alembic:
        log.info("Stamping existing DB at baseline revision 0001 (%s)", mask_url(url))
        command.stamp(cfg, "0001")

    command.upgrade(cfg, "head")
