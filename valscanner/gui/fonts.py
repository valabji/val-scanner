from __future__ import annotations
from pathlib import Path
from PySide6.QtGui import QFontDatabase

_UI_FAMILY   = ""
_MONO_FAMILY = ""

_ASSETS_DIR = Path(__file__).parent.parent / "assets" / "fonts"

_UI_FILES = ["Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf"]
_MONO_FILES = ["JetBrainsMono-Regular.ttf", "JetBrainsMono-Medium.ttf"]


def load_fonts() -> None:
    global _UI_FAMILY, _MONO_FAMILY
    for name in _UI_FILES + _MONO_FILES:
        path = _ASSETS_DIR / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    families = QFontDatabase.families()
    if "Inter" in families:
        _UI_FAMILY = "Inter"
    if "JetBrains Mono" in families:
        _MONO_FAMILY = "JetBrains Mono"


def ui_font_family() -> str:
    return _UI_FAMILY or "system-ui"


def mono_font_family() -> str:
    return _MONO_FAMILY or "monospace"
