from __future__ import annotations

PRESETS: dict[str, int] = {
    "compact": 26,
    "normal":  32,
    "relaxed": 38,
}
DEFAULT = "normal"
_SETTING_KEY = "display/rowDensity"

_current   = DEFAULT
_callbacks: list = []


def load_density() -> None:
    global _current
    try:
        from PySide6.QtCore import QSettings
        from .theme import ORG_NAME, APP_NAME
        val = QSettings(ORG_NAME, APP_NAME).value(_SETTING_KEY, DEFAULT)
        if val in PRESETS:
            _current = val
    except Exception:
        pass


def get_density() -> str:
    return _current


def get_row_height() -> int:
    return PRESETS[_current]


def set_density(name: str) -> None:
    global _current
    if name not in PRESETS:
        return
    _current = name
    try:
        from PySide6.QtCore import QSettings
        from .theme import ORG_NAME, APP_NAME
        QSettings(ORG_NAME, APP_NAME).setValue(_SETTING_KEY, name)
    except Exception:
        pass
    for cb in list(_callbacks):
        try:
            cb()
        except Exception:
            import traceback
            traceback.print_exc()


def on_changed(cb) -> None:
    _callbacks.append(cb)
