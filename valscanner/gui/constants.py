from __future__ import annotations

from .theme import load_palette


class HexColor(str):
    """Hex colour string. f'{color:AA}' where AA is a 2-hex-digit alpha emits rgba()."""
    def __format__(self, spec: str) -> str:
        if len(spec) == 2:
            try:
                r = int(self[1:3], 16)
                g = int(self[3:5], 16)
                b = int(self[5:7], 16)
                return f"rgba({r},{g},{b},{int(spec, 16)/255:.3f})"
            except (ValueError, IndexError):
                pass
        return super().__format__(spec)


class LazyColor(str):
    """Color token that reads from the current Theme palette on format/str access.

    Subclasses str so QColor(DARK_BG) and similar C-level APIs work using the
    initial (import-time) string value. f-strings and str() calls read the
    current theme via the overridden __format__ / __str__, making
    _apply_stylesheet() re-evaluate correctly after a theme switch.
    """

    def __new__(cls, key: str) -> "LazyColor":
        initial = load_palette()[key]
        obj = str.__new__(cls, initial)
        obj._key = key  # type: ignore[attr-defined]
        return obj

    def _value(self) -> str:
        return load_palette()[self._key]  # type: ignore[attr-defined]

    def __str__(self) -> str:
        return self._value()

    def __repr__(self) -> str:
        return f"LazyColor({self._key!r}={self._value()!r})"  # type: ignore[attr-defined]

    def __format__(self, spec: str) -> str:
        val = self._value()
        if len(spec) == 2:
            try:
                r = int(val[1:3], 16)
                g = int(val[3:5], 16)
                b = int(val[5:7], 16)
                return f"rgba({r},{g},{b},{int(spec, 16)/255:.3f})"
            except (ValueError, IndexError):
                pass
        return format(val, spec)

    def __eq__(self, other: object) -> bool:
        return str(self) == str(other)

    def __hash__(self) -> int:
        return hash(str(self))


CATEGORY_COLORS: dict[str, str] = {
    "photo":        "#4CAF50",
    "video":        "#2196F3",
    "audio":        "#9C27B0",
    "document":     "#FF9800",
    "spreadsheet":  "#009688",
    "presentation": "#E91E63",
    "code":         "#00BCD4",
    "data":         "#607D8B",
    "archive":      "#795548",
    "executable":   "#F44336",
    "font":         "#FF5722",
    "ebook":        "#8BC34A",
    "image":        "#CDDC39",
    "other":        "#9E9E9E",
}

DARK_BG  = LazyColor("DARK_BG")
PANEL_BG = LazyColor("PANEL_BG")
ROW_ALT  = LazyColor("ROW_ALT")
ACCENT   = LazyColor("ACCENT")
TEXT     = LazyColor("TEXT")
SUBTEXT  = LazyColor("SUBTEXT")
BORDER   = LazyColor("BORDER")
GREEN    = LazyColor("GREEN")
RED      = LazyColor("RED")
YELLOW   = LazyColor("YELLOW")
SEL_BG   = LazyColor("SEL_BG")
SEL_TEXT = LazyColor("SEL_TEXT")
