from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSettings, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QColorDialog,
    QDialogButtonBox, QFileDialog, QFrame,
)

from .constants import DARK_BG, PANEL_BG, ACCENT, TEXT, SUBTEXT, BORDER, SEL_TEXT
from .theme import THEMES, THEME_LABELS, DEFAULT_THEME, ORG_NAME, APP_NAME, _hex9_to_rgba


SETTINGS_DEFAULTS = {
    "theme":                 DEFAULT_THEME,
    "accentColor":           "",
    "selectionColor":        "",
    "selectionTextColor":    "",
    "defaultDbPath":         "file_index.db",
    "computeHashesByDefault": False,
    "autoStartScan":         True,
    "restoreWindowState":    True,
    "openLastDbOnStartup":   False,
    "showConsoleOnStartup":  True,
    # scan options — persisted silently, no UI needed here
    "scanStoreThumbnails":   False,
    "scanThumbSize":         128,
    "scanThumbQuality":      75,
    "scanStoreSamples":      False,
    "scanSampleDuration":    5,
    "scanSkipHiddenDirs":  True,
    "scanSkipVcs":         False,
    "scanSkipSystem":      False,
    "scanSkipCaches":      False,
    "scanSkipHiddenFiles": False,
    "scanSkipBinaries":    False,
    "scanSkipTemp":        False,
    "scanSkipLogs":        False,
}


def settings() -> QSettings:
    return QSettings(ORG_NAME, APP_NAME)


def get(key: str):
    s   = settings()
    val = s.value(key, SETTINGS_DEFAULTS.get(key))
    if isinstance(SETTINGS_DEFAULTS.get(key), bool):
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)
    return val


class PreferencesDialog(QDialog):
    settings_changed = Signal(dict)   # emitted on Apply / OK, dict of changed keys

    def __init__(self, parent=None):
        from .theme import Theme
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(520)
        self._original_theme = Theme.instance().current_mode()
        self._before = {k: get(k) for k in SETTINGS_DEFAULTS}
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        self.setStyleSheet(f"""
            QDialog {{ background: {DARK_BG}; color: {TEXT}; }}
            QLabel {{ color: {TEXT}; font-size: 12px; }}
            QLineEdit, QComboBox {{
                background: {PANEL_BG}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 6px;
                padding: 4px 8px; font-size: 12px;
            }}
            QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
            QCheckBox {{ color: {TEXT}; spacing: 6px; font-size: 12px; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px; border: 1px solid {BORDER};
                border-radius: 4px; background: {PANEL_BG};
            }}
            QCheckBox::indicator:checked {{
                background: {ACCENT}; border-color: {ACCENT};
            }}
            QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; }}
            QTabBar::tab {{
                background: transparent; color: {SUBTEXT}; padding: 6px 16px;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                color: {TEXT}; border-bottom: 2px solid {ACCENT}; font-weight: bold;
            }}
            QPushButton {{
                background: transparent; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 6px;
                padding: 5px 14px; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_appearance_tab(), "Appearance")
        self.tabs.addTab(self._build_behavior_tab(),   "Behavior")
        lay.addWidget(self.tabs, 1)

        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._restore_defaults)
        lay.addWidget(btns)

    # ── Appearance tab ────────────────────────────────────────────────────────

    def _build_appearance_tab(self) -> QWidget:
        w   = QWidget()
        f   = QFormLayout(w)
        f.setContentsMargins(14, 14, 14, 14)
        f.setSpacing(10)

        self.theme_combo = QComboBox()
        for key in THEMES:
            self.theme_combo.addItem(THEME_LABELS.get(key, key), userData=key)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_live)
        f.addRow("Theme", self.theme_combo)

        accent_row = QHBoxLayout()
        self.accent_swatch = QFrame()
        self.accent_swatch.setFixedSize(24, 24)
        self.accent_swatch.setStyleSheet(
            f"background: {ACCENT}; border: 1px solid {BORDER}; border-radius: 6px;"
        )
        accent_row.addWidget(self.accent_swatch)
        self.accent_value = QLabel(ACCENT)
        self.accent_value.setStyleSheet(f"color: {SUBTEXT}; font-family: monospace;")
        accent_row.addWidget(self.accent_value)
        accent_row.addStretch()
        pick = QPushButton("Pick…")
        pick.clicked.connect(self._pick_accent)
        accent_row.addWidget(pick)
        reset = QPushButton("Reset")
        reset.clicked.connect(self._reset_accent)
        accent_row.addWidget(reset)
        accent_box = QWidget()
        accent_box.setLayout(accent_row)
        f.addRow("Accent color", accent_box)

        sel_row = QHBoxLayout()
        self.sel_swatch = QFrame()
        self.sel_swatch.setFixedSize(24, 24)
        self.sel_swatch.setStyleSheet(
            f"background: {ACCENT:55}; border: 1px solid {BORDER}; border-radius: 6px;"
        )
        sel_row.addWidget(self.sel_swatch)
        self.sel_value = QLabel(f"{ACCENT:55}")
        self.sel_value.setStyleSheet(f"color: {SUBTEXT}; font-family: monospace;")
        sel_row.addWidget(self.sel_value)
        sel_row.addStretch()
        pick_sel = QPushButton("Pick…")
        pick_sel.clicked.connect(self._pick_sel)
        sel_row.addWidget(pick_sel)
        reset_sel = QPushButton("Reset")
        reset_sel.clicked.connect(self._reset_sel)
        sel_row.addWidget(reset_sel)
        sel_box = QWidget(); sel_box.setLayout(sel_row)
        f.addRow("Selection highlight", sel_box)

        sel_text_row = QHBoxLayout()
        self.sel_text_swatch = QFrame()
        self.sel_text_swatch.setFixedSize(24, 24)
        self.sel_text_swatch.setStyleSheet(
            f"background: {SEL_TEXT}; border: 1px solid {BORDER}; border-radius: 6px;"
        )
        sel_text_row.addWidget(self.sel_text_swatch)
        self.sel_text_value = QLabel(SEL_TEXT)
        self.sel_text_value.setStyleSheet(f"color: {SUBTEXT}; font-family: monospace;")
        sel_text_row.addWidget(self.sel_text_value)
        sel_text_row.addStretch()
        pick_sel_text = QPushButton("Pick…")
        pick_sel_text.clicked.connect(self._pick_sel_text)
        sel_text_row.addWidget(pick_sel_text)
        reset_sel_text = QPushButton("Reset")
        reset_sel_text.clicked.connect(self._reset_sel_text)
        sel_text_row.addWidget(reset_sel_text)
        sel_text_box = QWidget(); sel_text_box.setLayout(sel_text_row)
        f.addRow("Selection text", sel_text_box)

        note = QLabel("Theme applies immediately. Accent and selection take effect after OK.")
        note.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px; font-style: italic;")
        f.addRow("", note)
        return w

    def _pick_accent(self) -> None:
        current = QColor(self._accent_choice() or ACCENT)
        chosen  = QColorDialog.getColor(current, self, "Pick accent color")
        if chosen.isValid():
            hex_ = chosen.name()
            self.accent_value.setText(hex_)
            self.accent_swatch.setStyleSheet(
                f"background: {hex_}; border: 1px solid {BORDER}; border-radius: 6px;"
            )

    def _reset_accent(self) -> None:
        self.accent_value.setText("(theme default)")
        theme_key = self.theme_combo.currentData() or DEFAULT_THEME
        default   = THEMES[theme_key]["ACCENT"]
        self.accent_swatch.setStyleSheet(
            f"background: {default}; border: 1px solid {BORDER}; border-radius: 6px;"
        )

    def _accent_choice(self) -> str:
        text = self.accent_value.text().strip()
        return text if text.startswith("#") else ""

    def _pick_sel(self) -> None:
        current_hex = self._sel_choice()
        current = QColor(current_hex[:7]) if current_hex else QColor(ACCENT)
        if current_hex and len(current_hex) == 9:
            current.setAlpha(int(current_hex[7:], 16))
        chosen = QColorDialog.getColor(
            current, self, "Pick selection highlight",
            QColorDialog.ShowAlphaChannel,
        )
        if chosen.isValid():
            hex_ = chosen.name() + format(chosen.alpha(), "02x")
            self.sel_value.setText(hex_)
            self.sel_swatch.setStyleSheet(
                f"background: {_hex9_to_rgba(hex_)}; border: 1px solid {BORDER}; border-radius: 6px;"
            )

    def _reset_sel(self) -> None:
        theme_key    = self.theme_combo.currentData() or DEFAULT_THEME
        default_rgba = _hex9_to_rgba(THEMES[theme_key]["ACCENT"] + "55")
        self.sel_value.setText("(theme default)")
        self.sel_swatch.setStyleSheet(
            f"background: {default_rgba}; border: 1px solid {BORDER}; border-radius: 6px;"
        )

    def _sel_choice(self) -> str:
        text = self.sel_value.text().strip()
        return text if (text.startswith("#") and len(text) == 9) else ""

    def _pick_sel_text(self) -> None:
        current = QColor(self._sel_text_choice() or SEL_TEXT)
        chosen  = QColorDialog.getColor(current, self, "Pick selection text color")
        if chosen.isValid():
            hex_ = chosen.name()
            self.sel_text_value.setText(hex_)
            self.sel_text_swatch.setStyleSheet(
                f"background: {hex_}; border: 1px solid {BORDER}; border-radius: 6px;"
            )

    def _reset_sel_text(self) -> None:
        theme_key = self.theme_combo.currentData() or DEFAULT_THEME
        default   = THEMES[theme_key]["TEXT"]
        self.sel_text_value.setText("(theme default)")
        self.sel_text_swatch.setStyleSheet(
            f"background: {default}; border: 1px solid {BORDER}; border-radius: 6px;"
        )

    def _sel_text_choice(self) -> str:
        text = self.sel_text_value.text().strip()
        return text if (text.startswith("#") and len(text) in (4, 7)) else ""

    # ── Behavior tab ──────────────────────────────────────────────────────────

    def _build_behavior_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(14, 14, 14, 14)
        f.setSpacing(10)

        db_row = QHBoxLayout()
        self.db_edit = QLineEdit()
        self.db_edit.setPlaceholderText("file_index.db")
        db_row.addWidget(self.db_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_default_db)
        db_row.addWidget(browse)
        box = QWidget(); box.setLayout(db_row)
        f.addRow("Default database", box)

        self.chk_hashes     = QCheckBox("Compute SHA-256 hashes by default when scanning")
        self.chk_auto_scan  = QCheckBox("Start scan automatically when a folder is selected")
        self.chk_restore    = QCheckBox("Restore window size & layout on launch")
        self.chk_reopen     = QCheckBox("Reopen last database on launch")
        self.chk_console    = QCheckBox("Show console panel on launch")
        f.addRow("", self.chk_hashes)
        f.addRow("", self.chk_auto_scan)
        f.addRow("", self.chk_restore)
        f.addRow("", self.chk_reopen)
        f.addRow("", self.chk_console)
        return w

    def _browse_default_db(self) -> None:
        start   = self.db_edit.text().strip() or str(Path.home() / "file_index.db")
        path, _ = QFileDialog.getSaveFileName(
            self, "Default database location", start,
            "SQLite databases (*.db);;All files (*)",
        )
        if path:
            if not path.endswith(".db"):
                path += ".db"
            self.db_edit.setText(path)

    # ── Load / save / defaults ────────────────────────────────────────────────

    def _load_values(self) -> None:
        from .theme import Theme
        theme = Theme.instance().current_mode()
        idx   = self.theme_combo.findData(theme)
        if idx >= 0:
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(idx)
            self.theme_combo.blockSignals(False)

        accent = get("accentColor") or ""
        if accent:
            self.accent_value.setText(accent)
            self.accent_swatch.setStyleSheet(
                f"background: {accent}; border: 1px solid {BORDER}; border-radius: 6px;"
            )
        else:
            self._reset_accent()

        sel = get("selectionColor") or ""
        if sel and sel.startswith("#") and len(sel) == 9:
            self.sel_value.setText(sel)
            self.sel_swatch.setStyleSheet(
                f"background: {_hex9_to_rgba(sel)}; border: 1px solid {BORDER}; border-radius: 6px;"
            )
        else:
            self._reset_sel()

        sel_text = get("selectionTextColor") or ""
        if sel_text and sel_text.startswith("#") and len(sel_text) in (4, 7):
            self.sel_text_value.setText(sel_text)
            self.sel_text_swatch.setStyleSheet(
                f"background: {sel_text}; border: 1px solid {BORDER}; border-radius: 6px;"
            )
        else:
            self._reset_sel_text()

        self.db_edit.setText(get("defaultDbPath") or "file_index.db")
        self.chk_hashes.setChecked(bool(get("computeHashesByDefault")))
        self.chk_auto_scan.setChecked(bool(get("autoStartScan")))
        self.chk_restore.setChecked(bool(get("restoreWindowState")))
        self.chk_reopen.setChecked(bool(get("openLastDbOnStartup")))
        self.chk_console.setChecked(bool(get("showConsoleOnStartup")))

    def _on_theme_live(self, _idx: int) -> None:
        from .theme import Theme
        key = self.theme_combo.currentData() or DEFAULT_THEME
        Theme.instance().set(key)
        # Refresh swatch defaults to match the newly active theme
        theme_data = THEMES.get(key, THEMES[DEFAULT_THEME])
        if not self.accent_value.text().strip().startswith("#"):
            self.accent_swatch.setStyleSheet(
                f"background: {theme_data['ACCENT']}; border: 1px solid {BORDER}; border-radius: 6px;"
            )
        if not self.sel_value.text().strip().startswith("#"):
            self.sel_swatch.setStyleSheet(
                f"background: {_hex9_to_rgba(theme_data['ACCENT'] + '55')};"
                f"border: 1px solid {BORDER}; border-radius: 6px;"
            )
        if not self.sel_text_value.text().strip().startswith("#"):
            self.sel_text_swatch.setStyleSheet(
                f"background: {theme_data['TEXT']}; border: 1px solid {BORDER}; border-radius: 6px;"
            )

    def reject(self) -> None:
        from .theme import Theme
        Theme.instance().set(self._original_theme)
        super().reject()

    def _restore_defaults(self) -> None:
        s = settings()
        for k in SETTINGS_DEFAULTS:
            s.remove(k)
        self._load_values()

    def _on_accept(self) -> None:
        s = settings()
        # theme is already persisted by Theme.instance().set() via the live combo handler
        accent = self._accent_choice()
        s.setValue("accentColor",           accent)
        sel = self._sel_choice()
        s.setValue("selectionColor",        sel)
        sel_text = self._sel_text_choice()
        s.setValue("selectionTextColor",    sel_text)
        s.setValue("defaultDbPath",         self.db_edit.text().strip() or "file_index.db")
        s.setValue("computeHashesByDefault", self.chk_hashes.isChecked())
        s.setValue("autoStartScan",         self.chk_auto_scan.isChecked())
        s.setValue("restoreWindowState",    self.chk_restore.isChecked())
        s.setValue("openLastDbOnStartup",   self.chk_reopen.isChecked())
        s.setValue("showConsoleOnStartup",  self.chk_console.isChecked())

        changed = {k: get(k) for k in SETTINGS_DEFAULTS if get(k) != self._before.get(k)}
        self.settings_changed.emit(changed)
        self.accept()
