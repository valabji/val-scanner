"""Logging configuration for ValScanner."""
from __future__ import annotations
import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(
    log_file: str | None = None,
    log_level: str = "INFO",
    log_max_size: int = 10485760,  # 10MB
    log_backup_count: int = 5,
    log_no_console: bool = False,
) -> None:
    """Configure logging for ValScanner.

    Args:
        log_file: Path to log file. If None, no file logging.
        log_level: Log level (DEBUG, INFO, WARNING, ERROR).
        log_max_size: Max size per log file in bytes (for rotation).
        log_backup_count: Number of backup logs to keep.
        log_no_console: If True, disable console output (file only).
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Clear any existing handlers to avoid duplicates
    root_logger.handlers = []

    # Console handler (stderr) — only if not suppressed
    if not log_no_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s: %(message)s")
        )
        root_logger.addHandler(console_handler)

    # File handler (rotating)
    if log_file:
        log_path = Path(log_file).expanduser().resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            str(log_path),
            maxBytes=log_max_size,
            backupCount=log_backup_count,
        )
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
            )
        )
        root_logger.addHandler(file_handler)
