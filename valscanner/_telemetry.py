"""Sentry initialization for ValScanner.

Errors are reported to Sentry by default. Disable by setting
``VALSCANNER_DISABLE_TELEMETRY=1``. Redirect to a self-hosted Sentry
project by setting ``VALSCANNER_SENTRY_DSN``. Override the deployment
environment tag with ``VALSCANNER_SENTRY_ENV``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from valscanner import __version__

_DEFAULT_DSN = (
    "https://6c94706b4333ca502b5727b633ce7ab2"
    "@o4511468367380480.ingest.de.sentry.io/4511468373475408"
)

log = logging.getLogger(__name__)


def _is_truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


def _build_path_replacements() -> list[tuple[str, str]]:
    rep: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(needle: str, replacement: str) -> None:
        if needle and needle not in seen and needle not in {"/", "\\"}:
            seen.add(needle)
            rep.append((needle, replacement))

    try:
        add(str(Path.home()), "~")
    except Exception:
        pass
    user = os.environ.get("USER") or os.environ.get("USERNAME")
    if user and len(user) >= 2:
        add(f"/Users/{user}", "~")
        add(f"/home/{user}", "~")
        add(f"C:\\Users\\{user}", "~")
    return rep


def _scrub(obj: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(obj, str):
        for needle, replacement in replacements:
            if needle in obj:
                obj = obj.replace(needle, replacement)
        return obj
    if isinstance(obj, list):
        return [_scrub(item, replacements) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_scrub(item, replacements) for item in obj)
    if isinstance(obj, dict):
        return {k: _scrub(v, replacements) for k, v in obj.items()}
    return obj


def _before_send(event: dict, hint: dict) -> dict | None:
    try:
        return _scrub(event, _build_path_replacements())
    except Exception:
        return event


def init_sentry(component: str) -> None:
    """Initialize Sentry for the given entry point ("gui", "cli", "web").

    Silently no-ops on any failure — telemetry must never crash the app.
    """
    if _is_truthy(os.environ.get("VALSCANNER_DISABLE_TELEMETRY")):
        return

    dsn = os.environ.get("VALSCANNER_SENTRY_DSN", _DEFAULT_DSN)
    if not dsn:
        return

    try:
        import sentry_sdk
    except Exception:
        return

    try:
        sentry_sdk.init(
            dsn=dsn,
            release=f"valscanner@{__version__}",
            environment=os.environ.get("VALSCANNER_SENTRY_ENV", "production"),
            send_default_pii=False,
            traces_sample_rate=0.0,
            profiles_sample_rate=0.0,
            before_send=_before_send,
        )
        sentry_sdk.set_tag("component", component)
    except Exception:
        log.debug("Sentry init failed", exc_info=True)
