from __future__ import annotations


class ScannerDBError(Exception):
    """Base class for all database-layer errors."""


class RecordNotFoundError(ScannerDBError):
    """Raised when a requested row does not exist."""


class DuplicateRecordError(ScannerDBError):
    """Raised on unique-constraint violations."""


class DBConnectionError(ScannerDBError):
    """Raised when a database connection cannot be established.
    Named `DBConnectionError` (not `ConnectionError`) so it does not shadow
    Python's builtin."""
