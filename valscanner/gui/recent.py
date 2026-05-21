from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QSettings


_MAX_RECENTS = 10
_ORG  = "valscanner"
_APP  = "ValScanner"
_KEY  = "recentDatabases"
_AKEY = "activeDatabase"


class RecentDBsModel(QObject):
    """Single source of truth for recently-opened databases.

    Both the File menu and the welcome-screen chip strip subscribe to
    `changed` and re-render themselves on each emit.
    """

    changed = Signal()

    _instance: RecentDBsModel | None = None

    @classmethod
    def instance(cls) -> RecentDBsModel:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active: Path | None = None

    def _settings(self) -> QSettings:
        return QSettings(_ORG, _APP)

    def items(self) -> list[Path]:
        s = self._settings()
        raw = s.value(_KEY, [])
        if isinstance(raw, str):
            raw = [raw]
        return [Path(p) for p in raw if p]

    def push(self, path: str | Path) -> None:
        p = Path(path)
        paths = [x for x in self.items() if x != p]
        paths.insert(0, p)
        paths = paths[:_MAX_RECENTS]
        s = self._settings()
        s.setValue(_KEY, [str(x) for x in paths])
        self.changed.emit()

    def remove(self, path: str | Path) -> None:
        p = Path(path)
        paths = [x for x in self.items() if x != p]
        self._settings().setValue(_KEY, [str(x) for x in paths])
        self.changed.emit()

    def active(self) -> Path | None:
        if self._active is not None:
            return self._active
        s = self._settings()
        raw = s.value(_AKEY, "")
        return Path(raw) if raw else None

    def set_active(self, path: str | Path | None) -> None:
        self._active = Path(path) if path else None
        s = self._settings()
        s.setValue(_AKEY, str(self._active) if self._active else "")
        self.changed.emit()
