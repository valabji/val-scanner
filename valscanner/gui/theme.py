from __future__ import annotations

ORG_NAME = "valscanner"
APP_NAME = "ValScanner"

PALETTE_KEYS = (
    "DARK_BG", "PANEL_BG", "ROW_ALT", "ACCENT",
    "TEXT", "SUBTEXT", "BORDER", "GREEN", "RED", "YELLOW", "SEL_BG", "SEL_TEXT",
    "DIVIDER2", "DIVIDER3", "BG2", "BG3",
    "BTN_HOVER", "BTN_PRESSED", "HOVER_BORDER", "SCROLLBAR_HOVER", "ORANGE",
)

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "DARK_BG":         "#0c0d10",
        "PANEL_BG":        "#111317",
        "ROW_ALT":         "#15181d",
        "ACCENT":          "#ffb547",
        "TEXT":            "#e8eaed",
        "SUBTEXT":         "#9aa0aa",
        "BORDER":          "#1f2329",
        "GREEN":           "#6dd58c",
        "RED":             "#ff7a85",
        "YELLOW":          "#ffd66b",
        "DIVIDER2":        "#272c34",
        "DIVIDER3":        "#343a44",
        "BG2":             "#15181d",
        "BG3":             "#1b1f25",
        "BTN_HOVER":       "#ffc96b",
        "BTN_PRESSED":     "#e0a035",
        "HOVER_BORDER":    "#3d4451",
        "SCROLLBAR_HOVER": "#434a57",
        "ORANGE":          "#ff9e4a",
    },
    "light": {
        "DARK_BG":         "#f4f4f6",
        "PANEL_BG":        "#ffffff",
        "ROW_ALT":         "#f9f9fb",
        "ACCENT":          "#d4830a",
        "TEXT":            "#1a1c1f",
        "SUBTEXT":         "#6b7079",
        "BORDER":          "#d8dbe0",
        "GREEN":           "#1e7e34",
        "RED":             "#c0392b",
        "YELLOW":          "#b8860b",
        "DIVIDER2":        "#e5e7eb",
        "DIVIDER3":        "#d1d5db",
        "BG2":             "#f0f1f4",
        "BG3":             "#e8eaed",
        "BTN_HOVER":       "#e89010",
        "BTN_PRESSED":     "#b86e08",
        "HOVER_BORDER":    "#adb2ba",
        "SCROLLBAR_HOVER": "#b8bcc5",
        "ORANGE":          "#e07028",
    },
    "high_contrast": {
        "DARK_BG":         "#000000",
        "PANEL_BG":        "#1a1a1a",
        "ROW_ALT":         "#0d0d0d",
        "ACCENT":          "#ffb547",
        "TEXT":            "#ffffff",
        "SUBTEXT":         "#e0e0e0",
        "BORDER":          "#888888",
        "GREEN":           "#00ff66",
        "RED":             "#ff5252",
        "YELLOW":          "#ffeb3b",
        "DIVIDER2":        "#444444",
        "DIVIDER3":        "#555555",
        "BG2":             "#111111",
        "BG3":             "#1a1a1a",
        "BTN_HOVER":       "#ffcc66",
        "BTN_PRESSED":     "#e0a000",
        "HOVER_BORDER":    "#aaaaaa",
        "SCROLLBAR_HOVER": "#bbbbbb",
        "ORANGE":          "#ff8800",
    },
    "catppuccin": {
        "DARK_BG":         "#1e1e2e",
        "PANEL_BG":        "#2a2a3e",
        "ROW_ALT":         "#252535",
        "ACCENT":          "#7c6af7",
        "TEXT":            "#cdd6f4",
        "SUBTEXT":         "#a6adc8",
        "BORDER":          "#45475a",
        "GREEN":           "#a6e3a1",
        "RED":             "#f38ba8",
        "YELLOW":          "#f9e2af",
        "DIVIDER2":        "#313244",
        "DIVIDER3":        "#45475a",
        "BG2":             "#252535",
        "BG3":             "#2e3040",
        "BTN_HOVER":       "#9d8fff",
        "BTN_PRESSED":     "#6a58d4",
        "HOVER_BORDER":    "#5a5a7a",
        "SCROLLBAR_HOVER": "#6a6a8a",
        "ORANGE":          "#fab387",
    },
}

THEME_LABELS: dict[str, str] = {
    "dark":          "Dark",
    "light":         "Light",
    "system":        "System",
    "high_contrast": "High Contrast",
    "catppuccin":    "Catppuccin",
}

DEFAULT_THEME = "catppuccin"


def _hex9_to_rgba(h: str) -> str:
    """Convert CSS #RRGGBBAA to rgba(r,g,b,a) — works in all Qt stylesheet properties."""
    r, g, b, a = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16), int(h[7:9], 16)
    return f"rgba({r},{g},{b},{a/255:.3f})"


def _build_palette(base_name: str) -> dict[str, str]:
    """Build a full palette dict (including SEL_BG/SEL_TEXT) for a resolved theme name."""
    from PySide6.QtCore import QSettings
    s = QSettings(ORG_NAME, APP_NAME)
    base = THEMES.get(base_name, THEMES[DEFAULT_THEME])
    # Ensure all PALETTE_KEYS are present (fill missing keys from dark theme as fallback)
    palette = {k: base.get(k, THEMES["dark"].get(k, "")) for k in PALETTE_KEYS}
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
        # Don't read QSettings here — QApplication may not exist yet (module imported
        # before main() creates it). _ensure_loaded() defers the read until first use.
        self._choice: str = DEFAULT_THEME
        self._resolved: str = DEFAULT_THEME
        self._callbacks: list = []
        self._settings_loaded: bool = False

    def _ensure_loaded(self) -> None:
        """Read persisted theme/mode from QSettings, but only once QApplication exists."""
        if self._settings_loaded:
            return
        try:
            from PySide6.QtWidgets import QApplication
            if QApplication.instance() is None:
                return
            from PySide6.QtCore import QSettings
            s = QSettings(ORG_NAME, APP_NAME)
            if s.contains("theme/mode"):
                choice = s.value("theme/mode") or DEFAULT_THEME
            else:
                choice = _initial_mode(s)
            self._choice   = choice
            self._resolved = self._resolve(choice)
            self._settings_loaded = True
        except Exception:
            pass

    # ── singleton ──────────────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> "Theme":
        global _instance
        if _instance is None:
            _instance = cls()
        return _instance

    # ── public API ─────────────────────────────────────────────────────────

    def palette(self) -> dict[str, str]:
        self._ensure_loaded()
        return _build_palette(self._resolved)

    def current_mode(self) -> str:
        self._ensure_loaded()
        return self._choice

    def set(self, name: str) -> None:
        from PySide6.QtCore import QSettings
        self._choice          = name
        self._resolved        = self._resolve(name)
        self._settings_loaded = True  # explicit set always wins
        QSettings(ORG_NAME, APP_NAME).setValue("theme/mode", name)
        for cb in list(self._callbacks):
            try:
                cb()
            except Exception:
                import traceback
                traceback.print_exc()

    def on_changed(self, callback) -> None:
        """Register a zero-argument callable to be called when theme changes."""
        self._callbacks.append(callback)

    # ── helpers ────────────────────────────────────────────────────────────

    def _resolve(self, choice: str) -> str:
        if choice in ("dark", "light", "high_contrast", "catppuccin"):
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
