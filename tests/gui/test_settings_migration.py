"""Tests for valscanner.gui.persistence — key migration and JSON helpers."""

import pytest


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Clear QSettings before each test so prior test state doesn't leak."""
    from valscanner.gui.persistence import settings
    s = settings()
    s.clear()
    s.sync()
    yield
    s.clear()
    s.sync()


def test_migrate_v0_to_v1_renames_keys(qapp):
    from valscanner.gui.persistence import SCHEMA_VERSION, settings, Keys, migrate

    s = settings()
    s.setValue("windowGeometry", b"fake_geo")
    s.setValue("splitterState",  b"fake_splitter")
    s.setValue("vsplitterState", b"fake_vsplit")
    s.sync()

    migrate()

    s2 = settings()
    assert s2.value(Keys.WINDOW_GEOMETRY) == b"fake_geo"
    assert s2.value(Keys.SPLITTER_STATE)  == b"fake_splitter"
    assert s2.value(Keys.VSPLITTER_STATE) == b"fake_vsplit"
    assert s2.value("windowGeometry")     is None
    assert s2.value("splitterState")      is None
    assert s2.value("vsplitterState")     is None
    assert int(s2.value(Keys.SCHEMA_VER, 0)) == SCHEMA_VERSION


def test_migrate_idempotent(qapp):
    from valscanner.gui.persistence import SCHEMA_VERSION, settings, Keys, migrate

    s = settings()
    s.setValue("windowGeometry", b"geo_data")
    s.sync()

    migrate()
    migrate()  # second call must not lose data or double-move

    s2 = settings()
    assert s2.value(Keys.WINDOW_GEOMETRY) == b"geo_data"
    assert int(s2.value(Keys.SCHEMA_VER, 0)) == SCHEMA_VERSION


def test_migrate_skips_absent_old_keys(qapp):
    from valscanner.gui.persistence import SCHEMA_VERSION, settings, Keys, migrate

    migrate()

    s = settings()
    assert int(s.value(Keys.SCHEMA_VER, 0)) == SCHEMA_VERSION
    assert s.value(Keys.WINDOW_GEOMETRY) is None


def test_migrate_v1_to_v2_clears_file_table_header(qapp):
    """v1→v2 wipes the persisted file-table header state (column order changed)."""
    from valscanner.gui.persistence import SCHEMA_VERSION, settings, Keys, migrate

    s = settings()
    s.setValue(Keys.FILE_TABLE_HDR, b"old_header_bytes")
    s.setValue(Keys.SCHEMA_VER, 1)
    s.sync()

    migrate()

    s2 = settings()
    assert s2.value(Keys.FILE_TABLE_HDR) is None
    assert int(s2.value(Keys.SCHEMA_VER, 0)) == SCHEMA_VERSION


def test_get_set_json_roundtrip(qapp):
    from valscanner.gui.persistence import get_json, set_json

    payload = {"hidden_categories": ["image", "video"], "min_bytes": 1048576}
    set_json("test/json_key", payload)
    assert get_json("test/json_key") == payload


def test_get_json_default_on_missing(qapp):
    from valscanner.gui.persistence import get_json

    assert get_json("nonexistent/key", "sentinel") == "sentinel"
    assert get_json("nonexistent/key") is None


def test_get_json_default_on_malformed(qapp):
    from valscanner.gui.persistence import settings, get_json

    settings().setValue("bad/json", "not { valid json }")
    assert get_json("bad/json", "fallback") == "fallback"
