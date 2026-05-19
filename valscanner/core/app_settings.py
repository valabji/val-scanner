from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit

from platformdirs import user_config_dir

log = logging.getLogger(__name__)

_KEYRING_SERVICE = "valscanner"
_KEYRING_USER    = "pg_password"

_DEFAULTS: dict = {
    "db_backend": "sqlite",
    "sqlite_path": "~/valscanner.db",
    "pg_host": "localhost",
    "pg_port": 5432,
    "pg_database": "valscanner",
    "pg_user": "",
    # pg_password intentionally NOT in defaults — comes from keyring.
}

# ── path helpers ─────────────────────────────────────────────────────────────

def _config_dir() -> Path:
    return Path(user_config_dir("valscanner"))


def _settings_file() -> Path:
    return _config_dir() / "settings.json"


def _normalize_sqlite_path(raw: str) -> str:
    """Expand ~ and convert to POSIX form so it slots into a sqlite:// URL."""
    if "\\" in raw:
        from pathlib import PureWindowsPath
        return PureWindowsPath(raw).as_posix()
    return Path(raw).expanduser().as_posix()


# ── keyring with fallback ────────────────────────────────────────────────────

_warned_no_keyring = False


def _get_pg_password(settings_blob: dict) -> str:
    global _warned_no_keyring
    try:
        import keyring
        val = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
        if val is not None:
            return val
    except Exception as exc:  # noqa: BLE001
        if not _warned_no_keyring:
            log.warning("keyring unavailable (%s); falling back to settings.json", exc)
            _warned_no_keyring = True
    return settings_blob.get("pg_password", "")


def _set_pg_password(settings_blob: dict, value: str) -> None:
    global _warned_no_keyring
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, value)
        settings_blob.pop("pg_password", None)  # remove any plaintext copy
        return
    except Exception as exc:  # noqa: BLE001
        if not _warned_no_keyring:
            log.warning("keyring unavailable (%s); storing password in settings.json", exc)
            _warned_no_keyring = True
    settings_blob["pg_password"] = value


# ── load / save ──────────────────────────────────────────────────────────────

def load() -> dict:
    """Return settings, merged with defaults. Includes the resolved password
    under key `pg_password` regardless of where it was stored."""
    sf = _settings_file()
    if not sf.exists():
        s = dict(_DEFAULTS)
    else:
        try:
            s = {**_DEFAULTS, **json.loads(sf.read_text())}
        except (json.JSONDecodeError, OSError):
            s = dict(_DEFAULTS)
    s["pg_password"] = _get_pg_password(s)
    return s


def save(settings: dict) -> None:
    """Persist settings. Moves `pg_password` to keyring if possible."""
    sf = _settings_file()
    sf.parent.mkdir(parents=True, exist_ok=True)

    blob = dict(settings)
    pw = blob.pop("pg_password", "")
    _set_pg_password(blob, pw)
    sf.write_text(json.dumps(blob, indent=2))


# ── URL resolution ───────────────────────────────────────────────────────────

def active_url(db_path_override: str | None = None) -> str:
    """Build the SQLAlchemy URL for the currently-active backend.

    Priority:
      1. db_path_override (string path or full URL)
      2. DATABASE_URL env var
      3. saved settings.json (+ keyring for PG password)
      4. built-in default (sqlite:///~/valscanner.db with ~ expanded)
    """
    if db_path_override:
        if db_path_override.startswith(("sqlite://", "postgresql://", "postgres://")):
            return db_path_override
        return f"sqlite:///{_normalize_sqlite_path(db_path_override)}"

    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url

    s = load()
    if s["db_backend"] == "postgresql":
        user = quote(s["pg_user"], safe="") if s["pg_user"] else ""
        pw   = quote(s["pg_password"], safe="") if s["pg_password"] else ""
        auth = f"{user}:{pw}@" if user else ""
        return f"postgresql://{auth}{s['pg_host']}:{s['pg_port']}/{s['pg_database']}"

    return f"sqlite:///{_normalize_sqlite_path(s['sqlite_path'])}"


def mask_url(url: str) -> str:
    """Return `url` with any password replaced by `***`. Safe for logging."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.password is None:
        return url
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    if parts.username:
        netloc = f"{parts.username}:***@{netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
