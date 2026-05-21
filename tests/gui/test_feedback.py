"""Unit tests for feedback.py — level taxonomy, color/icon mapping."""

import pytest
from valscanner.gui.feedback import Level, TIMEOUTS, color_for, icon_for


def test_level_values():
    assert Level.INFO == "info"
    assert Level.SUCCESS == "success"
    assert Level.WARNING == "warning"
    assert Level.ERROR == "error"
    assert Level.BUSY == "busy"


def test_timeouts_all_levels():
    for level in ("info", "success", "warning", "error", "busy"):
        assert isinstance(TIMEOUTS[level], int)


def test_sticky_levels_have_zero_timeout():
    assert TIMEOUTS["error"] == 0
    assert TIMEOUTS["busy"] == 0


def test_color_for_returns_string():
    for level in ("info", "success", "warning", "error", "busy"):
        c = color_for(level)
        assert isinstance(c, str)
        assert c  # non-empty


def test_color_for_unknown_defaults():
    c = color_for("unknown_level")
    assert isinstance(c, str)


def test_icon_for_returns_string():
    for level in ("info", "success", "warning", "error", "busy"):
        assert isinstance(icon_for(level), str)
