# GUI tests

## What belongs here

- **Construction smoke tests** for every QWidget subclass in the GUI. A widget that can't be constructed is a regression.
- **Unit tests for non-Qt logic** under `valscanner/gui/` — feedback formatters, persistence key handling, FlowLayout math, dataclasses.
- **Contract tests** (e.g. "every worker has a stop method").

## What does NOT belong here

- Full interaction flows (click X, drag Y, assert pixel Z). The repo has no Qt UI test framework today; adding one is its own initiative.
- Tests that require a real display, a real file dialog, or a real keyring. Use the conftest fixtures to isolate.
- Tests that hit real network endpoints. PostgreSQL connection tests belong in `tests/core/test_repository_pg.py` (skipped unless a test DB is configured).

## Running

```
pip install -e ".[dev]"
QT_QPA_PLATFORM=offscreen pytest tests/gui/
```

The `QT_QPA_PLATFORM=offscreen` is set automatically by `conftest.py` but is shown here for CI clarity.
