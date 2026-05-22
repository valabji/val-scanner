"""Centralised QSettings key registry, JSON helpers, and schema migration.

SCHEMA_VERSION tracks the layout of keys stored under the app's QSettings
namespace. When keys are renamed or reorganised, bump the version and add a
migration function below.

Version history
  0 → 1  Renamed flat geometry/splitter keys into window/* namespace;
          added fileTable/* and similar/* sections.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QSettings

from .theme import ORG_NAME, APP_NAME

SCHEMA_VERSION = 1


class Keys:
    # Schema bookkeeping
    SCHEMA_VER       = "app/schema_version"

    # Window geometry / layout (was: "windowGeometry", "splitterState", …)
    WINDOW_GEOMETRY  = "window/geometry"
    SPLITTER_STATE   = "window/splitter"
    VSPLITTER_STATE  = "window/vsplitter"

    # File table — view mode, display index, header sort + widths
    FILE_VIEW_MODE   = "fileTable/viewMode"    # "browser" | "flat"
    FILE_VIEW_INDEX  = "fileTable/viewIndex"   # int 0=Details 1=Grid 2=List
    FILE_TABLE_HDR   = "fileTable/headerState" # QByteArray from saveState()

    # File table — persisted filter values
    FILES_FILTERS    = "files/filters"         # JSON-encoded dict (view-filter state)

    # Similar Folders panel — controls
    SIM_SORT_IDX     = "similar/sortIndex"
    SIM_THRESH_IDX   = "similar/thresholdIndex"
    SIM_MIN_FILES    = "similar/minFiles"
    SIM_MIN_SIZE     = "similar/minSizeText"
    SIM_FILTERS      = "similar/filters"       # JSON-encoded dict
    SIM_SCAN_IDS     = "similar/scanIds"       # JSON-encoded list[int]

    # Scans panel
    SCANS_HEADER     = "scans/headerState"     # QByteArray from saveState()

    # Non-modal dialog geometry
    VIEW_FILTERS_GEO = "dialogs/viewFilters/geometry"

    # ScanOptionsDialog — collapsed/expanded state of Filters group
    SCAN_OPTIONS_FILTERS_EXPANDED = "dialogs/scanOptions/filtersExpanded"

    # Collapsible rail widths (restore splitter slot when re-expanding)
    FOLDER_RAIL_WIDTH = "panel/folderRailWidth"
    DETAIL_RAIL_WIDTH = "panel/detailRailWidth"


def settings() -> QSettings:
    """Return a QSettings instance bound to the app's org/name."""
    return QSettings(ORG_NAME, APP_NAME)


def get_json(key: str, default=None):
    """Read a JSON-encoded value; return *default* if absent or malformed."""
    val = settings().value(key)
    if val is None:
        return default
    try:
        return json.loads(val)
    except (ValueError, TypeError):
        return default


def set_json(key: str, value) -> None:
    """Write *value* as a JSON string under *key*."""
    settings().setValue(key, json.dumps(value))


# ── Migration helpers ─────────────────────────────────────────────────────────

def _migrate_v0_to_v1(s: QSettings) -> None:
    """Rename flat geometry/splitter keys into the window/* namespace."""
    for old, new in (
        ("windowGeometry", Keys.WINDOW_GEOMETRY),
        ("splitterState",  Keys.SPLITTER_STATE),
        ("vsplitterState", Keys.VSPLITTER_STATE),
    ):
        val = s.value(old)
        if val is not None:
            s.setValue(new, val)
            s.remove(old)


def _migrate_v1_to_v2(s: QSettings) -> None:
    """Clear saved file-table header state: Hash column added, column order changed."""
    s.remove(Keys.FILE_TABLE_HDR)


def migrate() -> None:
    """Run any pending schema migrations; idempotent across calls."""
    s = settings()
    ver = int(s.value(Keys.SCHEMA_VER, 0) or 0)
    if ver < 1:
        _migrate_v0_to_v1(s)
        s.setValue(Keys.SCHEMA_VER, 1)
    if ver < 2:
        _migrate_v1_to_v2(s)
        s.setValue(Keys.SCHEMA_VER, 2)
