"""Tests for valscanner.core.logging_config.setup_logging.

`setup_logging` mutates the root logger, so each test must restore it.
"""
from __future__ import annotations

import logging
import logging.handlers

import pytest

from valscanner.core.logging_config import setup_logging


@pytest.fixture(autouse=True)
def _restore_root_logger():
    """Snapshot/restore root logger so tests don't bleed into each other."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        yield
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def _handler_types(handlers):
    return {type(h) for h in handlers}


def test_console_only_by_default():
    setup_logging()
    handlers = logging.getLogger().handlers
    assert any(isinstance(h, logging.StreamHandler) for h in handlers)
    # No file handler when log_file omitted
    assert not any(
        isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers
    )


def test_log_no_console_suppresses_stream_handler():
    setup_logging(log_no_console=True)
    handlers = logging.getLogger().handlers
    assert handlers == []  # No file, no console → empty


def test_invalid_level_falls_back_to_info():
    setup_logging(log_level="not-a-real-level")
    assert logging.getLogger().level == logging.INFO


def test_explicit_level_applied():
    setup_logging(log_level="debug")
    assert logging.getLogger().level == logging.DEBUG


def test_repeated_setup_does_not_duplicate_handlers():
    """Re-invocation must clear prior handlers so logs don't double-print."""
    setup_logging()
    setup_logging()
    handlers = logging.getLogger().handlers
    assert sum(isinstance(h, logging.StreamHandler) for h in handlers) == 1


def test_file_handler_writes_and_creates_parent(tmp_path):
    log_file = tmp_path / "nested" / "subdir" / "vs.log"
    setup_logging(log_file=str(log_file), log_max_size=2048, log_backup_count=2)

    handlers = logging.getLogger().handlers
    rot = [h for h in handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(rot) == 1
    assert rot[0].maxBytes == 2048
    assert rot[0].backupCount == 2

    # Parent directory was created on demand
    assert log_file.parent.is_dir()

    # Actually log something and make sure it lands on disk
    logging.getLogger("vstest").error("hello-from-test")
    for h in handlers:
        h.flush()
    assert "hello-from-test" in log_file.read_text()
