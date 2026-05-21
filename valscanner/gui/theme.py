from __future__ import annotations

ORG_NAME = "valscanner"
APP_NAME = "ValScanner"

PALETTE_KEYS = (
    "DARK_BG", "PANEL_BG", "ROW_ALT", "ACCENT",
    "TEXT", "SUBTEXT", "BORDER", "GREEN", "RED", "YELLOW", "SEL_BG", "SEL_TEXT",
)

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "DARK_BG":  "#1e1e2e",
        "PANEL_BG": "#2a2a3e",
        "ROW_ALT":  "#252535",
        "ACCENT":   "#7c6af7",
        "TEXT":     "#cdd6f4",
        "SUBTEXT":  "#a6adc8",
        "BORDER":   "#45475a",
        "GREEN":    "#a6e3a1",
        "RED":      "#f38ba8",
        "YELLOW":   "#f9e2af",
    },
    "light": {
        "DARK_BG":  "#f5f5f7",
        "PANEL_BG": "#ffffff",
        "ROW_ALT":  "#fafafa",
        "ACCENT":   "#7c6af7",
        "TEXT":     "#1d1d1f",
        "SUBTEXT":  "#6e6e73",
        "BORDER":   "#d2d2d7",
        "GREEN":    "#34a853",
        "RED":      "#d93025",
        "YELLOW":   "#f29900",
    },
    "high_contrast": {
        "DARK_BG":  "#000000",
        "PANEL_BG": "#1a1a1a",
        "ROW_ALT":  "#0d0d0d",
        "ACCENT":   "#00e5ff",
        "TEXT":     "#ffffff",
        "SUBTEXT":  "#e0e0e0",
        "BORDER":   "#888888",
        "GREEN":    "#00ff66",
        "RED":      "#ff5252",
        "YELLOW":   "#ffeb3b",
    },
}

THEME_LABELS: dict[str, str] = {
    "dark":          "Dark",
    "light":         "Light",
    "system":        "System",
    "high_contrast": "High Contrast",
}

DEFAULT_THEME = "dark"


def _hex9_to_rgba(h: str) -> str:
    """Convert CSS #RRGGBBAA to rgba(r,g,b,a) — works in all Qt stylesheet properties."""
    r, g, b, a = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16), int(h[7:9], 16)
    return f"rgba({r},{g},{b},{a/255:.3f})"


def _build_palette(base_name: str) -> dict[str, str]:
    """Build a full palette dict (including SEL_BG/SEL_TEXT) for a resolved theme name."""
    from PySide6.QtCore import QSettings
    s = QSettings(ORG_NAME, APP_NAME)
    palette = dict(THEMES.get(base_name, THEMES[DEFAULT_THEME]))
    accent = s.value("accentColor", "") or ""
    if accent and accent.startswith("#") and len(accent) in (4, 7, 9):
        palette["ACCENT"] = accent
    sel = s.value("selectionColor", "") or ""
    raw_sel = sel if (sel.startswith("#") and len(sel) == 9) else palette["ACCENT"] + "55"
    palette["SEL_BG"]   = _hex9_to_rgba(raw_sel)
    sel_text = s.value("selectionTextColor", "") or ""
    palette["SEL_TEXT"] = sel_text if (sel_text.startswith("#") and len(sel_text) in (4, 7)) else palette["TEXT"]
    return palette


def load_palette() -> dict[str, str]:
    """Return the active palette. Called from constants.py LazyColor on each access."""
    return Theme.instance().palette()


def _initial_mode(s) -> str:
    """Determine default mode for a user who has never explicitly set theme/mode."""
    if s.contains("windowGeometry") or s.contains("geometry"):
        return "dark"   # upgrading user — preserve current look
    return "system"     # fresh install — follow OS


_instance: "Theme | None" = None


class Theme:
    """Runtime theme singleton. Holds the current mode and emits changed signal."""

    def __init__(self) -> None:
        from PySide6.QtCore import QSettings
        s = QSettings(ORG_NAME, APP_NAME)
        if s.contains("theme/mode"):
            choice = s.value("theme/mode") or "dark"
        else:
            choice = _initial_mode(s)
        self._choice: str = choice
        self._resolved: str = self._resolve(choice)
        self._callbacks: list = []

    # ── singleton ──────────────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> "Theme":
        global _instance
        if _instance is None:
            _instance = cls()
        return _instance

    # ── public API ─────────────────────────────────────────────────────────

    def palette(self) -> dict[str, str]:
        return _build_palette(self._resolved)

    def current_mode(self) -> str:
        return self._choice

    def set(self, name: str) -> None:
        from PySide6.QtCore import QSettings
        self._choice   = name
        self._resolved = self._resolve(name)
        QSettings(ORG_NAME, APP_NAME).setValue("theme/mode", name)
        for cb in self._callbacks:
            cb()

    def on_changed(self, callback) -> None:
        """Register a zero-argument callable to be called when theme changes."""
        self._callbacks.append(callback)

    # ── helpers ────────────────────────────────────────────────────────────

    def _resolve(self, choice: str) -> str:
        if choice in ("dark", "light", "high_contrast"):
            return choice
        # "system" — try Qt 6.5+ colorScheme hint
        try:
            from PySide6.QtGui import QGuiApplication
            hints = QGuiApplication.styleHints()
            if hasattr(hints, "colorScheme"):
                from PySide6.QtCore import Qt
                scheme = hints.colorScheme()
                if hasattr(Qt, "ColorScheme"):
                    if scheme == Qt.ColorScheme.Dark:
                        return "dark"
                    if scheme == Qt.ColorScheme.Light:
                        return "light"
        except Exception:
            pass
        return "dark"
