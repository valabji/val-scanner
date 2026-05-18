#!/usr/bin/env python3
from __future__ import annotations
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox,
    QComboBox, QProgressBar, QStatusBar,
    QFileDialog, QTableView, QListView,
    QHeaderView, QAbstractItemView,
    QFrame, QScrollArea,
    QTabWidget,
    QMessageBox, QMenu, QDialog,
    QStackedWidget, QButtonGroup,
    QDockWidget,
)

from .constants import (
    CATEGORY_COLORS,
    DARK_BG, PANEL_BG, ROW_ALT, ACCENT, TEXT, SUBTEXT, BORDER, GREEN, RED, YELLOW, SEL_BG, SEL_TEXT,
)
from .models import FileTableModel, FileIconModel, _THUMB_CACHE, COL_IDX
from .delegates import FileCardDelegate, FileRowDelegate
from .workers import ScanWorker, LazyLoadWorker, PAGE_SIZE
from .dialogs import ScanOptionsDialog, ViewFiltersDialog
from .panels.detail import DetailPanel
from .panels.folders import FolderPanel
from .panels.similar import SimilarFoldersPanel
from .panels.scans import ScansPanel
from .panels.console import ConsolePanel, _StderrBridge
from .panels.process import ProcessPanel, ProcessRegistry
from .preferences import PreferencesDialog, get as pref_get, settings as pref_settings
from ..core.export import export_csv, export_json
from ..core.db import list_scans
from ..core.schema import human_size
from ..core.scanner import _SYSTEM_DIRS, _CACHE_DIRS, _VCS_DIRS, _BINARY_EXTS, _TEMP_EXTS, _LOG_EXTS


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ValScanner")
        self.resize(1440, 860)
        self._db_path                = ""
        self._worker                 = None
        self._all_rows: list         = []
        self._active_folder_filter   = ""
        self._folder_filter_recursive = False
        self._active_scan_id         = 0
        self._scan_start             = 0.0
        self._elapsed_timer          = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._scan_options: dict     = {}
        self._view_filters: dict     = {}
        self._group_by: str          = ""
        self._view_filters_dlg: ViewFiltersDialog | None = None
        self._filtered_rows: list    = []
        self._lazy_worker: LazyLoadWorker | None = None
        self._total_row_count        = 0
        self._loaded_offset          = 0

        self._apply_palette()
        self._build_menu()
        self._build_ui()

        self.setAcceptDrops(True)
        self._install_shortcuts()
        self._apply_startup_settings()

    def _apply_palette(self) -> None:
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: {DARK_BG}; color: {TEXT};
                font-family: 'SF Pro Display', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            }}
            QSplitter::handle {{ background: {BORDER}; width: 1px; height: 1px; }}
            QLineEdit {{
                background: {DARK_BG}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 7px; padding: 5px 11px; font-size: 12px;
                selection-background-color: {ACCENT};
            }}
            QLineEdit:focus {{ border-color: {ACCENT}; background: {PANEL_BG}; }}
            QLineEdit:hover {{ border-color: #5a5a7a; }}
            QComboBox {{
                background: {DARK_BG}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 7px; padding: 5px 10px; font-size: 12px; min-width: 80px;
            }}
            QComboBox:hover {{ border-color: #5a5a7a; }}
            QComboBox:focus {{ border-color: {ACCENT}; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox::down-arrow {{ image: none; }}
            QComboBox QAbstractItemView {{
                background: {PANEL_BG}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 6px; selection-background-color: {ACCENT}; padding: 4px;
            }}
            QCheckBox {{ color: {SUBTEXT}; spacing: 6px; font-size: 12px; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px; border: 1px solid {BORDER};
                border-radius: 4px; background: {DARK_BG};
            }}
            QCheckBox::indicator:hover   {{ border-color: {ACCENT}; }}
            QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
            QProgressBar {{ background: {PANEL_BG}; border: none; border-radius: 3px; }}
            QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
            QScrollBar:vertical   {{ background: transparent; width: 6px; margin: 2px; }}
            QScrollBar:horizontal {{ background: transparent; height: 6px; margin: 2px; }}
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
                background: {BORDER}; border-radius: 3px; min-height: 20px; min-width: 20px;
            }}
            QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
                background: #6a6a8a;
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{
                background: transparent; color: {SUBTEXT}; padding: 8px 20px;
                font-size: 12px; border-bottom: 2px solid transparent; margin-right: 2px;
            }}
            QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; font-weight: bold; }}
            QTabBar::tab:hover:!selected {{ color: {TEXT}; }}
            QToolTip {{
                background: {PANEL_BG}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 5px; padding: 4px 8px; font-size: 11px;
            }}
            QMenu {{
                background: {PANEL_BG}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 8px; padding: 4px;
            }}
            QMenu::item {{ padding: 7px 20px; border-radius: 5px; }}
            QMenu::item:selected {{ background: {ACCENT}; }}
            QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
            QStatusBar {{ background: {PANEL_BG}; color: {SUBTEXT}; font-size: 11px; }}
            QStatusBar::item {{ border: none; }}
        """)

    # ── Drag & drop ───────────────────────────────────────────────────────────

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls() and any(
            u.isLocalFile() for u in ev.mimeData().urls()
        ):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        urls = [u for u in ev.mimeData().urls() if u.isLocalFile()]
        if not urls:
            return
        path = urls[0].toLocalFile()
        p    = Path(path)
        if p.is_dir():
            self.path_edit.setText(str(p))
            if not self.db_edit.text().strip() or self.db_edit.text() == "file_index.db":
                self.db_edit.setText(str(p.parent / "file_index.db"))
            ev.acceptProposedAction()
            if pref_get("autoStartScan"):
                self._start_scan()
        elif p.is_file() and p.suffix.lower() == ".db":
            self.db_edit.setText(str(p))
            self._db_path = str(p)
            self._load_db(str(p))
            ev.acceptProposedAction()
        else:
            self._set_status(f"⚠ Drop a folder to scan or a .db file to open (got: {p.name})")

    # ── Shortcuts ─────────────────────────────────────────────────────────────

    def _install_shortcuts(self) -> None:
        def _mk(seq: str, slot):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(slot)
            return sc

        _mk("/",              self._focus_search)
        _mk("Ctrl+F",         self._focus_search)
        _mk("Ctrl+Shift+R",   self._reveal_active_file)
        _mk("Ctrl+Shift+C",   self._copy_active_path)

        for v in (self.table, self.grid_view, self.list_view):
            for seq in ("Return", "Enter"):
                sc = QShortcut(QKeySequence(seq), v)
                sc.setContext(Qt.WidgetShortcut)
                sc.activated.connect(self._open_active_file)

    def _focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _open_active_file(self) -> None:
        row = self._active_row()
        if row:
            self.detail._current_path = row[0]
            self.detail._open_file()

    def _reveal_active_file(self) -> None:
        row = self._active_row()
        if row:
            self._reveal(str(Path(row[0]).parent))

    def _copy_active_path(self) -> None:
        row = self._active_row()
        if row:
            QApplication.clipboard().setText(row[0])
            self._set_status(f"Copied path: {row[0]}")

    def _active_row(self):
        if self._view_stack.currentIndex() == 0:
            idx = self.table.selectionModel().currentIndex()
            if idx.isValid() and self.table_model._rows:
                return self.table_model._rows[idx.row()]
        else:
            view = self.grid_view if self._view_stack.currentIndex() == 1 else self.list_view
            idx  = view.selectionModel().currentIndex()
            if idx.isValid():
                return self.icon_model.data(idx, Qt.UserRole)
        return None

    def _build_menu(self) -> None:
        mb = self.menuBar()
        mb.setStyleSheet(f"""
            QMenuBar {{
                background: {PANEL_BG}; color: {SUBTEXT};
                border-bottom: 1px solid {BORDER}; padding: 2px 8px; font-size: 12px;
            }}
            QMenuBar::item {{ background: transparent; padding: 4px 10px; border-radius: 5px; }}
            QMenuBar::item:selected {{ background: {DARK_BG}; color: {TEXT}; }}
        """)

        fm     = mb.addMenu("File")
        a_open = QAction("Open Database…",  self, shortcut="Ctrl+O")
        a_scan = QAction("Scan Folder…",    self, shortcut="Ctrl+Shift+S")
        a_csv  = QAction("Export CSV…",     self, shortcut="Ctrl+E")
        a_json = QAction("Export JSON…",    self, shortcut="Ctrl+Shift+E")
        a_open.triggered.connect(self._open_db)
        a_scan.triggered.connect(self._start_scan)
        a_csv.triggered.connect(self._export_csv)
        a_json.triggered.connect(self._export_json)
        fm.addAction(a_open); fm.addAction(a_scan)
        self._recent_menu = fm.addMenu("Open Recent")
        self._rebuild_recent_menu()
        fm.addSeparator()
        fm.addAction(a_csv);  fm.addAction(a_json)
        fm.addSeparator()
        a_pref = QAction("Preferences…", self, shortcut="Ctrl+,")
        a_pref.triggered.connect(self._open_preferences)
        fm.addAction(a_pref)

        vm        = mb.addMenu("View")
        a_expand  = QAction("Expand All Folders",   self, shortcut="Ctrl+]")
        a_collapse = QAction("Collapse All Folders", self, shortcut="Ctrl+[")
        a_clear   = QAction("Clear Filters",         self, shortcut="Escape")
        a_expand.triggered.connect(lambda: self.folder_panel.tree.expandAll())
        a_collapse.triggered.connect(lambda: self.folder_panel.tree.collapseAll())
        a_clear.triggered.connect(self._clear_filters)
        vm.addAction(a_expand); vm.addAction(a_collapse)
        vm.addSeparator(); vm.addAction(a_clear)
        self._view_menu = vm

    # ── Recent databases ──────────────────────────────────────────────────────

    _RECENT_KEY = "recentDatabases"
    _RECENT_MAX = 5

    def _recent_paths(self) -> list[str]:
        raw = pref_settings().value(self._RECENT_KEY, [])
        if isinstance(raw, str):
            raw = [raw]
        return [p for p in (raw or []) if p and Path(p).exists()][: self._RECENT_MAX]

    def _push_recent(self, path: str) -> None:
        path  = str(Path(path).resolve())
        items = [p for p in self._recent_paths() if Path(p).resolve() != Path(path)]
        items.insert(0, path)
        pref_settings().setValue(self._RECENT_KEY, items[: self._RECENT_MAX])
        self._rebuild_recent_menu()
        if hasattr(self, "_recents_strip"):
            self._refresh_recents_strip()

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        paths = self._recent_paths()
        if not paths:
            a = self._recent_menu.addAction("(none)")
            a.setEnabled(False)
            return
        for p in paths:
            act = self._recent_menu.addAction(Path(p).name)
            act.setToolTip(p)
            act.triggered.connect(lambda _c=False, path=p: self._open_recent(path))
        self._recent_menu.addSeparator()
        clear = self._recent_menu.addAction("Clear Recent")
        clear.triggered.connect(self._clear_recent)

    def _open_recent(self, path: str) -> None:
        if not Path(path).exists():
            QMessageBox.warning(self, "Not found", f"File no longer exists:\n{path}")
            self._rebuild_recent_menu()
            return
        self.db_edit.setText(path)
        self._db_path = path
        self._load_db(path)

    def _clear_recent(self) -> None:
        pref_settings().setValue(self._RECENT_KEY, [])
        self._rebuild_recent_menu()
        if hasattr(self, "_recents_strip"):
            self._refresh_recents_strip()

    # ── Preferences ───────────────────────────────────────────────────────────

    def _open_preferences(self) -> None:
        dlg = PreferencesDialog(self)
        dlg.settings_changed.connect(self._on_settings_changed)
        dlg.exec()

    def _on_settings_changed(self, changed: dict) -> None:
        if "defaultDbPath" in changed:
            if not self._db_path:
                self.db_edit.setText(changed["defaultDbPath"] or "file_index.db")
        if "computeHashesByDefault" in changed:
            self.hash_chk.setChecked(bool(changed["computeHashesByDefault"]))
        if "showConsoleOnStartup" in changed and hasattr(self, "_main_vsplit"):
            self._apply_console_visibility(bool(changed["showConsoleOnStartup"]))
        if "theme" in changed or "accentColor" in changed or "selectionColor" in changed or "selectionTextColor" in changed:
            self._set_status("⚠  Theme change will take effect after restart.")

    def _apply_console_visibility(self, visible: bool) -> None:
        self._set_console_visible(visible)

    def _add_panel_toggles(self) -> None:
        vm = self._view_menu
        vm.addSeparator()
        s           = pref_settings()
        folder_vis  = s.value("panelFolderVisible",    True,                                   type=bool)
        detail_vis  = s.value("panelDetailVisible",    True,                                   type=bool)
        console_vis = s.value("panelConsoleVisible",   bool(pref_get("showConsoleOnStartup")),  type=bool)
        filter_vis  = s.value("panelFilterBarVisible", True,                                   type=bool)
        stats_vis   = s.value("panelStatsBarVisible",  True,                                   type=bool)
        process_vis = s.value("panelProcessVisible",   False,                                  type=bool)

        self._act_folder_panel = QAction("Folder Panel", self, checkable=True, checked=folder_vis)
        self._act_detail_panel = QAction("Detail Panel", self, checkable=True, checked=detail_vis)
        self._act_console      = QAction("Console",      self, checkable=True, checked=console_vis)
        self._act_filterbar    = QAction("Filter Bar",   self, checkable=True, checked=filter_vis)
        self._act_statsbar     = QAction("Stats Bar",    self, checkable=True, checked=stats_vis)
        self._act_process_dock = QAction("Process Monitor", self, checkable=True, checked=process_vis)

        self._act_folder_panel.triggered.connect(self._set_folder_panel_visible)
        self._act_detail_panel.triggered.connect(self._set_detail_panel_visible)
        self._act_console.triggered.connect(self._set_console_visible)
        self._act_filterbar.triggered.connect(self._toggle_filterbar)
        self._act_statsbar.triggered.connect(self._toggle_statsbar)
        self._act_process_dock.triggered.connect(self._set_process_dock_visible)
        self._process_dock.visibilityChanged.connect(
            lambda visible: self._act_process_dock.setChecked(visible)
        )

        vm.addAction(self._act_folder_panel)
        vm.addAction(self._act_detail_panel)
        vm.addAction(self._act_console)
        vm.addAction(self._act_filterbar)
        vm.addAction(self._act_statsbar)
        vm.addAction(self._act_process_dock)

    _DEFAULT_FOLDER_WIDTH = 220
    _DEFAULT_DETAIL_WIDTH = 280

    def _set_folder_panel_visible(self, visible: bool) -> None:
        if visible:
            self.folder_panel.setVisible(True)
            sizes = list(self.splitter.sizes())
            if sizes[0] == 0:
                sizes[0] = getattr(self, "_saved_folder_width", self._DEFAULT_FOLDER_WIDTH)
                self.splitter.setSizes(sizes)
        else:
            sizes = list(self.splitter.sizes())
            if sizes[0] > 0:
                self._saved_folder_width = sizes[0]
            self.folder_panel.setVisible(False)
        if hasattr(self, "_act_folder_panel"):
            self._act_folder_panel.setChecked(visible)
        pref_settings().setValue("panelFolderVisible", visible)

    def _set_detail_panel_visible(self, visible: bool) -> None:
        if visible:
            self.detail.setVisible(True)
            sizes = list(self.splitter.sizes())
            if sizes[2] == 0:
                sizes[2] = getattr(self, "_saved_detail_width", self._DEFAULT_DETAIL_WIDTH)
                self.splitter.setSizes(sizes)
        else:
            sizes = list(self.splitter.sizes())
            if sizes[2] > 0:
                self._saved_detail_width = sizes[2]
            self.detail.setVisible(False)
        if hasattr(self, "_act_detail_panel"):
            self._act_detail_panel.setChecked(visible)
        pref_settings().setValue("panelDetailVisible", visible)

    def _set_console_visible(self, visible: bool) -> None:
        sizes = list(self._main_vsplit.sizes())
        total = sum(sizes) or 800
        if visible:
            h = getattr(self, "_saved_console_height", int(total * 0.18))
            h = max(h, 60)
            self._main_vsplit.setSizes([total - h, h])
        else:
            if sizes[1] > 0:
                self._saved_console_height = sizes[1]
            self._main_vsplit.setSizes([total, 0])
        if hasattr(self, "_act_console"):
            self._act_console.setChecked(visible)
        pref_settings().setValue("panelConsoleVisible", visible)

    def _set_process_dock_visible(self, visible: bool) -> None:
        self._process_dock.setVisible(visible)
        if hasattr(self, "_act_process_dock"):
            self._act_process_dock.setChecked(visible)
        pref_settings().setValue("panelProcessVisible", visible)

    def _toggle_filterbar(self, visible: bool) -> None:
        self._filterbar.setVisible(visible)
        if hasattr(self, "_act_filterbar"):
            self._act_filterbar.setChecked(visible)
        pref_settings().setValue("panelFilterBarVisible", visible)

    def _toggle_statsbar(self, visible: bool) -> None:
        self._statsbar.setVisible(visible)
        if hasattr(self, "_act_statsbar"):
            self._act_statsbar.setChecked(visible)
        pref_settings().setValue("panelStatsBarVisible", visible)

    def _apply_startup_settings(self) -> None:
        default_db = pref_get("defaultDbPath") or "file_index.db"
        self.db_edit.setText(default_db)
        self.hash_chk.setChecked(bool(pref_get("computeHashesByDefault")))

        self._scan_options = {
            "store_thumbnails": bool(pref_get("scanStoreThumbnails")),
            "thumb_size":       int(pref_get("scanThumbSize") or 128),
            "thumb_quality":    int(pref_get("scanThumbQuality") or 75),
            "store_samples":    bool(pref_get("scanStoreSamples")),
            "sample_duration":  int(pref_get("scanSampleDuration") or 5),
            "skip_hidden_dirs":  bool(pref_get("scanSkipHiddenDirs")),
            "skip_vcs":          bool(pref_get("scanSkipVcs")),
            "skip_system":       bool(pref_get("scanSkipSystem")),
            "skip_caches":       bool(pref_get("scanSkipCaches")),
            "skip_hidden_files": bool(pref_get("scanSkipHiddenFiles")),
            "skip_binaries":     bool(pref_get("scanSkipBinaries")),
            "skip_temp":         bool(pref_get("scanSkipTemp")),
            "skip_logs":         bool(pref_get("scanSkipLogs")),
        }
        self._update_options_btn_label()

        if pref_get("restoreWindowState"):
            s = pref_settings()
            geo   = s.value("windowGeometry")
            state = s.value("splitterState")
            vstate = s.value("vsplitterState")
            if geo:
                self.restoreGeometry(geo)
            if state and hasattr(self, "splitter"):
                self.splitter.restoreState(state)
            if vstate and hasattr(self, "_main_vsplit"):
                self._main_vsplit.restoreState(vstate)

        _ps = pref_settings()
        self._set_console_visible(_ps.value("panelConsoleVisible", bool(pref_get("showConsoleOnStartup")), type=bool))
        self._set_folder_panel_visible(_ps.value("panelFolderVisible", True, type=bool))
        self._set_detail_panel_visible(_ps.value("panelDetailVisible", True, type=bool))
        self._toggle_filterbar(_ps.value("panelFilterBarVisible", True, type=bool))
        self._toggle_statsbar(_ps.value("panelStatsBarVisible", True, type=bool))

        if pref_get("openLastDbOnStartup"):
            recents = self._recent_paths()
            if recents:
                from PySide6.QtCore import QTimer as _T
                _T.singleShot(0, lambda: self._open_recent(recents[0]))

    def closeEvent(self, ev) -> None:
        if pref_get("restoreWindowState"):
            s = pref_settings()
            s.setValue("windowGeometry", self.saveGeometry())
            if hasattr(self, "splitter"):
                s.setValue("splitterState", self.splitter.saveState())
            if hasattr(self, "_main_vsplit"):
                s.setValue("vsplitterState", self._main_vsplit.saveState())
        _ps = pref_settings()
        _ps.setValue("panelFolderVisible",    self.folder_panel.isVisible() if hasattr(self, "folder_panel") else True)
        _ps.setValue("panelDetailVisible",    self.detail.isVisible()       if hasattr(self, "detail")        else True)
        _ps.setValue("panelConsoleVisible",   (self._main_vsplit.sizes()[1] > 0) if hasattr(self, "_main_vsplit") else False)
        _ps.setValue("panelFilterBarVisible", self._filterbar.isVisible()   if hasattr(self, "_filterbar")   else True)
        _ps.setValue("panelStatsBarVisible",  self._statsbar.isVisible()    if hasattr(self, "_statsbar")    else True)
        super().closeEvent(ev)

    def _refresh_recents_strip(self) -> None:
        while self._recents_lay.count():
            item = self._recents_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        paths = self._recent_paths()
        if not paths:
            return
        hdr = QLabel("Recent databases")
        hdr.setAlignment(Qt.AlignCenter)
        hdr.setStyleSheet(f"color:{SUBTEXT};font-size:11px;font-weight:bold;")
        self._recents_lay.addWidget(hdr)

        chip_row = QHBoxLayout()
        chip_row.setAlignment(Qt.AlignCenter)
        chip_row.setSpacing(8)
        chip_ss = (
            f"QPushButton{{background:transparent;color:{TEXT};"
            f"border:1px solid {BORDER};border-radius:12px;padding:4px 12px;font-size:11px;}}"
            f"QPushButton:hover{{border-color:{ACCENT};color:{ACCENT};}}"
        )
        for p in paths:
            chip = QPushButton(f"📂  {Path(p).name}")
            chip.setToolTip(p)
            chip.setStyleSheet(chip_ss)
            chip.clicked.connect(lambda _c=False, path=p: self._open_recent(path))
            chip_row.addWidget(chip)
        container = QWidget()
        container.setLayout(chip_row)
        self._recents_lay.addWidget(container)

    # ── Button factories ──────────────────────────────────────────────────────

    def _btn_primary(self, text: str, tooltip: str = "") -> QPushButton:
        b = QPushButton(text); b.setToolTip(tooltip)
        b.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; color: white; border: none;
                border-radius: 7px; padding: 6px 16px; font-weight: 600; font-size: 12px;
            }}
            QPushButton:hover    {{ background: #9d8fff; }}
            QPushButton:pressed  {{ background: #6a58d4; }}
            QPushButton:disabled {{ background: {BORDER}; color: {SUBTEXT}; }}
        """)
        return b

    def _btn_secondary(self, text: str, tooltip: str = "") -> QPushButton:
        b = QPushButton(text); b.setToolTip(tooltip)
        b.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 7px; padding: 6px 14px; font-size: 12px;
            }}
            QPushButton:hover    {{ background: {PANEL_BG}; border-color: {ACCENT}; color: {ACCENT}; }}
            QPushButton:pressed  {{ background: {DARK_BG}; }}
            QPushButton:disabled {{ color: {SUBTEXT}; border-color: {BORDER}; }}
        """)
        return b

    def _btn_danger(self, text: str, tooltip: str = "") -> QPushButton:
        b = QPushButton(text); b.setToolTip(tooltip)
        b.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {RED}; border: 1px solid {RED:44};
                border-radius: 7px; padding: 6px 14px; font-size: 12px;
            }}
            QPushButton:hover    {{ background: {RED:22}; border-color: {RED}; }}
            QPushButton:pressed  {{ background: {RED:33}; }}
            QPushButton:disabled {{ color: {SUBTEXT}; border-color: {BORDER}; }}
        """)
        return b

    def _btn_ghost(self, text: str, tooltip: str = "") -> QPushButton:
        b = QPushButton(text); b.setToolTip(tooltip)
        b.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {SUBTEXT}; border: none;
                border-radius: 5px; padding: 4px 8px; font-size: 11px;
            }}
            QPushButton:hover   {{ color: {TEXT}; background: {PANEL_BG}; }}
            QPushButton:pressed {{ color: {ACCENT}; }}
        """)
        return b

    # ── Main UI ───────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central  = QWidget()
        self.setCentralWidget(central)
        root_lay = QVBoxLayout(central)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        root_lay.addWidget(self._build_toolbar())
        root_lay.addWidget(self._build_scan_progress())
        root_lay.addWidget(self._build_filterbar())

        self.console = ConsolePanel()
        sys.stderr   = _StderrBridge(self.console, sys.stderr)

        v_split = QSplitter(Qt.Vertical)
        v_split.setHandleWidth(1)
        v_split.addWidget(self._build_body())
        v_split.addWidget(self.console)
        v_split.setSizes([660, 140])
        self._main_vsplit = v_split
        root_lay.addWidget(v_split, 1)

        root_lay.addWidget(self._build_statsbar())

        # Process monitor dock
        self._process_dock = ProcessPanel(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self._process_dock)
        self._process_dock.hide()

        self._add_panel_toggles()

        sb = QStatusBar()
        sb.setFixedHeight(26)
        self.setStatusBar(sb)
        self.status = sb
        self._set_status("Open a database or scan a folder to get started.  "
                         "  Ctrl+O = Open DB  ·  Ctrl+Shift+S = Scan")

    def _build_toolbar(self) -> QWidget:
        bar   = QWidget()
        bar.setStyleSheet(f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        r1 = QWidget()
        r1.setStyleSheet(f"background: {PANEL_BG};")
        r1.setFixedHeight(52)
        rl = QHBoxLayout(r1)
        rl.setContentsMargins(16, 0, 16, 0)
        rl.setSpacing(8)

        logo = QLabel("🔎")
        logo.setStyleSheet("font-size: 20px;")
        rl.addWidget(logo)
        title = QLabel("ValScanner")
        title.setStyleSheet(f"color: {TEXT}; font-size: 15px; font-weight: bold;")
        rl.addWidget(title)

        sep = QFrame(); sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {BORDER};")
        rl.addWidget(sep)

        scan_lbl = QLabel("Scan folder:")
        scan_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        rl.addWidget(scan_lbl)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Choose a folder to scan…")
        self.path_edit.setMinimumWidth(300)
        self.path_edit.returnPressed.connect(self._start_scan)
        rl.addWidget(self.path_edit, 1)

        browse_scan_btn = self._btn_secondary("📁  Browse", "Choose folder to scan (Ctrl+Shift+S)")
        browse_scan_btn.clicked.connect(self._browse_scan)
        rl.addWidget(browse_scan_btn)

        label_lbl = QLabel("Label:")
        label_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        rl.addWidget(label_lbl)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("e.g. MacBook SSD, Drive A…")
        self.label_edit.setFixedWidth(180)
        self.label_edit.setFixedHeight(30)
        self.label_edit.setToolTip("Optional name for this scan")
        rl.addWidget(self.label_edit)

        self.hash_chk = QCheckBox("SHA-256 hashes")
        self.hash_chk.setChecked(False)
        self.hash_chk.setToolTip("Compute file hashes — enables exact duplicate detection")
        rl.addWidget(self.hash_chk)

        self.options_btn = self._btn_secondary("⚙ Options", "Configure scan options")
        self.options_btn.setFixedHeight(32)
        self.options_btn.clicked.connect(self._open_scan_options)
        rl.addWidget(self.options_btn)

        self.scan_btn = self._btn_primary("⚡  Scan", "Start scanning (Enter)")
        self.scan_btn.setFixedWidth(100)
        self.scan_btn.clicked.connect(self._start_scan)
        rl.addWidget(self.scan_btn)

        self.stop_btn = self._btn_danger("■  Stop", "Abort current scan")
        self.stop_btn.setFixedWidth(80)
        self.stop_btn.clicked.connect(self._stop_scan)
        self.stop_btn.setEnabled(False)
        rl.addWidget(self.stop_btn)
        outer.addWidget(r1)

        r2 = QWidget()
        r2.setStyleSheet(f"background: {DARK_BG}; border-top: 1px solid {BORDER};")
        r2.setFixedHeight(40)
        rl2 = QHBoxLayout(r2)
        rl2.setContentsMargins(16, 0, 16, 0)
        rl2.setSpacing(8)

        db_icon = QLabel("🗄")
        db_icon.setStyleSheet(f"color: {SUBTEXT}; font-size: 13px;")
        rl2.addWidget(db_icon)
        db_lbl = QLabel("Database:")
        db_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        rl2.addWidget(db_lbl)

        self.db_edit = QLineEdit("file_index.db")
        self.db_edit.setPlaceholderText("Path to .db file…")
        self.db_edit.setFixedWidth(220)
        self.db_edit.setFixedHeight(26)
        self.db_edit.setStyleSheet(
            f"QLineEdit {{ background:{PANEL_BG}; color:{TEXT}; border:1px solid {BORDER};"
            f"border-radius:5px; padding:3px 8px; font-size:11px; }}"
            f"QLineEdit:focus {{ border-color:{ACCENT}; }}"
        )
        rl2.addWidget(self.db_edit)

        browse_db_btn = self._btn_ghost("📁", "Browse for database save location")
        browse_db_btn.setFixedSize(26, 26)
        browse_db_btn.clicked.connect(self._browse_db_save)
        rl2.addWidget(browse_db_btn)

        open_db_btn = self._btn_ghost("📂  Open existing DB", "Load a previously saved database (Ctrl+O)")
        open_db_btn.clicked.connect(self._open_db)
        rl2.addWidget(open_db_btn)

        rl2.addSpacing(12)
        sep2 = QFrame(); sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet(f"color: {BORDER};")
        rl2.addWidget(sep2)
        rl2.addSpacing(4)

        self.csv_btn  = self._btn_ghost("↓ CSV",  "Export results to CSV (Ctrl+E)")
        self.json_btn = self._btn_ghost("↓ JSON", "Export results to JSON (Ctrl+Shift+E)")
        self.csv_btn.clicked.connect(self._export_csv)
        self.json_btn.clicked.connect(self._export_json)
        self.csv_btn.setEnabled(False)
        self.json_btn.setEnabled(False)
        rl2.addWidget(self.csv_btn); rl2.addWidget(self.json_btn)
        rl2.addStretch()

        self.db_status_lbl = QLabel("No database loaded")
        self.db_status_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; background: {PANEL_BG}; "
            f"border: 1px solid {BORDER}; border-radius: 8px; padding: 1px 10px;"
        )
        self.db_status_lbl.setMaximumHeight(22)
        rl2.addWidget(self.db_status_lbl, 0, Qt.AlignVCenter)
        outer.addWidget(r2)
        return bar

    def _build_scan_progress(self) -> QWidget:
        self._scan_strip = QWidget()
        self._scan_strip.setFixedHeight(28)
        self._scan_strip.setStyleSheet(f"background: {DARK_BG};")
        sl = QHBoxLayout(self._scan_strip)
        sl.setContentsMargins(16, 0, 16, 0)
        sl.setSpacing(10)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            f"QProgressBar {{ border: none; background: {PANEL_BG}; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}"
        )
        sl.addWidget(self.progress, 1)

        self.elapsed_lbl = QLabel()
        self.elapsed_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 10px; font-family: monospace;")
        self.elapsed_lbl.setFixedWidth(60)
        sl.addWidget(self.elapsed_lbl)
        self._scan_strip.hide()
        return self._scan_strip

    def _build_filterbar(self) -> QWidget:
        self._filterbar = QWidget()
        self._filterbar.setStyleSheet(
            f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )
        self._filterbar.setFixedHeight(44)
        fl = QHBoxLayout(self._filterbar)
        fl.setContentsMargins(12, 0, 12, 0)
        fl.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍  Search filename, tag, path…   (press /)")
        self.search_edit.setMinimumWidth(260)
        self.search_edit.setFixedHeight(30)
        self.search_edit.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._apply_filters)
        self.search_edit.textChanged.connect(lambda _t: self._search_timer.start())
        self.search_edit.setStyleSheet(
            f"QLineEdit {{ background:{DARK_BG}; color:{TEXT}; border:1px solid {BORDER};"
            f"border-radius:15px; padding:4px 14px; font-size:12px; }}"
            f"QLineEdit:focus {{ border-color:{ACCENT}; }}"
        )
        fl.addWidget(self.search_edit)

        self.scan_combo = QComboBox()
        self.scan_combo.setFixedHeight(30)
        self.scan_combo.addItem("All scans", userData=0)
        self.scan_combo.currentIndexChanged.connect(self._on_scan_filter_changed)
        self.scan_combo.setFixedWidth(160)
        fl.addWidget(self.scan_combo)

        self.cat_combo = QComboBox()
        self.cat_combo.setFixedHeight(30)
        self.cat_combo.addItem("All types")
        for cat in sorted(CATEGORY_COLORS.keys()):
            self.cat_combo.addItem(cat)
        self.cat_combo.currentTextChanged.connect(self._apply_filters)
        self.cat_combo.setFixedWidth(140)
        fl.addWidget(self.cat_combo)

        self.sort_combo = QComboBox()
        self.sort_combo.setFixedHeight(30)
        self.sort_combo.addItems(["Name ↑", "Size ↓", "Modified ↓", "Category"])
        self.sort_combo.currentIndexChanged.connect(self._apply_sort)
        self.sort_combo.setFixedWidth(120)
        fl.addWidget(self.sort_combo)

        sep_vf = QFrame(); sep_vf.setFrameShape(QFrame.VLine)
        sep_vf.setStyleSheet(f"color: {BORDER};")
        sep_vf.setFixedHeight(20)
        fl.addWidget(sep_vf)

        self._vf_btn = QPushButton("⚗ Filters")
        self._vf_btn.setFixedHeight(30)
        self._vf_btn.setToolTip("Show / hide view filters (no re-scan needed)")
        self._vf_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{SUBTEXT};border:1px solid {BORDER};"
            f"border-radius:6px;padding:2px 10px;font-size:11px;}}"
            f"QPushButton:hover{{color:{TEXT};border-color:{ACCENT};}}"
            f"QPushButton[active=true]{{color:{ACCENT};border-color:{ACCENT};background:{ACCENT:18};}}"
        )
        self._vf_btn.clicked.connect(self._open_view_filters)
        fl.addWidget(self._vf_btn)

        group_lbl = QLabel("Group:")
        group_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        fl.addWidget(group_lbl)

        self._group_combo = QComboBox()
        self._group_combo.setFixedHeight(30)
        self._group_combo.addItems(["None", "Category", "Extension", "Folder", "Date"])
        self._group_combo.setFixedWidth(110)
        self._group_combo.setToolTip("Group files in the Details view")
        self._group_combo.currentIndexChanged.connect(self._on_group_changed)
        fl.addWidget(self._group_combo)

        fl.addStretch()

        self.folder_pill = QWidget()
        self.folder_pill.setStyleSheet(
            f"background: {ACCENT:22}; border: 1px solid {ACCENT}; border-radius: 10px;"
        )
        self.folder_pill.setFixedHeight(24)
        pill_lay = QHBoxLayout(self.folder_pill)
        pill_lay.setContentsMargins(8, 0, 4, 0)
        pill_lay.setSpacing(4)
        self.folder_pill_lbl = QLabel()
        self.folder_pill_lbl.setStyleSheet(
            f"color: {ACCENT}; font-size: 11px; border: none; background: transparent;"
        )
        pill_lay.addWidget(self.folder_pill_lbl)
        self.folder_depth_btn = QPushButton("·/")
        self.folder_depth_btn.setFixedSize(20, 16)
        self.folder_depth_btn.setCheckable(True)
        self.folder_depth_btn.setToolTip("Direct children only · click to include all descendants")
        self.folder_depth_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {ACCENT:88}; border: none; font-size: 10px; font-weight: bold; padding: 0; }}"
            f"QPushButton:hover {{ color: {ACCENT}; }}"
            f"QPushButton:checked {{ color: {ACCENT}; }}"
        )
        self.folder_depth_btn.toggled.connect(self._on_folder_depth_toggled)
        pill_lay.addWidget(self.folder_depth_btn)
        dismiss_pill = QPushButton("×")
        dismiss_pill.setFixedSize(16, 16)
        dismiss_pill.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {ACCENT}; border: none; font-size: 13px; padding: 0; }}"
            f"QPushButton:hover {{ color: white; }}"
        )
        dismiss_pill.clicked.connect(self._clear_folder_filter)
        pill_lay.addWidget(dismiss_pill)
        self.folder_pill.hide()
        fl.addWidget(self.folder_pill)

        sep_v = QFrame(); sep_v.setFrameShape(QFrame.VLine)
        sep_v.setStyleSheet(f"color: {BORDER};")
        sep_v.setFixedHeight(20)
        fl.addWidget(sep_v)

        _vbtn_ss = (
            f"QPushButton{{background:transparent;color:{SUBTEXT};border:1px solid {BORDER};"
            f"border-radius:5px;padding:2px 9px;font-size:12px;}}"
            f"QPushButton:checked{{background:{ACCENT:22};color:{ACCENT};border-color:{ACCENT};}}"
            f"QPushButton:hover:!checked{{color:{TEXT};border-color:#5a5a7a;}}"
        )
        self._view_btn_grp = QButtonGroup(self._filterbar)
        self._view_btn_grp.setExclusive(True)
        for i, (label, tip) in enumerate([
            ("⊟ Details", "Full details table"),
            ("▦ Grid",    "Icon / thumbnail grid"),
            ("≡ List",    "Compact single-line list"),
        ]):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setStyleSheet(_vbtn_ss)
            if i == 0:
                b.setChecked(True)
            self._view_btn_grp.addButton(b, i)
            fl.addWidget(b)
        self._view_btn_grp.idClicked.connect(self._set_view_mode)

        clear_btn = self._btn_ghost("✕ Clear all")
        clear_btn.setFixedHeight(28)
        clear_btn.clicked.connect(self._clear_filters)
        fl.addWidget(clear_btn)
        return self._filterbar

    def _build_body(self) -> QSplitter:
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(1)

        self.folder_panel = FolderPanel()
        self.folder_panel.setMinimumWidth(180)
        self.folder_panel.folder_selected.connect(self._filter_by_folder)
        self.splitter.addWidget(self.folder_panel)

        self.center_tabs = QTabWidget()
        self.center_tabs.setDocumentMode(True)

        self._welcome_widget = self._build_welcome()
        self.center_tabs.addTab(self._welcome_widget, "")
        self.center_tabs.tabBar().hide()

        file_tab = QWidget()
        ftl      = QVBoxLayout(file_tab)
        ftl.setContentsMargins(0, 0, 0, 0)
        ftl.setSpacing(0)

        self._view_stack = QStackedWidget()

        self.table_model = FileTableModel()
        self.table       = QTableView()
        self.table.setModel(self.table_model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setHighlightSections(False)
        for col, mode in [
            (COL_IDX["Filename"], QHeaderView.ResizeToContents),
            (COL_IDX["Category"], QHeaderView.ResizeToContents),
            (COL_IDX["Size"],     QHeaderView.ResizeToContents),
            (COL_IDX["Modified"], QHeaderView.ResizeToContents),
            (COL_IDX["Tags"],     QHeaderView.Stretch),
            (COL_IDX["Path"],     QHeaderView.ResizeToContents),
        ]:
            self.table.horizontalHeader().setSectionResizeMode(col, mode)
        self.table.setStyleSheet(f"""
            QTableView {{
                background: {DARK_BG}; color: {TEXT}; border: none;
                font-size: 12px; selection-background-color: {SEL_BG}; selection-color: {SEL_TEXT};
            }}
            QTableView::item:selected {{ background: {SEL_BG}; color: {SEL_TEXT}; }}
            QHeaderView::section {{
                background: {PANEL_BG}; color: {SUBTEXT}; border: none;
                border-bottom: 1px solid {BORDER}; padding: 6px 10px;
                font-size: 11px; font-weight: bold;
            }}
        """)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_selected)
        self.table.doubleClicked.connect(self._open_selected)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self._view_stack.addWidget(self.table)

        self.icon_model = FileIconModel()
        self.grid_view  = QListView()
        self.grid_view.setModel(self.icon_model)
        self.grid_view.setViewMode(QListView.IconMode)
        self.grid_view.setResizeMode(QListView.Adjust)
        self.grid_view.setUniformItemSizes(True)
        self.grid_view.setSpacing(2)
        self.grid_view.setItemDelegate(FileCardDelegate())
        self.grid_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.grid_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid_view.setStyleSheet(
            f"QListView {{ background:{DARK_BG}; border:none; }}"
            f"QListView::item:selected {{ background:transparent; }}"
        )
        self.grid_view.selectionModel().currentChanged.connect(self._on_icon_selected)
        self.grid_view.doubleClicked.connect(self._open_selected)
        self.grid_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid_view.customContextMenuRequested.connect(self._context_menu)
        self._view_stack.addWidget(self.grid_view)

        self.list_view = QListView()
        self.list_view.setModel(self.icon_model)
        self.list_view.setViewMode(QListView.ListMode)
        self.list_view.setItemDelegate(FileRowDelegate())
        self.list_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setStyleSheet(
            f"QListView {{ background:{DARK_BG}; border:none; }}"
            f"QListView::item:selected {{ background:transparent; }}"
        )
        self.list_view.selectionModel().currentChanged.connect(self._on_icon_selected)
        self.list_view.doubleClicked.connect(self._open_selected)
        self.list_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self._context_menu)
        self._view_stack.addWidget(self.list_view)

        ftl.addWidget(self._view_stack)
        self.center_tabs.addTab(file_tab, "📄  Files")

        self.similar_panel = SimilarFoldersPanel()
        self.similar_panel.status_message.connect(self._set_status)
        self.center_tabs.addTab(self.similar_panel, "🗂  Similar Folders")

        self.scans_panel = ScansPanel()
        self.scans_panel.scan_deleted.connect(self._on_scan_deleted)
        self.scans_panel.scan_selected.connect(self._on_scan_panel_selected)
        self.center_tabs.addTab(self.scans_panel, "📦  Scans")

        self.splitter.addWidget(self.center_tabs)

        self.detail = DetailPanel()
        self.detail.setStyleSheet(f"background: {PANEL_BG}; border-left: 1px solid {BORDER};")
        self.splitter.addWidget(self.detail)

        self.splitter.setSizes([220, 900, 280])
        return self.splitter

    def _build_welcome(self) -> QWidget:
        from PySide6.QtWidgets import QVBoxLayout
        w   = QWidget()
        w.setStyleSheet(f"background: {DARK_BG};")
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)

        icon = QLabel("🔎")
        icon.setStyleSheet("font-size: 56px;")
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon)

        headline = QLabel("ValScanner")
        headline.setStyleSheet(f"color: {TEXT}; font-size: 22px; font-weight: bold;")
        headline.setAlignment(Qt.AlignCenter)
        lay.addWidget(headline)

        sub = QLabel("Index and explore your files with metadata, tags, and similarity detection.")
        sub.setStyleSheet(f"color: {SUBTEXT}; font-size: 13px;")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)

        lay.addSpacing(8)
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignCenter)
        btn_row.setSpacing(12)
        scan_btn = self._btn_primary("⚡  Scan a Folder")
        scan_btn.clicked.connect(self._browse_scan)
        open_btn = self._btn_secondary("📂  Open Existing Database")
        open_btn.clicked.connect(self._open_db)
        btn_row.addWidget(scan_btn); btn_row.addWidget(open_btn)
        lay.addLayout(btn_row)
        lay.addSpacing(20)

        self._recents_strip = QWidget()
        self._recents_lay   = QVBoxLayout(self._recents_strip)
        self._recents_lay.setContentsMargins(0, 0, 0, 0)
        self._recents_lay.setSpacing(6)
        self._recents_lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._recents_strip)
        self._refresh_recents_strip()
        lay.addSpacing(20)

        tips = QLabel(
            "Tip: drag a folder onto this window to scan it, or drop a .db file to open it.\n"
            "Keyboard shortcuts:  Ctrl+Shift+S = Scan  ·  Ctrl+O = Open DB  ·  / = Search  ·  Esc = Clear filters"
        )
        tips.setStyleSheet(f"color: {SUBTEXT:55}; font-size: 11px;")
        tips.setAlignment(Qt.AlignCenter)
        lay.addWidget(tips)
        return w

    def _build_statsbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background: {PANEL_BG}; border-top: 1px solid {BORDER};")
        bar.setFixedHeight(32)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 0)
        bl.setSpacing(0)

        def _stat(icon: str) -> QLabel:
            l = QLabel(f"{icon}  —")
            l.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px; padding: 0 12px;")
            return l

        def vsep() -> QFrame:
            f = QFrame(); f.setFrameShape(QFrame.VLine)
            f.setStyleSheet(f"color: {BORDER};")
            f.setFixedHeight(14)
            return f

        self._stat_files   = _stat("📁")
        self._stat_size    = _stat("💾")
        self._stat_showing = _stat("🔍")
        bl.addWidget(self._stat_files); bl.addWidget(vsep())
        bl.addWidget(self._stat_size);  bl.addWidget(vsep())
        bl.addWidget(self._stat_showing)
        bl.addStretch()
        self._statsbar = bar
        return bar

    def _update_stats(self, total: int, total_size: int, showing: int) -> None:
        self._stat_files.setText(f"📁  {total:,} files")
        self._stat_size.setText(f"💾  {human_size(total_size)}")
        self._stat_showing.setText(f"🔍  Showing {showing:,}")

    # ── Scan actions ──────────────────────────────────────────────────────────

    def _browse_scan(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose folder to scan", str(Path.home()))
        if path:
            self.path_edit.setText(path)
            if not self.db_edit.text().strip() or self.db_edit.text() == "file_index.db":
                self.db_edit.setText(str(Path(path).parent / "file_index.db"))
            if pref_get("autoStartScan"):
                self._start_scan()

    def _browse_db_save(self) -> None:
        current = self.db_edit.text().strip() or str(Path.home() / "file_index.db")
        path, _ = QFileDialog.getSaveFileName(
            self, "Choose database save location", current,
            "SQLite databases (*.db);;All files (*)",
        )
        if path:
            if not path.endswith(".db"):
                path += ".db"
            self.db_edit.setText(path)

    def _open_db(self) -> None:
        start = self.db_edit.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Open existing database", start,
            "SQLite databases (*.db);;All files (*)",
        )
        if not path:
            return
        if not Path(path).exists():
            QMessageBox.warning(self, "Not found", f"File not found:\n{path}")
            return
        try:
            conn   = sqlite3.connect(path)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            conn.close()
            if "files" not in tables:
                QMessageBox.warning(self, "Invalid database",
                                    "This file doesn't look like a ValScanner database.")
                return
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not open database:\n{e}")
            self._set_status(f"⚠ Could not open database: {e}")
            return
        self.db_edit.setText(path)
        self._db_path = path
        self._load_db(path)

    def _load_db(self, path: str) -> None:
        self._db_path = path
        self._push_recent(path)
        self.csv_btn.setEnabled(True)
        self.json_btn.setEnabled(True)
        self.similar_panel.set_db(path)
        self.detail.set_db(path)
        _THUMB_CACHE.set_db(path)
        self._refresh_scan_combo()
        self.scans_panel.load(path)
        self._load_from_db()
        self.folder_panel.load(path)
        self._switch_to_results()
        name = Path(path).name
        self.db_status_lbl.setText(f"  🟢 {name}  ")
        self.db_status_lbl.setStyleSheet(
            f"color: {GREEN}; font-size: 10px; background: {GREEN:11}; "
            f"border: 1px solid {GREEN:44}; border-radius: 8px; padding: 2px 10px;"
        )
        self._set_status(f"Loaded database: {path}")

    def _refresh_scan_combo(self) -> None:
        self.scan_combo.blockSignals(True)
        self.scan_combo.clear()
        self.scan_combo.addItem("All scans", userData=0)
        for s in list_scans(self._db_path):
            label = s["label"] or s["root"]
            self.scan_combo.addItem(f"[{s['id']}] {label}", userData=s["id"])
        self.scan_combo.blockSignals(False)

    def _switch_to_results(self) -> None:
        self.center_tabs.tabBar().show()
        self.center_tabs.setCurrentIndex(1)

    def _start_scan(self) -> None:
        root = self.path_edit.text().strip()
        if not root:
            self._browse_scan()
            return
        if not Path(root).exists():
            QMessageBox.warning(self, "Invalid path", f"Folder not found:\n{root}")
            return

        db = self.db_edit.text().strip() or "file_index.db"
        self._db_path = db
        self._clear_folder_filter()
        self.search_edit.clear()

        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.csv_btn.setEnabled(False)
        self.json_btn.setEnabled(False)
        self._scan_strip.show()
        self.db_status_lbl.setText("  🔄 Scanning…  ")
        self.db_status_lbl.setStyleSheet(
            f"color: {YELLOW}; font-size: 10px; background: {YELLOW:11}; "
            f"border: 1px solid {YELLOW:44}; border-radius: 8px; padding: 2px 10px;"
        )

        self._scan_start = time.time()
        self._elapsed_timer.start(1000)

        self._worker = ScanWorker(root, db, self.hash_chk.isChecked(),
                                  label=self.label_edit.text().strip(),
                                  options=self._scan_options)

        # Register with process monitor before starting
        reg = ProcessRegistry.instance()
        pid = reg.register(
            name=f"Scan: {Path(root).name}",
            cancel_cb=self._worker.stop,
            kill_cb=self._worker.terminate,
        )
        self._worker._pid = pid
        self._process_dock.show()

        self._worker.progress.connect(self._on_progress)
        self._worker.progress.connect(
            lambda count, path: reg.set_progress(pid, min(count // 1000, 99))
        )
        self._worker.finished.connect(self._on_scan_done)
        self._worker.error.connect(lambda e: self._set_status(f"⚠ Error: {e}"))
        self._worker.start()

    def _open_scan_options(self) -> None:
        dlg = ScanOptionsDialog(self, self._scan_options)
        if dlg.exec() == QDialog.Accepted:
            self._scan_options = dlg.get_options()
            self._save_scan_options()
            self._update_options_btn_label()

    def _save_scan_options(self) -> None:
        s = pref_settings()
        s.setValue("scanStoreThumbnails", self._scan_options.get("store_thumbnails", False))
        s.setValue("scanThumbSize",       self._scan_options.get("thumb_size", 128))
        s.setValue("scanThumbQuality",    self._scan_options.get("thumb_quality", 75))
        s.setValue("scanStoreSamples",    self._scan_options.get("store_samples", False))
        s.setValue("scanSampleDuration",  self._scan_options.get("sample_duration", 5))
        s.setValue("scanSkipHiddenDirs",  self._scan_options.get("skip_hidden_dirs",  True))
        s.setValue("scanSkipVcs",         self._scan_options.get("skip_vcs",          False))
        s.setValue("scanSkipSystem",      self._scan_options.get("skip_system",       False))
        s.setValue("scanSkipCaches",      self._scan_options.get("skip_caches",       False))
        s.setValue("scanSkipHiddenFiles", self._scan_options.get("skip_hidden_files", False))
        s.setValue("scanSkipBinaries",    self._scan_options.get("skip_binaries",     False))
        s.setValue("scanSkipTemp",        self._scan_options.get("skip_temp",         False))
        s.setValue("scanSkipLogs",        self._scan_options.get("skip_logs",         False))

    def _update_options_btn_label(self) -> None:
        active = [k for k, v in self._scan_options.items() if v and k.startswith("store_")]
        if active:
            labels = {"store_thumbnails": "thumbnails", "store_samples": "samples"}
            self.options_btn.setText("⚙ Options ·  " + ", ".join(labels[k] for k in active if k in labels))
        else:
            self.options_btn.setText("⚙ Options")

    def _stop_scan(self) -> None:
        if self._worker:
            self._worker.stop()
        self._elapsed_timer.stop()
        self._set_status("Scan cancelled.")

    def _tick_elapsed(self) -> None:
        secs = int(time.time() - self._scan_start)
        m, s = divmod(secs, 60)
        self.elapsed_lbl.setText(f"{m:02d}:{s:02d}")

    def _on_progress(self, count: int, path: str) -> None:
        short = path[-70:] if len(path) > 70 else path
        self.status.showMessage(f"Indexing… {count:,} files  —  {short}")
        if count % 1000 == 0:
            self.console.log(f"Indexed {count:,} files…", "info")

    def _on_scan_done(self, stats: dict) -> None:
        self._elapsed_timer.stop()
        self._scan_strip.hide()
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.csv_btn.setEnabled(True)
        self.json_btn.setEnabled(True)
        elapsed = int(time.time() - self._scan_start)
        self._set_status(
            f"✅  Scan complete — {stats['scanned']:,} files in {elapsed}s"
            + (f", {stats['errors']} errors" if stats["errors"] else "")
        )
        self._load_db(self._db_path)

    # ── Load / filter ─────────────────────────────────────────────────────────

    def _load_from_db(self) -> None:
        if not self._db_path or not Path(self._db_path).exists():
            return
        conn = sqlite3.connect(self._db_path)
        sid = self._active_scan_id
        where = "WHERE scan_id=?" if sid else ""
        args = (sid,) if sid else ()

        # Count and total size queries
        total, = conn.execute(f"SELECT COUNT(*) FROM files {where}", args).fetchone()
        total_size, = conn.execute(f"SELECT SUM(size_bytes) FROM files {where}", args).fetchone()

        # First page synchronous
        page_args = (sid, PAGE_SIZE, 0) if sid else (PAGE_SIZE, 0)
        rows = conn.execute(
            f"SELECT path, filename, category, size_bytes, size_human, modified_at, tags, extra_meta "
            f"FROM files {where} ORDER BY filename LIMIT ? OFFSET ?",
            page_args,
        ).fetchall()
        conn.close()

        self._all_rows = list(rows)
        self._total_row_count = total
        self._loaded_offset = PAGE_SIZE

        self._apply_filters()
        self._update_stats(total, total_size or 0, len(self._all_rows))
        self.center_tabs.setTabText(1, f"📄  Files ({total:,})")

        # Connect scroll handler for lazy loading
        sb = self.table.verticalScrollBar()
        try:
            sb.valueChanged.disconnect(self._on_table_scroll)
        except RuntimeError:
            pass
        sb.valueChanged.connect(self._on_table_scroll)

    def _apply_filters(self) -> None:
        term        = self.search_edit.text().strip().lower()
        cat         = self.cat_combo.currentText()
        folder      = self._active_folder_filter
        if cat == "All types":
            cat = ""
        folder_norm = str(Path(folder)) if folder else ""

        filtered = []
        for r in self._all_rows:
            if folder_norm:
                if self._folder_filter_recursive:
                    if not r[0].startswith(folder_norm + "/") and r[0] != folder_norm:
                        continue
                elif str(Path(r[0]).parent) != folder_norm:
                    continue
            if cat and r[2] != cat:
                continue
            if term and term not in f"{r[1]} {r[2]} {r[6]} {r[0]}".lower():
                continue
            filtered.append(r)

        # View filters (post-scan, no re-scan required)
        vf = self._view_filters
        if vf:
            hidden_cats     = vf.get("hidden_categories", set())
            min_bytes       = vf.get("min_bytes", 0)
            max_bytes       = vf.get("max_bytes", 0)
            exts            = vf.get("extensions", set())
            hide_hidden_dirs  = vf.get("hide_hidden_dirs",  False)
            hide_vcs          = vf.get("hide_vcs",          False)
            hide_system       = vf.get("hide_system",       False)
            hide_caches       = vf.get("hide_caches",       False)
            hide_hidden_files = vf.get("hide_hidden_files", False)
            hide_binaries     = vf.get("hide_binaries",     False)
            hide_temp         = vf.get("hide_temp",         False)
            hide_logs         = vf.get("hide_logs",         False)

            any_path_filter = (hide_hidden_dirs or hide_vcs or hide_system or hide_caches)
            any_active = (hidden_cats or min_bytes or max_bytes or exts
                          or any_path_filter
                          or hide_hidden_files or hide_binaries or hide_temp or hide_logs)

            if any_active:
                vf_out = []
                for r in filtered:
                    path, filename, _cat, size_b = r[0], r[1], r[2], r[3]
                    ext = Path(filename).suffix.lower()

                    if _cat in hidden_cats:
                        continue
                    if min_bytes and size_b < min_bytes:
                        continue
                    if max_bytes and size_b > max_bytes:
                        continue
                    if exts and ext.lstrip(".") not in exts:
                        continue
                    if hide_hidden_files and filename.startswith("."):
                        continue
                    if hide_binaries and ext in _BINARY_EXTS:
                        continue
                    if hide_temp and ext in _TEMP_EXTS:
                        continue
                    if hide_logs and ext in _LOG_EXTS:
                        continue

                    if any_path_filter:
                        parts = set(Path(path).parts)
                        if hide_hidden_dirs and any(p.startswith(".") for p in parts):
                            continue
                        if hide_vcs and parts & _VCS_DIRS:
                            continue
                        if hide_system and parts & _SYSTEM_DIRS:
                            continue
                        if hide_caches and parts & _CACHE_DIRS:
                            continue

                    vf_out.append(r)
                filtered = vf_out

        self._filtered_rows = filtered
        self._apply_sort()
        self._stat_showing.setText(f"🔍  Showing {len(filtered):,}")
        if self._active_folder_filter:
            self._update_pill_label(filtered_count=len(filtered))

    def _apply_sort(self) -> None:
        idx     = self.sort_combo.currentIndex()
        mapping = {
            0: (COL_IDX["Filename"], Qt.AscendingOrder),
            1: (COL_IDX["Size"],     Qt.DescendingOrder),
            2: (COL_IDX["Modified"], Qt.DescendingOrder),
            3: (COL_IDX["Category"], Qt.AscendingOrder),
        }
        col, order = mapping.get(idx, (COL_IDX["Filename"], Qt.AscendingOrder))
        # Always sort from ungrouped rows so group-header sentinels can't corrupt the sort
        self.table_model.load(self._filtered_rows)
        self.table_model.sort(col, order)
        sorted_rows = list(self.table_model._rows)  # sorted, ungrouped

        if self._group_by:
            self.table_model.load(self._group_rows(sorted_rows))

        self.icon_model.load(sorted_rows)

    def _group_rows(self, rows: list) -> list:
        """Insert group-header sentinel rows before each group."""
        KEY = {
            "category":  lambda r: r[2] or "other",
            "extension": lambda r: Path(r[1]).suffix.lower() or "(no ext)",
            "folder":    lambda r: str(Path(r[0]).parent),
            "date":      lambda r: r[5][:7] if (r[5] and len(r[5]) >= 7) else "Unknown",
        }.get(self._group_by)
        if KEY is None:
            return rows

        groups: dict[str, list] = {}
        order: list[str] = []
        for r in rows:
            k = KEY(r)
            if k not in groups:
                groups[k] = []
                order.append(k)
            groups[k].append(r)

        result = []
        for k in order:
            count = len(groups[k])
            header = (None,
                      f"{k}  ·  {count} {'file' if count == 1 else 'files'}",
                      "__group__", 0, "", "", "", "")
            result.append(header)
            result.extend(groups[k])
        return result

    # ── View filters ──────────────────────────────────────────────────────────

    def _open_view_filters(self) -> None:
        if self._view_filters_dlg is None:
            self._view_filters_dlg = ViewFiltersDialog(self, self._view_filters)
            self._view_filters_dlg.filters_changed.connect(self._on_view_filters_changed)
        else:
            self._view_filters_dlg.set_filters(self._view_filters)
        self._view_filters_dlg.show()
        self._view_filters_dlg.raise_()
        self._view_filters_dlg.activateWindow()

    def _on_view_filters_changed(self, filters: dict) -> None:
        self._view_filters = filters
        self._apply_filters()
        self._update_vf_btn_label()

    def _update_vf_btn_label(self) -> None:
        n = self._count_active_view_filters()
        self._vf_btn.setText(f"⚗ Filters  ·  {n}" if n else "⚗ Filters")
        self._vf_btn.setProperty("active", "true" if n else "false")
        self._vf_btn.style().unpolish(self._vf_btn)
        self._vf_btn.style().polish(self._vf_btn)

    def _count_active_view_filters(self) -> int:
        f = self._view_filters
        n  = len(f.get("hidden_categories", set()))
        if f.get("min_bytes", 0):        n += 1
        if f.get("max_bytes", 0):        n += 1
        if f.get("extensions"):          n += 1
        _pf_keys = ("hide_hidden_dirs", "hide_vcs", "hide_system", "hide_caches",
                    "hide_hidden_files", "hide_binaries", "hide_temp", "hide_logs")
        n += sum(1 for k in _pf_keys if f.get(k))
        return n

    def _on_group_changed(self, _index: int) -> None:
        keys = ["", "category", "extension", "folder", "date"]
        self._group_by = keys[self._group_combo.currentIndex()]
        self._apply_sort()

    def _set_view_mode(self, mode: int) -> None:
        self._view_stack.setCurrentIndex(mode)

    def _on_icon_selected(self, current, _prev) -> None:
        if not current.isValid():
            return
        row = self.icon_model.data(current, Qt.UserRole)
        if row:
            self.detail.show_file(row)

    def _filter_by_folder(self, folder_path: str) -> None:
        if not folder_path:
            return
        self._active_folder_filter    = folder_path
        self._folder_filter_recursive = False
        self.folder_depth_btn.blockSignals(True)
        self.folder_depth_btn.setChecked(False)
        self.folder_depth_btn.blockSignals(False)
        self._update_pill_label()
        self.folder_pill.show()
        self._apply_filters()
        self.center_tabs.setCurrentIndex(1)

    def _on_folder_depth_toggled(self, checked: bool) -> None:
        self._folder_filter_recursive = checked
        self.folder_depth_btn.setToolTip(
            "All descendants · click for direct children only" if checked
            else "Direct children only · click to include all descendants"
        )
        self._update_pill_label()
        self._apply_filters()

    def _update_pill_label(self, filtered_count: int | None = None) -> None:
        short = Path(self._active_folder_filter).name or self._active_folder_filter
        mode  = "/**" if self._folder_filter_recursive else "/·"
        suffix = f"  ·  {filtered_count:,}" if filtered_count is not None else ""
        self.folder_pill_lbl.setText(f"📂 {short}{mode}{suffix}")

    def _clear_folder_filter(self) -> None:
        self._active_folder_filter    = ""
        self._folder_filter_recursive = False
        self.folder_depth_btn.blockSignals(True)
        self.folder_depth_btn.setChecked(False)
        self.folder_depth_btn.blockSignals(False)
        self.folder_pill.hide()
        self._apply_filters()

    def _clear_filters(self) -> None:
        self.search_edit.clear()
        self.cat_combo.setCurrentIndex(0)
        self._clear_folder_filter()
        self._view_filters = {}
        self._update_vf_btn_label()
        if self._view_filters_dlg is not None:
            self._view_filters_dlg.set_filters({})

    def _on_scan_filter_changed(self, _index) -> None:
        self._active_scan_id = self.scan_combo.currentData() or 0
        self._clear_folder_filter()
        self._load_from_db()
        if self._active_scan_id:
            self.folder_panel.load(self._db_path, scan_id=self._active_scan_id)
        else:
            self.folder_panel.load(self._db_path)

    def _on_scan_panel_selected(self, scan_id: int, label: str) -> None:
        for i in range(self.scan_combo.count()):
            if self.scan_combo.itemData(i) == scan_id:
                self.scan_combo.setCurrentIndex(i)
                break
        self.center_tabs.setCurrentIndex(1)

    def _on_scan_deleted(self, _scan_id: int) -> None:
        self._active_scan_id = 0
        self._refresh_scan_combo()
        self._load_from_db()
        self.folder_panel.load(self._db_path)
        self.scans_panel.load(self._db_path)
        self.similar_panel._rebuild_partition_row()

    # ── Table interaction ─────────────────────────────────────────────────────

    def _on_row_selected(self, current, _prev) -> None:
        if not current.isValid() or not self.table_model._rows:
            return
        data = self.table_model.data(current, Qt.UserRole)
        if data:
            self.detail.show_file(data)

    def _open_selected(self, _index) -> None:
        self.detail._open_file()

    def _context_menu(self, pos) -> None:
        view  = self.sender()
        index = view.indexAt(pos)
        if not index.isValid():
            return
        if view is self.table:
            row = self.table_model._rows[index.row()]
        else:
            row = self.icon_model.data(index, Qt.UserRole)
        if not row:
            return
        menu       = QMenu(self)
        open_act   = menu.addAction("🚀  Open file")
        reveal_act = menu.addAction("📂  Reveal in Finder / Explorer")
        menu.addSeparator()
        copy_path = menu.addAction("📋  Copy path")
        copy_name = menu.addAction("📋  Copy filename")
        act = menu.exec(view.viewport().mapToGlobal(pos))
        if act == open_act:
            self.detail._current_path = row[0]
            self.detail._open_file()
        elif act == reveal_act:
            self._reveal(str(Path(row[0]).parent))
        elif act == copy_path:
            QApplication.clipboard().setText(row[0])
            self._set_status(f"Copied path: {row[0]}")
        elif act == copy_name:
            QApplication.clipboard().setText(row[1])
            self._set_status(f"Copied: {row[1]}")

    def _reveal(self, path: str) -> None:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def _on_table_scroll(self, value: int) -> None:
        """Lazy load handler: trigger when scrolling near the end."""
        sb = self.table.verticalScrollBar()
        if sb.maximum() == 0:
            return
        # Trigger at 80% scroll depth
        if value / sb.maximum() < 0.80:
            return
        # Already loaded all rows
        if self._loaded_offset >= self._total_row_count:
            return
        # Avoid concurrent loads
        if self._lazy_worker and self._lazy_worker.isRunning():
            return
        self._fetch_next_page()

    def _fetch_next_page(self) -> None:
        """Start background load of next page."""
        self._lazy_worker = LazyLoadWorker(self._db_path, self._active_scan_id, self._loaded_offset)
        self._lazy_worker.rows_ready.connect(self._on_lazy_rows_ready)
        self._lazy_worker.error.connect(lambda e: self._set_status(f"⚠ Error loading rows: {e}"))
        self._lazy_worker.start()

    def _on_lazy_rows_ready(self, new_rows: list) -> None:
        """Handle newly loaded rows from background worker."""
        if not new_rows:
            return
        # Extend internal row cache
        self._all_rows.extend(new_rows)
        self._loaded_offset += len(new_rows)

        # Filter new batch against current search/category state
        term = self.search_edit.text().strip().lower()
        cat = self.cat_combo.currentText()
        if cat == "All types":
            cat = ""
        filtered_new = [
            r for r in new_rows
            if (not cat or r[2] == cat)
            and (not term or term in f"{r[1]} {r[2]} {r[6]} {r[0]}".lower())
        ]

        if filtered_new:
            self._filtered_rows.extend(filtered_new)
            # Apply table model append (preserves scroll position)
            self.table_model.append_rows(filtered_new)
            # Icon model still resets (acceptable for secondary view)
            self.icon_model.load(list(self.table_model._rows))
            self._stat_showing.setText(f"🔍  Showing {len(self._filtered_rows):,}")

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_csv(self) -> None:
        if not self._db_path:
            return
        out  = self._db_path.replace(".db", ".csv")
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", out, "CSV files (*.csv)")
        if path:
            export_csv(self._db_path, path)
            self._set_status(f"✅  CSV saved → {path}")

    def _export_json(self) -> None:
        if not self._db_path:
            return
        out  = self._db_path.replace(".db", ".json")
        path, _ = QFileDialog.getSaveFileName(self, "Export JSON", out, "JSON files (*.json)")
        if path:
            export_json(self._db_path, path)
            self._set_status(f"✅  JSON saved → {path}")

    def _set_status(self, msg: str) -> None:
        self.status.showMessage(msg)
        if not hasattr(self, "console"):
            return
        if "✅" in msg or "complete" in msg.lower() or "saved" in msg.lower() or msg.startswith("Loaded"):
            level = "success"
        elif "⚠" in msg or "Error" in msg or "error" in msg or "failed" in msg.lower() or "cancelled" in msg.lower():
            level = "error"
        else:
            level = "info"
        self.console.log(msg, level)


def _app_icon() -> QIcon:
    assets = Path(__file__).parent.parent / "assets"
    if sys.platform == "win32":
        name = "icon.ico"
    elif sys.platform == "darwin":
        name = "icon.icns"
    else:
        name = "icon.png"
    icon = QIcon(str(assets / name))
    return icon if not icon.isNull() else QIcon()


def main() -> None:
    app = QApplication(sys.argv)
    app.setOrganizationName("valscanner")
    app.setApplicationName("ValScanner")
    app.setApplicationDisplayName("ValScanner")
    app.setStyle("Fusion")
    icon = _app_icon()
    app.setWindowIcon(icon)
    win = MainWindow()
    win.setWindowIcon(icon)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
