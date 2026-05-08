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

_p = load_palette()
DARK_BG  = HexColor(_p["DARK_BG"])
PANEL_BG = HexColor(_p["PANEL_BG"])
ROW_ALT  = HexColor(_p["ROW_ALT"])
ACCENT   = HexColor(_p["ACCENT"])
TEXT     = HexColor(_p["TEXT"])
SUBTEXT  = HexColor(_p["SUBTEXT"])
BORDER   = HexColor(_p["BORDER"])
GREEN    = HexColor(_p["GREEN"])
RED      = HexColor(_p["RED"])
YELLOW   = HexColor(_p["YELLOW"])
# SEL_BG is already rgba() — leave it as plain str
SEL_BG   = _p["SEL_BG"]
SEL_TEXT = HexColor(_p["SEL_TEXT"])
