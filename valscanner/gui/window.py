#!/usr/bin/env python3
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSettings, QSize, QEvent
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox,
    QComboBox, QProgressBar, QStatusBar,
    QFileDialog, QTableView, QListView,
    QHeaderView, QAbstractItemView,
    QFrame, QScrollArea,
    QTabWidget,
    QMessageBox, QMenu, QDialog,
    QStackedWidget, QButtonGroup,
)

from .constants import (
    CATEGORY_COLORS,
    DARK_BG, PANEL_BG, ROW_ALT, ACCENT, TEXT, SUBTEXT, BORDER, GREEN, RED, YELLOW, SEL_BG, SEL_TEXT,
    DIVIDER2, DIVIDER3, BG2, BG3,
    BTN_HOVER, BTN_PRESSED, HOVER_BORDER, SCROLLBAR_HOVER,
)
from .models import FileTableModel, FileIconModel, _THUMB_CACHE, COL_IDX, make_folder_row, _FOLDER_SENTINEL
from . import icons as _icons
from .delegates import FileCardDelegate, FileRowDelegate
from .workers import ScanWorker, DbLoadWorker, LazyLoadWorker, BrowserLoadWorker, ConnectWorker, PAGE_SIZE
from .dialogs import ScanOptionsDialog, ViewFiltersDialog, DatabaseSettingsDialog
from .panels.detail import DetailPanel
from .panels.folders import FolderPanel
from .panels.similar import SimilarFoldersPanel
from .panels.scans import ScansPanel
from .panels.console import ConsolePanel, _StderrBridge
from .panels.process import ProcessPanel, ProcessRegistry
from .collapsible import CollapsiblePanel, RightZone
from .widgets.hover_peek import HoverPeekCard
from .recent import RecentDBsModel
from .preferences import PreferencesDialog, get as pref_get, settings as pref_settings
from . import persistence
from . import density as _density
from .fonts import load_fonts, ui_font_family, mono_font_family
from ..core.export import export_csv, export_json
from ..core.db import list_scans, reset_repos
from ..core.db_config import reset_engines
from ..core.schema import human_size
from ..core.scanner import _SYSTEM_DIRS, _CACHE_DIRS, _VCS_DIRS, _BINARY_EXTS, _TEMP_EXTS, _LOG_EXTS
from ..core import app_settings as _app_settings
from ..core.app_settings import active_url, mask_url


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        persistence.migrate()
        self.setWindowTitle("ValScanner")
        self.resize(1440, 880)
        self._db_path                = ""
        self._db_url                 = ""  # authoritative SQLAlchemy URL
        self._connect_worker: ConnectWorker | None = None
        self._worker                 = None
        self._db_load_worker: DbLoadWorker | None = None
        self._all_rows: list         = []
        self._folder_filter_recursive = False
        self._active_scan_id         = 0
        self._scan_start             = 0.0
        self._elapsed_timer          = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._scan_options: dict     = {}
        self._scan_queue: list[dict] = []
        self._view_filters: dict     = persistence.get_json(persistence.Keys.FILES_FILTERS, {})
        self._group_by: str          = ""
        self._view_filters_dlg: ViewFiltersDialog | None = None
        self._filtered_rows: list    = []
        self._lazy_worker: LazyLoadWorker | None = None
        self._total_row_count        = 0
        self._loaded_offset          = 0
        # Browser mode
        self._browser_path           = ""          # current path in browser mode
        self._browser_worker: BrowserLoadWorker | None = None
        self._browser_history: list[str] = []
        self._current_view_index     = 0           # 0=table 1=grid 2=list

        self.recent_dbs = RecentDBsModel.instance()
        self.recent_dbs.changed.connect(self._rebuild_recent_menu)
        self.recent_dbs.changed.connect(self._on_recents_changed)

        _density.load_density()
        self._apply_global_stylesheet()
        self._build_menu()
        self._build_ui()

        from .theme import Theme
        Theme.instance().on_changed(self._apply_stylesheet)
        _density.on_changed(self._on_density_changed)

        self.setAcceptDrops(True)
        self._install_shortcuts()
        self._apply_startup_settings()

    def _apply_global_stylesheet(self) -> None:
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: {DARK_BG}; color: {TEXT};
                font-family: '{ui_font_family()}', 'SF Pro Display', 'Segoe UI', sans-serif;
            }}
            QSplitter::handle {{ background: {BORDER}; width: 1px; height: 1px; }}
            QLineEdit {{
                background: {DARK_BG}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 7px; padding: 5px 11px; font-size: 12px;
                selection-background-color: {ACCENT};
            }}
            QLineEdit:focus {{ border-color: {ACCENT}; background: {PANEL_BG}; }}
            QLineEdit:hover {{ border-color: {HOVER_BORDER}; }}
            QComboBox {{
                background: {DARK_BG}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 7px; padding: 5px 10px; font-size: 12px; min-width: 80px;
            }}
            QComboBox:hover {{ border-color: {HOVER_BORDER}; }}
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
                background: {SCROLLBAR_HOVER};
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
            QTabWidget::pane {{ border: none; }}
            QTabBar {{ background: {DARK_BG}; border-bottom: 1px solid {BORDER}; }}
            QTabBar::tab {{
                background: transparent; color: {SUBTEXT}; padding: 10px 16px;
                font-size: 12px; border-bottom: 2px solid transparent; margin-right: 2px;
                min-height: 18px; letter-spacing: 0.01em;
            }}
            QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}
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

    def _apply_stylesheet(self) -> None:
        """Re-apply all themed stylesheets — called on live theme change."""
        self._apply_global_stylesheet()
        if not hasattr(self, "table"):
            return  # called before _build_ui; global stylesheet is enough

        # toolbar
        self._toolbar.setStyleSheet(
            f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )
        self._toolbar_r1.setStyleSheet(f"background: {PANEL_BG};")
        self._toolbar_r2.setStyleSheet(f"background: {PANEL_BG};")
        self.db_edit.setStyleSheet(
            f"QLineEdit {{ background:{PANEL_BG}; color:{TEXT}; border:1px solid {BORDER};"
            f"border-radius:5px; padding:3px 8px; font-size:11px; }}"
            f"QLineEdit:focus {{ border-color:{ACCENT}; }}"
        )
        self.db_status_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; background: {PANEL_BG}; "
            f"border: 1px solid {BORDER}; border-radius: 8px; padding: 1px 10px;"
        )

        # inline progress
        self.progress.setStyleSheet(
            f"QProgressBar {{ border: none; background: {PANEL_BG}; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}"
        )
        self.elapsed_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; font-family: '{mono_font_family()}', monospace;"
        )

        # queue strip
        self._queue_strip.setStyleSheet(
            f"background: {DARK_BG}; border-bottom: 1px solid {BORDER};"
        )
        self._queue_status_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        self._clear_queue_btn.setStyleSheet(
            f"QPushButton{{color:{SUBTEXT};font-size:11px;border:none;padding:0;}}"
            f"QPushButton:hover{{color:{TEXT};}}"
        )

        # filter bar
        self._filterbar.setStyleSheet(
            f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )
        self.search_edit.setStyleSheet(
            f"QLineEdit {{ background:{DARK_BG}; color:{TEXT}; border:1px solid {DIVIDER2};"
            f"border-radius:8px; padding:0 10px; font-size:12px; }}"
            f"QLineEdit:focus {{ border-color:{ACCENT}; background:{PANEL_BG}; }}"
        )
        self._vf_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{SUBTEXT};border:0;"
            f"padding:0 8px;font-size:11px;}}"
            f"QPushButton:hover{{color:{TEXT};}}"
            f"QPushButton[active=true]{{color:{ACCENT};background:{ACCENT:22};border-radius:4px;}}"
        )
        self.folder_pill.setStyleSheet(
            f"background: {ACCENT:22}; border: 1px solid {ACCENT:6a}; border-radius: 11px;"
        )
        self.folder_pill_lbl.setStyleSheet(
            f"color: {ACCENT}; font-size: 10.5px; border: none; background: transparent;"
            f"font-family: '{mono_font_family()}', monospace;"
        )
        _vbtn_ss = (
            f"QPushButton{{background:transparent;color:{SUBTEXT};border:1px solid {DIVIDER2};"
            f"border-radius:5px;padding:0 9px;font-size:11px;}}"
            f"QPushButton:checked{{background:{ACCENT:22};color:{ACCENT};border-color:{ACCENT};}}"
            f"QPushButton:hover:!checked{{color:{TEXT};border-color:{DIVIDER3};}}"
        )
        _seg_inner = (
            f"QPushButton{{background:transparent;color:{SUBTEXT};border:0;border-radius:0;"
            f"padding:0 10px;font-size:11px;}}"
            f"QPushButton:checked{{background:{ACCENT:22};color:{ACCENT};}}"
            f"QPushButton:hover:!checked{{color:{TEXT};}}"
        )
        for _b in self._view_btn_grp.buttons():
            _b.setStyleSheet(_seg_inner)
        for _b in self._density_btn_grp.buttons():
            _b.setStyleSheet(_vbtn_ss)

        # breadcrumb + depth buttons
        self._breadcrumb_bar.setStyleSheet(
            f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )
        _seg = (
            f"QPushButton{{background:{PANEL_BG};color:{SUBTEXT};border:1px solid {BORDER};"
            f"padding:2px 9px;font-size:11px;}}"
            f"QPushButton:checked{{background:{ACCENT:22};color:{ACCENT};border-color:{ACCENT};}}"
            f"QPushButton:hover:!checked{{color:{TEXT};}}"
        )
        self._depth_this_btn.setStyleSheet(
            _seg + "QPushButton{border-radius:0;"
                   "border-top-left-radius:5px;border-bottom-left-radius:5px;}"
        )
        self._depth_sub_btn.setStyleSheet(
            _seg + "QPushButton{border-radius:0;"
                   "border-top-right-radius:5px;border-bottom-right-radius:5px;border-left:none;}"
        )

        # views
        self.table.setStyleSheet(f"""
            QTableView {{
                background: {DARK_BG}; color: {TEXT}; border: none;
                font-size: 12px; selection-background-color: {SEL_BG};
                selection-color: {SEL_TEXT};
            }}
            QTableView::item:selected {{ background: {SEL_BG}; color: {SEL_TEXT}; }}
            QHeaderView::section {{
                background: {PANEL_BG}; color: {SUBTEXT}; border: none;
                border-bottom: 1px solid {BORDER}; padding: 6px 10px;
                font-size: 11px; font-weight: bold;
            }}
        """)
        self.grid_view.setStyleSheet(
            f"QListView {{ background:{DARK_BG}; border:none; }}"
            f"QListView::item:selected {{ background:transparent; }}"
        )
        self.list_view.setStyleSheet(
            f"QListView {{ background:{DARK_BG}; border:none; }}"
            f"QListView::item:selected {{ background:transparent; }}"
        )
        self.detail.setStyleSheet(
            f"background: {PANEL_BG}; border-left: 1px solid {BORDER};"
        )
        if hasattr(self, "_folder_rail"):
            self._folder_rail.apply_theme()
        if hasattr(self, "_right_zone"):
            self._right_zone.apply_theme()

        # task pill
        _gear_ss = (
            f"QToolButton{{background:transparent;border:none;}}"
            f"QToolButton:hover{{background:{PANEL_BG};border-radius:3px;}}"
        )
        self._task_gear_btn.setStyleSheet(_gear_ss)
        self._task_count_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:10px;")
        self._task_name_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:10px;")
        self._task_stop_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{RED};border:none;font-size:11px;}}"
            f"QPushButton:hover{{background:{RED:22};border-radius:3px;}}"
        )

        # statsbar
        self._statsbar.setStyleSheet(
            f"background: {PANEL_BG}; border-top: 1px solid {BORDER};"
        )
        for _lbl in (self._stat_files, self._stat_size, self._stat_showing):
            _lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px; padding: 0 12px 0 4px;")

        # scan button — re-style only, never touch signals
        if getattr(self, "_worker", None) and self._worker.isRunning():
            self.scan_btn.setStyleSheet(
                f"QPushButton{{background:{RED};color:white;border:none;"
                f"border-radius:7px;padding:6px 16px;font-weight:600;font-size:12px;}}"
                f"QPushButton:hover{{background:{RED};}}"
            )
        else:
            self.scan_btn.setStyleSheet(
                f"QPushButton{{background:{ACCENT};color:white;border:none;"
                f"border-radius:7px;padding:6px 16px;font-weight:600;font-size:12px;}}"
                f"QPushButton:hover{{background:{BTN_HOVER};}}"
                f"QPushButton:pressed{{background:{BTN_PRESSED};}}"
                f"QPushButton:disabled{{background:{BORDER};color:{SUBTEXT};}}"
            )

    # ── Density ───────────────────────────────────────────────────────────────

    def _on_density_id_clicked(self, idx: int) -> None:
        _density.set_density(("compact", "normal", "relaxed")[idx])

    def _on_density_changed(self) -> None:
        h = _density.get_row_height()
        self.table.verticalHeader().setDefaultSectionSize(h)
        self.table.update()

    # ── Hover peek ────────────────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if (hasattr(self, "table") and obj is self.table.viewport()
                and self._current_view_index == 0):
            t = event.type()
            if t == QEvent.MouseMove:
                idx = self.table.indexAt(event.pos())
                if idx.isValid():
                    row = self.table_model.data(
                        self.table_model.index(idx.row(), 0), Qt.UserRole
                    )
                    if row and len(row) > 2:
                        gpos = self.table.viewport().mapToGlobal(event.pos())
                        self._hover_card.show_for(row, gpos, self._db_path)
                    else:
                        self._hover_card.hide_soon()
                else:
                    self._hover_card.hide_soon()
            elif t in (QEvent.Leave, QEvent.MouseButtonPress):
                self._hover_card.hide_now()
        return super().eventFilter(obj, event)

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
            self._set_status(f"Drop a folder to scan or a .db file to open (got: {p.name})")

    # ── Shortcuts ─────────────────────────────────────────────────────────────

    def _install_shortcuts(self) -> None:
        def _mk(seq: str, slot):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(slot)
            return sc

        _mk("/",              self._focus_search)
        _mk("Ctrl+F",         self._focus_search)
        _mk("Ctrl+R",         self._toggle_folder_depth)
        _mk("Ctrl+Shift+R",   self._reveal_active_file)
        _mk("Ctrl+Shift+C",   self._copy_active_path)
        _mk("Esc",            self._on_escape)
        _mk("Ctrl+.",         self._hard_cancel)
        _mk("Ctrl+Shift+B",   self._toggle_folder_panel)
        _mk("Ctrl+Shift+D",   self._toggle_detail_panel)
        _mk("Ctrl+`",         self._toggle_console)

        for i, key in enumerate(("Ctrl+1", "Ctrl+2", "Ctrl+3")):
            _mk(key, lambda i=i: self.center_tabs.setCurrentIndex(i))

        for v in (self.table, self.grid_view, self.list_view):
            for seq in ("Return", "Enter"):
                sc = QShortcut(QKeySequence(seq), v)
                sc.setContext(Qt.WidgetShortcut)
                sc.activated.connect(self._open_active_file)
            sc_a = QShortcut(QKeySequence("Ctrl+A"), v)
            sc_a.setContext(Qt.WidgetShortcut)
            sc_a.activated.connect(v.selectAll)

    def _on_escape(self) -> None:
        busy = self._busy_workers()
        if busy:
            kinds = " and ".join(busy)
            if QMessageBox.question(
                self, "Cancel task?", f"A {kinds} is running. Cancel it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) == QMessageBox.Yes:
                self._hard_cancel()
            return
        if self.search_edit.hasFocus() and self.search_edit.text():
            self.search_edit.clear()
            return
        if self._any_filter_active():
            if QMessageBox.question(
                self, "Clear filters?", "Clear all active view filters?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) == QMessageBox.Yes:
                self._reset_all_filters()

    def _hard_cancel(self) -> None:
        if getattr(self, "_worker", None) and self._worker.isRunning():
            self._worker.stop()
        sp_worker = getattr(getattr(self, "similar_panel", None), "_worker", None)
        if sp_worker and sp_worker.isRunning():
            sp_worker.stop()
        self._set_status("Cancelling…")

    def _busy_workers(self) -> list:
        out = []
        if getattr(self, "_worker", None) and self._worker.isRunning():
            out.append("scan")
        sp_worker = getattr(getattr(self, "similar_panel", None), "_worker", None)
        if sp_worker and sp_worker.isRunning():
            out.append("similarity analysis")
        return out

    def _any_filter_active(self) -> bool:
        if self._browser_path:
            return True
        if hasattr(self, "search_edit") and self.search_edit.text().strip():
            return True
        if hasattr(self, "cat_combo") and self.cat_combo.currentText() != "All types":
            return True
        return self._count_active_view_filters() > 0

    def _reset_all_filters(self) -> None:
        self._clear_folder_filter()
        if hasattr(self, "search_edit"):
            self.search_edit.clear()
        if hasattr(self, "cat_combo"):
            self.cat_combo.setCurrentIndex(0)
        self._on_view_filters_changed({})

    def _toggle_folder_panel(self) -> None:
        if hasattr(self, "_folder_rail"):
            self._set_folder_panel_visible(not self._folder_rail.is_expanded())

    def _toggle_detail_panel(self) -> None:
        if hasattr(self, "_right_zone"):
            self._set_detail_panel_visible(not self._right_zone.is_inspector_visible())

    def _toggle_console(self) -> None:
        if hasattr(self, "_main_vsplit"):
            sizes = self._main_vsplit.sizes()
            self._set_console_visible(sizes[1] == 0)

    def _focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _open_path(self, path: str) -> None:
        """Open a file path in the OS default application."""
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            subprocess.Popen(["start", "", path], shell=True)
        else:
            subprocess.Popen(["xdg-open", path])

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

        sm = mb.addMenu("Settings")
        db_action = sm.addAction("Database…")
        db_action.triggered.connect(self._open_db_settings)

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

    def _push_recent(self, path: str) -> None:
        self.recent_dbs.push(Path(path).resolve())

    def _on_recents_changed(self) -> None:
        if hasattr(self, "_recents_strip"):
            self._refresh_recents_strip()

    def _rebuild_recent_menu(self) -> None:
        if not hasattr(self, "_recent_menu"):
            return
        self._recent_menu.clear()
        items = self.recent_dbs.items()
        active = self.recent_dbs.active()
        if not items:
            a = self._recent_menu.addAction("(none)")
            a.setEnabled(False)
            return
        for p in items:
            label = ("● " if active and p == active else "") + p.name
            act = self._recent_menu.addAction(label)
            act.setToolTip(str(p))
            act.triggered.connect(lambda _c=False, path=str(p): self._open_recent(path))
        self._recent_menu.addSeparator()
        clear = self._recent_menu.addAction("Clear Recent")
        clear.triggered.connect(self._clear_recent)

    def _open_recent(self, path: str) -> None:
        if not Path(path).exists():
            from .feedback import notify_error
            notify_error(self, "File no longer exists",
                f"The database at '{path}' was opened recently but is missing now. "
                "It may have been moved or deleted.",
                detail=path)
            self.recent_dbs.remove(path)
            return
        self.recent_dbs.push(path)
        self._load_url(active_url(path))

    def _clear_recent(self) -> None:
        from PySide6.QtCore import QSettings
        QSettings("valscanner", "ValScanner").setValue("recentDatabases", [])
        self.recent_dbs.changed.emit()

    # ── Preferences ───────────────────────────────────────────────────────────

    def _open_preferences(self) -> None:
        dlg = PreferencesDialog(self)
        dlg.settings_changed.connect(self._on_settings_changed)
        dlg.exec()

    def _on_settings_changed(self, changed: dict) -> None:
        if "defaultDbPath" in changed:
            if not self._db_url and hasattr(self, "db_edit"):
                self.db_edit.setText(changed["defaultDbPath"] or "file_index.db")
        if "computeHashesByDefault" in changed:
            self.hash_chk.setChecked(bool(changed["computeHashesByDefault"]))
        if "showConsoleOnStartup" in changed and hasattr(self, "_main_vsplit"):
            self._apply_console_visibility(bool(changed["showConsoleOnStartup"]))
        if "accentColor" in changed or "selectionColor" in changed or "selectionTextColor" in changed:
            self._apply_stylesheet()
            self._set_status("Accent colour updated.")

    def _apply_console_visibility(self, visible: bool) -> None:
        self._set_console_visible(visible)

    def _add_panel_toggles(self) -> None:
        vm = self._view_menu

        # ── Theme submenu ──────────────────────────────────────────────────
        from .theme import Theme
        theme_menu = vm.addMenu("Theme")
        ag = QActionGroup(self)
        ag.setExclusive(True)
        current = Theme.instance().current_mode()
        for label, name in (("System", "system"), ("Light", "light"), ("Dark", "dark"), ("Catppuccin", "catppuccin")):
            act = QAction(label, self, checkable=True)
            act.setChecked(current == name)
            act.triggered.connect(lambda _=False, n=name: Theme.instance().set(n))
            ag.addAction(act)
            theme_menu.addAction(act)
        self._theme_action_group = ag

        vm.addSeparator()
        s           = pref_settings()
        folder_vis  = s.value("panelFolderVisible",    True,                                   type=bool)
        detail_vis  = s.value("panelDetailVisible",    True,                                   type=bool)
        console_vis = s.value("panelConsoleVisible",   bool(pref_get("showConsoleOnStartup")),  type=bool)
        filter_vis  = s.value("panelFilterBarVisible", True,                                   type=bool)
        stats_vis   = s.value("panelStatsBarVisible",  True,                                   type=bool)
        process_vis = s.value("panelProcessVisible",   True,                                   type=bool)

        self._act_folder_panel = QAction("Folder Panel", self, checkable=True, checked=folder_vis)
        self._act_detail_panel = QAction("Inspector", self, checkable=True, checked=detail_vis)
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

        vm.addAction(self._act_folder_panel)
        vm.addAction(self._act_detail_panel)
        vm.addAction(self._act_console)
        vm.addAction(self._act_filterbar)
        vm.addAction(self._act_statsbar)
        vm.addAction(self._act_process_dock)

        if hasattr(self, "_right_zone"):
            self._right_zone.set_monitor_visible(process_vis)

    _DEFAULT_FOLDER_WIDTH  = 248
    _DEFAULT_DETAIL_WIDTH  = 320
    _DEFAULT_PROCESS_WIDTH = 296

    def _set_folder_panel_visible(self, visible: bool) -> None:
        if hasattr(self, "_folder_rail"):
            self._folder_rail.blockSignals(True)
            self._folder_rail.set_expanded(visible)
            self._folder_rail.blockSignals(False)
            if visible:
                sizes = list(self.splitter.sizes())
                from .collapsible import RAIL_W
                if sizes[0] <= RAIL_W:
                    sizes[0] = getattr(self, "_saved_folder_width", self._DEFAULT_FOLDER_WIDTH)
                    self.splitter.setSizes(sizes)
            else:
                sizes = list(self.splitter.sizes())
                from .collapsible import RAIL_W
                if sizes[0] > RAIL_W:
                    self._saved_folder_width = sizes[0]
        if hasattr(self, "_act_folder_panel"):
            self._act_folder_panel.setChecked(visible)
        pref_settings().setValue("panelFolderVisible", visible)

    def _set_detail_panel_visible(self, visible: bool) -> None:
        if hasattr(self, "_right_zone"):
            self._right_zone.set_inspector_visible(visible)
            if visible:
                sizes = list(self.splitter.sizes())
                from .collapsible import RAIL_W
                if sizes[2] <= RAIL_W:
                    default = self._DEFAULT_DETAIL_WIDTH + self._DEFAULT_PROCESS_WIDTH
                    sizes[2] = getattr(self, "_saved_rz_w", default)
                    self.splitter.setSizes(sizes)
            else:
                if not self._right_zone.is_monitor_visible():
                    sizes = list(self.splitter.sizes())
                    from .collapsible import RAIL_W
                    if sizes[2] > RAIL_W:
                        self._saved_rz_w = sizes[2]
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
        if hasattr(self, "_right_zone"):
            self._right_zone.set_monitor_visible(visible)
            if visible:
                sizes = list(self.splitter.sizes())
                from .collapsible import RAIL_W
                if sizes[2] <= RAIL_W:
                    default = self._DEFAULT_DETAIL_WIDTH + self._DEFAULT_PROCESS_WIDTH
                    sizes[2] = getattr(self, "_saved_rz_w", default)
                    self.splitter.setSizes(sizes)
            else:
                if not self._right_zone.is_inspector_visible():
                    sizes = list(self.splitter.sizes())
                    from .collapsible import RAIL_W
                    if sizes[2] > RAIL_W:
                        self._saved_rz_w = sizes[2]
        if hasattr(self, "_act_process_dock"):
            self._act_process_dock.setChecked(visible)
        pref_settings().setValue("panelProcessVisible", visible)

    def _toggle_filterbar(self, visible: bool) -> None:
        if hasattr(self, "_filterbar_container"):
            self._filterbar_container.setVisible(visible)
        else:
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
            geo    = s.value(persistence.Keys.WINDOW_GEOMETRY)
            state  = s.value(persistence.Keys.SPLITTER_STATE)
            vstate = s.value(persistence.Keys.VSPLITTER_STATE)
            if geo:
                self.restoreGeometry(geo)
            if state and hasattr(self, "splitter"):
                self.splitter.restoreState(state)
            if vstate and hasattr(self, "_main_vsplit"):
                self._main_vsplit.restoreState(vstate)

            # Restore Details / Grid / List index
            try:
                saved_idx = int(s.value(persistence.Keys.FILE_VIEW_INDEX, 0) or 0)
            except (TypeError, ValueError):
                saved_idx = 0
            if saved_idx != 0:
                btn = self._view_btn_grp.button(saved_idx)
                if btn:
                    btn.setChecked(True)
                self._current_view_index = saved_idx

            # Restore column widths / sort order
            hdr_state = s.value(persistence.Keys.FILE_TABLE_HDR)
            if hdr_state and hasattr(self, "table"):
                self.table.horizontalHeader().restoreState(hdr_state)

            # Restore rail widths as saved_* fallbacks used by set_*_panel_visible
            try:
                fw = int(s.value(persistence.Keys.FOLDER_RAIL_WIDTH, 0) or 0)
                if fw > 0:
                    self._saved_folder_width = fw
            except (TypeError, ValueError):
                pass
            try:
                dw = int(s.value(persistence.Keys.DETAIL_RAIL_WIDTH, 0) or 0)
                if dw > 0:
                    self._saved_rz_w = dw
            except (TypeError, ValueError):
                pass

        _ps = pref_settings()
        self._set_console_visible(_ps.value("panelConsoleVisible", bool(pref_get("showConsoleOnStartup")), type=bool))
        self._set_folder_panel_visible(_ps.value("panelFolderVisible", True, type=bool))
        self._set_detail_panel_visible(_ps.value("panelDetailVisible", True, type=bool))
        self._set_process_dock_visible(_ps.value("panelProcessVisible", True, type=bool))
        self._toggle_filterbar(_ps.value("panelFilterBarVisible", True, type=bool))
        self._toggle_statsbar(_ps.value("panelStatsBarVisible", True, type=bool))
        if _ps.value("dbBarCollapsed", False, type=bool):
            self._collapse_db_bar()
        if _ps.value("filterBarCollapsed", False, type=bool):
            self._collapse_filterbar()

        # Auto-connect: open recent (SQLite) or active_url() (may be PG)
        recents = self.recent_dbs.items()
        if pref_get("openLastDbOnStartup") and recents:
            QTimer.singleShot(0, lambda: self._load_url(active_url(str(recents[0]))))
        else:
            QTimer.singleShot(0, lambda: self._load_url(active_url()))

    def closeEvent(self, ev) -> None:
        busy = self._busy_workers()
        if busy:
            msg = "A " + " and a ".join(busy) + " is still running. Quit anyway?"
            if QMessageBox.question(
                self, "Quit ValScanner", msg,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                ev.ignore()
                return
        if pref_get("restoreWindowState"):
            s = pref_settings()
            s.setValue(persistence.Keys.WINDOW_GEOMETRY, self.saveGeometry())
            if hasattr(self, "splitter"):
                s.setValue(persistence.Keys.SPLITTER_STATE, self.splitter.saveState())
            if hasattr(self, "_main_vsplit"):
                s.setValue(persistence.Keys.VSPLITTER_STATE, self._main_vsplit.saveState())
            s.setValue(persistence.Keys.FILE_VIEW_INDEX, self._current_view_index)
            if hasattr(self, "table"):
                s.setValue(persistence.Keys.FILE_TABLE_HDR,
                           self.table.horizontalHeader().saveState())
            if hasattr(self, "scans_panel"):
                self.scans_panel._persist_header()
            if hasattr(self, "splitter") and hasattr(self, "_folder_rail"):
                sizes = self.splitter.sizes()
                from .collapsible import RAIL_W
                if sizes[0] > RAIL_W:
                    s.setValue(persistence.Keys.FOLDER_RAIL_WIDTH, sizes[0])
            if hasattr(self, "splitter") and hasattr(self, "_right_zone"):
                sizes = self.splitter.sizes()
                from .collapsible import RAIL_W
                if sizes[2] > RAIL_W:
                    s.setValue(persistence.Keys.DETAIL_RAIL_WIDTH, sizes[2])
        _ps = pref_settings()
        _ps.setValue("panelFolderVisible",
                     self._folder_rail.is_expanded() if hasattr(self, "_folder_rail") else True)
        _ps.setValue("panelDetailVisible",
                     self._right_zone.is_inspector_visible() if hasattr(self, "_right_zone") else True)
        _ps.setValue("panelProcessVisible",
                     self._right_zone.is_monitor_visible() if hasattr(self, "_right_zone") else True)
        _ps.setValue("panelConsoleVisible",   (self._main_vsplit.sizes()[1] > 0) if hasattr(self, "_main_vsplit") else False)
        _ps.setValue("panelFilterBarVisible", self._filterbar.isVisible()   if hasattr(self, "_filterbar")   else True)
        _ps.setValue("panelStatsBarVisible",  self._statsbar.isVisible()    if hasattr(self, "_statsbar")    else True)
        super().closeEvent(ev)

    def _refresh_recents_strip(self) -> None:
        while self._recents_lay.count():
            item = self._recents_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        items  = self.recent_dbs.items()
        active = self.recent_dbs.active()
        if not items:
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
        active_ss = (
            f"QPushButton{{background:{GREEN:11};color:{GREEN};"
            f"border:1px solid {GREEN:44};border-radius:12px;padding:4px 12px;font-size:11px;}}"
            f"QPushButton:hover{{border-color:{GREEN};background:{GREEN:22};}}"
        )
        for p in items:
            is_active = active is not None and p == active
            label = ("● " if is_active else "") + p.name
            chip = QPushButton(label)
            chip.setIcon(_icons.icon("open", color=str(GREEN if is_active else SUBTEXT)))
            chip.setIconSize(QSize(14, 14))
            chip.setToolTip(str(p))
            chip.setStyleSheet(active_ss if is_active else chip_ss)
            chip.clicked.connect(lambda _c=False, path=str(p): self._open_recent(path))
            chip_row.addWidget(chip)
        container = QWidget()
        container.setLayout(chip_row)
        self._recents_lay.addWidget(container)

    # ── Button factories ──────────────────────────────────────────────────────

    @staticmethod
    def _apply_icon(b: QPushButton, icon: str | None, color: str | None, size: int = 16) -> None:
        if not icon:
            return
        b.setIcon(_icons.icon(icon, color=color) if color else _icons.icon(icon))
        b.setIconSize(QSize(size, size))

    def _btn_primary(self, text: str, tooltip: str = "", icon: str | None = None) -> QPushButton:
        b = QPushButton(text); b.setToolTip(tooltip)
        b.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; color: white; border: none;
                border-radius: 7px; padding: 6px 16px; font-weight: 600; font-size: 12px;
            }}
            QPushButton:hover    {{ background: {BTN_HOVER}; }}
            QPushButton:pressed  {{ background: {BTN_PRESSED}; }}
            QPushButton:disabled {{ background: {BORDER}; color: {SUBTEXT}; }}
        """)
        self._apply_icon(b, icon, "#ffffff")
        return b

    def _btn_secondary(self, text: str, tooltip: str = "", icon: str | None = None) -> QPushButton:
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
        self._apply_icon(b, icon, str(TEXT))
        return b

    def _btn_danger(self, text: str, tooltip: str = "", icon: str | None = None) -> QPushButton:
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
        self._apply_icon(b, icon, str(RED))
        return b

    def _btn_ghost(self, text: str, tooltip: str = "", icon: str | None = None) -> QPushButton:
        b = QPushButton(text); b.setToolTip(tooltip)
        b.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {SUBTEXT}; border: none;
                border-radius: 5px; padding: 4px 8px; font-size: 11px;
            }}
            QPushButton:hover   {{ color: {TEXT}; background: {PANEL_BG}; }}
            QPushButton:pressed {{ color: {ACCENT}; }}
        """)
        self._apply_icon(b, icon, str(SUBTEXT), size=14)
        return b

    @staticmethod
    def _icon_label(name: str, size: int, color: str | None = None) -> QLabel:
        """Create a label that displays a vector icon as a pixmap."""
        lbl = QLabel()
        lbl.setPixmap(_icons.pixmap(name, size, color=color))
        lbl.setFixedSize(size, size)
        lbl.setAlignment(Qt.AlignCenter)
        return lbl

    # ── Main UI ───────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central  = QWidget()
        self.setCentralWidget(central)
        root_lay = QVBoxLayout(central)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        # Never let children's min/max size cascade into the window — toggling
        # collapse states should not resize the main window.
        root_lay.setSizeConstraint(QLayout.SetNoConstraint)
        # Allow the window to shrink as small as the user wants; clamp only at
        # the QMainWindow level.
        self.setMinimumSize(640, 400)

        root_lay.addWidget(self._build_toolbar())
        root_lay.addWidget(self._build_queue_strip())

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

        self._add_panel_toggles()

        sb = QStatusBar()
        sb.setFixedHeight(26)
        sb.setSizeGripEnabled(False)
        sb.setStyleSheet(
            f"QStatusBar {{ background: {DARK_BG}; color: {SUBTEXT}; font-size: 11px; }}"
            f"QStatusBar::item {{ border: none; }}"
        )
        self.setStatusBar(sb)
        self.status = sb

        # Left: dot + persistent status label (replaces showMessage to keep them visible)
        left = QWidget()
        ll = QHBoxLayout(left)
        ll.setContentsMargins(8, 0, 0, 0)
        ll.setSpacing(8)
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(8, 8)
        self._status_dot.setStyleSheet(
            f"background: {GREEN}; border-radius: 4px;"
        )
        ll.addWidget(self._status_dot)
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 11px;"
        )
        ll.addWidget(self._status_lbl)
        sb.addWidget(left, 1)

        self._task_pill = self._build_task_pill()
        sb.addPermanentWidget(self._task_pill)

        # Mono clock on right
        self._status_clock = QLabel()
        self._status_clock.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; padding: 0 12px 0 8px;"
            f"font-family: '{mono_font_family()}', monospace;"
        )
        sb.addPermanentWidget(self._status_clock)
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()

        ProcessRegistry.instance().add_listener(self._update_task_pill)
        self._set_status("Open a database or scan a folder to get started.  "
                         "  Ctrl+O = Open DB  ·  Ctrl+Shift+S = Scan")

    def _tick_clock(self) -> None:
        if hasattr(self, "_status_clock"):
            from datetime import datetime
            self._status_clock.setText(datetime.now().strftime("%H:%M:%S"))

    def _build_toolbar(self) -> QWidget:
        bar   = QWidget()
        self._toolbar = bar
        bar.setStyleSheet(f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        r1 = QWidget()
        self._toolbar_r1 = r1
        r1.setStyleSheet(f"background: {PANEL_BG};")
        r1.setFixedHeight(52)
        rl = QHBoxLayout(r1)
        rl.setContentsMargins(14, 0, 14, 0)
        rl.setSpacing(10)

        # Brand mark + name + version tag
        brand = self._build_brand_mark()
        rl.addWidget(brand)

        sep = QFrame(); sep.setFrameShape(QFrame.VLine)
        sep.setFixedHeight(22)
        sep.setStyleSheet(f"color: {BORDER}; background: {BORDER};")
        rl.addWidget(sep)

        scan_lbl = QLabel("Scan")
        scan_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; font-weight: 500;"
            f"letter-spacing: 0.04em; text-transform: uppercase;"
        )
        rl.addWidget(scan_lbl)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Pick a folder to index…")
        self.path_edit.setMinimumWidth(260)
        self.path_edit.setFixedHeight(28)
        self.path_edit.addAction(_icons.icon("folder", color=str(SUBTEXT)), QLineEdit.LeadingPosition)
        self.path_edit.returnPressed.connect(self._start_scan)
        rl.addWidget(self.path_edit, 1)

        browse_scan_btn = self._btn_secondary("Browse", "Choose folder to scan (Ctrl+Shift+S)")
        browse_scan_btn.setFixedHeight(28)
        browse_scan_btn.clicked.connect(self._browse_scan)
        rl.addWidget(browse_scan_btn)

        label_lbl = QLabel("Label")
        label_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; font-weight: 500;"
            f"letter-spacing: 0.04em; text-transform: uppercase;"
        )
        rl.addWidget(label_lbl)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("Aurora — Q4 Reshoot")
        self.label_edit.setFixedWidth(170)
        self.label_edit.setFixedHeight(28)
        self.label_edit.setToolTip("Optional name for this scan")
        rl.addWidget(self.label_edit)

        self.hash_chk = QCheckBox("SHA-256")
        self.hash_chk.setChecked(False)
        self.hash_chk.setToolTip("Compute file hashes — enables exact duplicate detection")
        self.hash_chk.setStyleSheet(
            f"QCheckBox {{ color: {SUBTEXT}; spacing: 6px; font-size: 11px; }}"
            f"QCheckBox:checked {{ color: {TEXT}; }}"
            f"QCheckBox::indicator {{"
            f"  width: 14px; height: 14px; border: 1px solid {DIVIDER3};"
            f"  border-radius: 3px; background: {DARK_BG};"
            f"}}"
            f"QCheckBox::indicator:hover   {{ border-color: {ACCENT}; }}"
            f"QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}"
        )
        rl.addWidget(self.hash_chk)

        rl.addStretch(1)

        # DB chip — shown only when Toolbar2 is collapsed
        self._db_chip = self._build_db_chip()
        self._db_chip.hide()
        rl.addWidget(self._db_chip)

        self.options_btn = self._btn_secondary("Options", "Configure scan options", icon="options")
        self.options_btn.setFixedHeight(28)
        self.options_btn.clicked.connect(self._open_scan_options)
        rl.addWidget(self.options_btn)

        self.scan_btn = self._btn_primary("Scan", "Start scanning (Enter)", icon="scan")
        self.scan_btn.setFixedWidth(110)
        self.scan_btn.setFixedHeight(28)
        self.scan_btn.clicked.connect(self._start_scan)
        rl.addWidget(self.scan_btn)
        outer.addWidget(r1)

        r2 = QWidget()
        self._toolbar_r2 = r2
        r2.setStyleSheet(f"background: {DARK_BG}; border-bottom: 1px solid {BORDER};")
        r2.setFixedHeight(38)
        rl2 = QHBoxLayout(r2)
        rl2.setContentsMargins(14, 0, 8, 0)
        rl2.setSpacing(10)

        db_icon = self._icon_label("database", 14, color=str(SUBTEXT))
        rl2.addWidget(db_icon)
        db_lbl = QLabel("Database")
        db_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; font-weight: 500;"
            f"letter-spacing: 0.04em; text-transform: uppercase;"
        )
        rl2.addWidget(db_lbl)

        self.db_edit = QLineEdit("file_index.db")
        self.db_edit.setPlaceholderText("Path to .db file…")
        self.db_edit.setMinimumWidth(280)
        self.db_edit.setFixedHeight(24)
        self.db_edit.setStyleSheet(
            f"QLineEdit {{ background:{DARK_BG}; color:{TEXT}; border:1px solid {DIVIDER2};"
            f"border-radius:5px; padding:2px 8px; font-size:11px;"
            f"font-family: '{mono_font_family()}', monospace; }}"
            f"QLineEdit:focus {{ border-color:{ACCENT}; }}"
        )
        rl2.addWidget(self.db_edit)

        browse_db_btn = self._btn_ghost("", "Browse for database save location", icon="browse")
        browse_db_btn.setFixedSize(26, 26)
        browse_db_btn.clicked.connect(self._browse_db_save)
        rl2.addWidget(browse_db_btn)

        open_db_btn = self._btn_ghost("Open existing DB", "Load a previously saved database (Ctrl+O)", icon="open")
        open_db_btn.clicked.connect(self._open_db)
        rl2.addWidget(open_db_btn)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.VLine)
        sep2.setFixedHeight(20)
        sep2.setStyleSheet(f"color: {BORDER}; background: {BORDER};")
        rl2.addWidget(sep2)

        self.csv_btn  = self._btn_ghost("CSV",  "Export results to CSV (Ctrl+E)",      icon="export-csv")
        self.json_btn = self._btn_ghost("JSON", "Export results to JSON (Ctrl+Shift+E)", icon="export-json")
        self.csv_btn.clicked.connect(self._export_csv)
        self.json_btn.clicked.connect(self._export_json)
        self.csv_btn.setEnabled(False)
        self.json_btn.setEnabled(False)
        rl2.addWidget(self.csv_btn); rl2.addWidget(self.json_btn)
        rl2.addStretch()

        self.db_status_lbl = QLabel("No database loaded")
        self.db_status_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; background: {PANEL_BG}; "
            f"border: 1px solid {DIVIDER2}; border-radius: 4px; padding: 2px 10px;"
            f"font-family: '{mono_font_family()}', monospace;"
        )
        self.db_status_lbl.setMaximumHeight(24)
        rl2.addWidget(self.db_status_lbl, 0, Qt.AlignVCenter)

        # Chevron-up collapse handle
        self._db_collapse_btn = QPushButton()
        self._db_collapse_btn.setIcon(_icons.icon("mdi.chevron-up", color=str(SUBTEXT)))
        self._db_collapse_btn.setIconSize(QSize(14, 14))
        self._db_collapse_btn.setFixedSize(24, 24)
        self._db_collapse_btn.setToolTip("Collapse database bar")
        self._db_collapse_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;border-radius:4px;}}"
            f"QPushButton:hover{{background:{BG2};}}"
        )
        self._db_collapse_btn.clicked.connect(self._collapse_db_bar)
        rl2.addWidget(self._db_collapse_btn)

        outer.addWidget(r2)
        return bar

    def _build_brand_mark(self) -> QWidget:
        """Compact brand chip — amber crosshair square + name + version tag."""
        w = QWidget()
        wl = QHBoxLayout(w)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(10)

        mark = QLabel()
        mark.setFixedSize(28, 28)
        mark.setAlignment(Qt.AlignCenter)
        mark.setPixmap(_icons.pixmap("mdi.crosshairs-gps", 16, color=str(ACCENT)))
        mark.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 #2a1f0f, stop:1 #1a1308);"
            f"border: 1px solid #3a2c14; border-radius: 6px;"
        )
        wl.addWidget(mark)

        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        name = QLabel("ValScanner")
        name.setStyleSheet(f"color: {TEXT}; font-size: 14px; font-weight: 700;")
        ver = QLabel("v2.4 · field")
        ver.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 9px; letter-spacing: 0.04em;"
            f"font-family: '{mono_font_family()}', monospace;"
        )
        cl.addWidget(name); cl.addWidget(ver)
        wl.addWidget(col)
        return w

    def _build_db_chip(self) -> QPushButton:
        """Compact DB chip shown in Toolbar1 when Toolbar2 is collapsed."""
        btn = QPushButton("  no database  ")
        btn.setFixedHeight(28)
        btn.setIcon(_icons.icon("database", color=str(SUBTEXT)))
        btn.setIconSize(QSize(13, 13))
        btn.setToolTip("Expand database bar")
        btn.setStyleSheet(
            f"QPushButton{{background:{DARK_BG};color:{TEXT};"
            f"border:1px solid {DIVIDER2};border-radius:6px;"
            f"padding:0 10px;font-size:11px;"
            f"font-family: '{mono_font_family()}', monospace;}}"
            f"QPushButton:hover{{border-color:{ACCENT}; background:{PANEL_BG};}}"
        )
        btn.clicked.connect(self._expand_db_bar)
        return btn

    def _collapse_db_bar(self) -> None:
        self._toolbar_r2.hide()
        # Update chip label to current db name
        name = Path(self._db_path).name if self._db_path else "no database"
        self._db_chip.setText(f"  {name}  ")
        self._db_chip.show()
        pref_settings().setValue("dbBarCollapsed", True)

    def _expand_db_bar(self) -> None:
        self._db_chip.hide()
        self._toolbar_r2.show()
        pref_settings().setValue("dbBarCollapsed", False)

    def _build_queue_strip(self) -> QWidget:
        self._queue_strip = QWidget()
        self._queue_strip.setFixedHeight(26)
        self._queue_strip.setStyleSheet(
            f"background: {DARK_BG}; border-bottom: 1px solid {BORDER};"
        )
        ql = QHBoxLayout(self._queue_strip)
        ql.setContentsMargins(14, 0, 14, 0)
        ql.setSpacing(10)

        queue_icon = QLabel("◎")
        queue_icon.setStyleSheet(f"color: {ACCENT}; font-size: 10px;")
        ql.addWidget(queue_icon)

        self._queue_status_lbl = QLabel()
        self._queue_status_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        ql.addWidget(self._queue_status_lbl, 1)

        self._clear_queue_btn = QPushButton("Clear queue")
        self._clear_queue_btn.setFlat(True)
        self._clear_queue_btn.setCursor(Qt.PointingHandCursor)
        self._clear_queue_btn.setStyleSheet(
            f"QPushButton{{color:{SUBTEXT};font-size:11px;border:none;padding:0;}}"
            f"QPushButton:hover{{color:{TEXT};}}"
        )
        self._clear_queue_btn.clicked.connect(self._clear_queue)
        ql.addWidget(self._clear_queue_btn)

        self._queue_strip.hide()
        return self._queue_strip

    def _refresh_queue_strip(self) -> None:
        if not self._scan_queue:
            self._queue_strip.hide()
            return
        n = len(self._scan_queue)
        names = [Path(item["root"]).name for item in self._scan_queue[:3]]
        preview = "  ·  ".join(names)
        if n > 3:
            preview += f"  ·  +{n - 3} more"
        self._queue_status_lbl.setText(f"{n} pending:  {preview}")
        self._queue_strip.show()

    # ── Filter bar (Files tab) ───────────────────────────────────────────────

    def _build_filterbar_container(self) -> QWidget:
        """Outer wrapper that swaps between expanded filterbar and a collapsed strip."""
        self._filterbar_container = QWidget()
        cl = QVBoxLayout(self._filterbar_container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._build_filterbar())
        cl.addWidget(self._build_filterbar_strip())
        self._filterbar_strip.hide()
        return self._filterbar_container

    def _build_filterbar(self) -> QWidget:
        self._filterbar = QWidget()
        self._filterbar.setStyleSheet(
            f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )
        self._filterbar.setMinimumHeight(46)
        fl = QHBoxLayout(self._filterbar)
        fl.setContentsMargins(14, 8, 14, 8)
        fl.setSpacing(8)

        # ── Search input ───────────────────────────────────────────────────
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filename, tag, EXIF, path…")
        self.search_edit.addAction(_icons.icon("search", color=str(SUBTEXT)), QLineEdit.LeadingPosition)
        self.search_edit.setMinimumWidth(180)
        self.search_edit.setMaximumWidth(260)
        self.search_edit.setFixedHeight(30)
        self.search_edit.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._apply_filters)
        self.search_edit.textChanged.connect(lambda _t: self._search_timer.start())
        self.search_edit.setStyleSheet(
            f"QLineEdit {{ background:{DARK_BG}; color:{TEXT}; border:1px solid {DIVIDER2};"
            f"border-radius:8px; padding:0 10px; font-size:12px; }}"
            f"QLineEdit:focus {{ border-color:{ACCENT}; background:{PANEL_BG}; }}"
        )
        fl.addWidget(self.search_edit)

        # ── Grouped Filter cluster ─────────────────────────────────────────
        fb_group = QWidget()
        fb_group.setStyleSheet(
            f"QWidget#fbGroup{{background:{DARK_BG};border:1px solid {DIVIDER2};"
            f"border-radius:7px;}}"
        )
        fb_group.setObjectName("fbGroup")
        fb_group.setFixedHeight(32)
        fgl = QHBoxLayout(fb_group)
        fgl.setContentsMargins(8, 0, 4, 0)
        fgl.setSpacing(4)

        grp_lbl = QLabel("FILTER")
        grp_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 9px; font-weight: 500;"
            f"letter-spacing: 0.06em; padding-right: 4px;"
            f"border-right: 1px solid {DIVIDER2};"
        )
        grp_lbl.setFixedHeight(24)
        grp_lbl.setAlignment(Qt.AlignCenter)
        fgl.addWidget(grp_lbl)

        _combo_ss = (
            f"QComboBox{{background:transparent;color:{TEXT};border:0;"
            f"padding:0 6px;font-size:11px;}}"
            f"QComboBox:hover{{color:{ACCENT};}}"
            f"QComboBox::drop-down{{border:0;width:14px;}}"
            f"QComboBox::down-arrow{{image:none;}}"
            f"QComboBox QAbstractItemView{{background:{PANEL_BG};"
            f"color:{TEXT};border:1px solid {DIVIDER2};"
            f"selection-background-color:{ACCENT}; padding:4px;}}"
        )

        self.scan_combo = QComboBox()
        self.scan_combo.setStyleSheet(_combo_ss)
        self.scan_combo.setFixedHeight(24)
        self.scan_combo.addItem("All scans", userData=0)
        self.scan_combo.currentIndexChanged.connect(self._on_scan_filter_changed)
        self.scan_combo.setFixedWidth(110)
        fgl.addWidget(self.scan_combo)

        self.cat_combo = QComboBox()
        self.cat_combo.setStyleSheet(_combo_ss)
        self.cat_combo.setFixedHeight(24)
        self.cat_combo.addItem("All types")
        for cat in sorted(CATEGORY_COLORS.keys()):
            self.cat_combo.addItem(cat)
        self.cat_combo.currentTextChanged.connect(self._apply_filters)
        self.cat_combo.setFixedWidth(95)
        fgl.addWidget(self.cat_combo)

        self.sort_combo = QComboBox()
        self.sort_combo.setStyleSheet(_combo_ss)
        self.sort_combo.setFixedHeight(24)
        self.sort_combo.addItems(["Name ↑", "Size ↓", "Modified ↓", "Category"])
        self.sort_combo.currentIndexChanged.connect(self._apply_sort)
        self.sort_combo.setFixedWidth(100)
        fgl.addWidget(self.sort_combo)

        self._vf_btn = QPushButton()
        self._vf_btn.setIcon(_icons.icon("filters", color=str(SUBTEXT)))
        self._vf_btn.setIconSize(QSize(13, 13))
        self._vf_btn.setFixedSize(26, 24)
        self._vf_btn.setToolTip("View filters (advanced)")
        self._vf_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{SUBTEXT};border:0;border-radius:4px;}}"
            f"QPushButton:hover{{color:{TEXT};background:{BG2};}}"
            f"QPushButton[active=true]{{color:{ACCENT};background:{ACCENT:22};}}"
        )
        self._vf_btn.clicked.connect(self._open_view_filters)
        fgl.addWidget(self._vf_btn)

        self._group_combo = QComboBox()
        self._group_combo.setStyleSheet(_combo_ss)
        self._group_combo.setFixedHeight(24)
        self._group_combo.addItems(["No group", "Category", "Extension", "Folder", "Date"])
        self._group_combo.setFixedWidth(100)
        self._group_combo.setToolTip("Group files in the Details view")
        self._group_combo.currentIndexChanged.connect(self._on_group_changed)
        fgl.addWidget(self._group_combo)

        fl.addWidget(fb_group)

        # ── Active pills (inline) ──────────────────────────────────────────
        self.folder_pill = QWidget()
        self.folder_pill.setStyleSheet(
            f"background: {ACCENT:22}; border: 1px solid {ACCENT:6a}; border-radius: 11px;"
        )
        self.folder_pill.setFixedHeight(22)
        pill_lay = QHBoxLayout(self.folder_pill)
        pill_lay.setContentsMargins(9, 0, 4, 0)
        pill_lay.setSpacing(5)
        pill_icon = self._icon_label("folder-open", 11, color=str(ACCENT))
        pill_lay.addWidget(pill_icon)
        self.folder_pill_lbl = QLabel()
        self.folder_pill_lbl.setStyleSheet(
            f"color: {ACCENT}; font-size: 10.5px; border: none; background: transparent;"
            f"font-family: '{mono_font_family()}', monospace;"
        )
        pill_lay.addWidget(self.folder_pill_lbl)
        dismiss_pill = QPushButton()
        dismiss_pill.setIcon(_icons.icon("close", color=str(ACCENT)))
        dismiss_pill.setIconSize(QSize(10, 10))
        dismiss_pill.setFixedSize(16, 16)
        dismiss_pill.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; padding: 0; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {ACCENT:33}; }}"
        )
        dismiss_pill.clicked.connect(self._clear_folder_filter)
        pill_lay.addWidget(dismiss_pill)
        self.folder_pill.hide()
        fl.addWidget(self.folder_pill)

        # ── Inline scan progress (right-aligned, becomes visible during scan)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedSize(140, 4)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            f"QProgressBar {{ border: none; background: {DARK_BG}; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}"
        )
        self.progress.hide()
        fl.addWidget(self.progress)

        self.elapsed_lbl = QLabel()
        self.elapsed_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; font-family: '{mono_font_family()}', monospace;"
        )
        self.elapsed_lbl.setFixedWidth(54)
        self.elapsed_lbl.hide()
        fl.addWidget(self.elapsed_lbl)

        fl.addStretch(1)

        # ── Right cluster: Browse toggle | View segment | Clear all | ▲ ────
        _vbtn_ss = (
            f"QPushButton{{background:transparent;color:{SUBTEXT};border:1px solid {DIVIDER2};"
            f"border-radius:5px;padding:0 9px;font-size:11px;}}"
            f"QPushButton:checked{{background:{ACCENT:22};color:{ACCENT};border-color:{ACCENT};}}"
            f"QPushButton:hover:!checked{{color:{TEXT};border-color:{DIVIDER3};}}"
        )

        # density buttons live in a hidden group (still accessible via View menu)
        self._density_btn_grp = QButtonGroup(self._filterbar)
        self._density_btn_grp.setExclusive(True)
        for _di, (_dn, _dl, _dt) in enumerate([
            ("compact", "S", "Compact rows (26 px)"),
            ("normal",  "M", "Normal rows (32 px)"),
            ("relaxed", "L", "Relaxed rows (38 px)"),
        ]):
            _db = QPushButton(_dl)
            _db.setToolTip(_dt)
            _db.setCheckable(True)
            _db.setFixedSize(26, 26)
            _db.setStyleSheet(_vbtn_ss)
            _db.hide()  # accessible via View > Density menu, not in filterbar
            if _dn == _density.get_density():
                _db.setChecked(True)
            self._density_btn_grp.addButton(_db, _di)
        self._density_btn_grp.idClicked.connect(self._on_density_id_clicked)

        # View segmented control (Details / Grid / List)
        view_seg = QWidget()
        view_seg.setStyleSheet(
            f"QWidget#viewSeg{{border:1px solid {DIVIDER2};border-radius:5px;background:transparent;}}"
        )
        view_seg.setObjectName("viewSeg")
        view_seg.setFixedHeight(26)
        vsl = QHBoxLayout(view_seg)
        vsl.setContentsMargins(0, 0, 0, 0)
        vsl.setSpacing(0)

        _seg_ss_inner = (
            f"QPushButton{{background:transparent;color:{SUBTEXT};border:0;border-radius:0;"
            f"padding:0 10px;font-size:11px;height:24px;}}"
            f"QPushButton:checked{{background:{ACCENT:22};color:{ACCENT};}}"
            f"QPushButton:hover:!checked{{color:{TEXT};}}"
        )

        self._view_btn_grp = QButtonGroup(self._filterbar)
        self._view_btn_grp.setExclusive(True)
        for i, (label, tip, icon_name) in enumerate([
            ("Details", "Full details table",       "view-table"),
            ("Grid",    "Icon / thumbnail grid",    "view-grid"),
            ("List",    "Compact single-line list", "view-list"),
        ]):
            b = QPushButton()
            b.setIcon(_icons.icon(icon_name, color=str(SUBTEXT)))
            b.setIconSize(QSize(14, 14))
            b.setToolTip(f"{label} — {tip}")
            b.setCheckable(True)
            b.setFixedSize(28, 24)
            b.setStyleSheet(_seg_ss_inner)
            if i == 0:
                b.setChecked(True)
            if i > 0:
                _div = QFrame(); _div.setFrameShape(QFrame.VLine)
                _div.setFixedWidth(1)
                _div.setStyleSheet(f"background:{DIVIDER2};color:{DIVIDER2};")
                vsl.addWidget(_div)
            self._view_btn_grp.addButton(b, i)
            vsl.addWidget(b)
        self._view_btn_grp.idClicked.connect(self._set_view_mode)
        fl.addWidget(view_seg)

        clear_btn = self._btn_ghost("Clear")
        clear_btn.setFixedHeight(26)
        clear_btn.clicked.connect(self._clear_filters)
        fl.addWidget(clear_btn)

        self._fb_collapse_btn = QPushButton()
        self._fb_collapse_btn.setIcon(_icons.icon("mdi.chevron-up", color=str(SUBTEXT)))
        self._fb_collapse_btn.setIconSize(QSize(14, 14))
        self._fb_collapse_btn.setFixedSize(24, 26)
        self._fb_collapse_btn.setToolTip("Collapse filter bar")
        self._fb_collapse_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;border-radius:4px;}}"
            f"QPushButton:hover{{background:{BG2};}}"
        )
        self._fb_collapse_btn.clicked.connect(self._collapse_filterbar)
        fl.addWidget(self._fb_collapse_btn)

        # depth-seg lives in the crumbs row, built lazily
        self._depth_seg_ctrl = self._build_depth_seg()

        return self._filterbar

    def _build_filterbar_strip(self) -> QWidget:
        """Thin strip shown when the filter bar is collapsed."""
        self._filterbar_strip = QWidget()
        self._filterbar_strip.setStyleSheet(
            f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )
        self._filterbar_strip.setFixedHeight(30)
        sl = QHBoxLayout(self._filterbar_strip)
        sl.setContentsMargins(14, 0, 14, 0)
        sl.setSpacing(10)

        funnel = self._icon_label("filters", 12, color=str(SUBTEXT))
        sl.addWidget(funnel)

        self._fb_strip_summary = QLabel("Filters · 0 active")
        self._fb_strip_summary.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 11px;"
        )
        sl.addWidget(self._fb_strip_summary)
        sl.addStretch(1)

        expand_btn = QPushButton("Expand filters")
        expand_btn.setIcon(_icons.icon("mdi.chevron-down", color=str(SUBTEXT)))
        expand_btn.setIconSize(QSize(12, 12))
        expand_btn.setFixedHeight(22)
        expand_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{SUBTEXT};"
            f"border:1px solid {DIVIDER2};border-radius:4px;padding:0 10px;font-size:11px;}}"
            f"QPushButton:hover{{color:{ACCENT};border-color:{ACCENT};background:{ACCENT:22};}}"
        )
        expand_btn.clicked.connect(self._expand_filterbar)
        sl.addWidget(expand_btn)
        return self._filterbar_strip

    def _collapse_filterbar(self) -> None:
        self._filterbar.hide()
        self._filterbar_strip.show()
        self._update_filterbar_summary()
        pref_settings().setValue("filterBarCollapsed", True)

    def _expand_filterbar(self) -> None:
        self._filterbar_strip.hide()
        self._filterbar.show()
        pref_settings().setValue("filterBarCollapsed", False)

    def _update_filterbar_summary(self) -> None:
        if not hasattr(self, "_fb_strip_summary"):
            return
        n = 0
        if hasattr(self, "search_edit") and self.search_edit.text().strip():
            n += 1
        if hasattr(self, "cat_combo") and self.cat_combo.currentText() != "All types":
            n += 1
        if hasattr(self, "scan_combo") and self.scan_combo.currentIndex() != 0:
            n += 1
        if hasattr(self, "_group_by") and self._group_by:
            n += 1
        n += self._count_active_view_filters()
        if self._browser_path:
            n += 1
        self._fb_strip_summary.setText(f"Filters · {n} active")

    def _build_depth_seg(self) -> QWidget:
        """Segmented control for folder-filter depth: This folder / + subfolders."""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        seg_ss = (
            f"QPushButton{{background:{PANEL_BG};color:{SUBTEXT};border:1px solid {BORDER};"
            f"padding:2px 9px;font-size:11px;}}"
            f"QPushButton:checked{{background:{ACCENT:22};color:{ACCENT};border-color:{ACCENT};}}"
            f"QPushButton:hover:!checked{{color:{TEXT};}}"
        )
        left_ss  = seg_ss + "QPushButton{border-radius:0;border-top-left-radius:5px;border-bottom-left-radius:5px;}"
        right_ss = seg_ss + "QPushButton{border-radius:0;border-top-right-radius:5px;border-bottom-right-radius:5px;border-left:none;}"

        self._depth_this_btn = QPushButton("This folder")
        self._depth_this_btn.setCheckable(True)
        self._depth_this_btn.setChecked(True)
        self._depth_this_btn.setFixedHeight(22)
        self._depth_this_btn.setStyleSheet(left_ss)
        self._depth_this_btn.setToolTip("Show only direct children of this folder  (Ctrl+R)")
        self._depth_this_btn.setAccessibleName("Filter: this folder only")

        self._depth_sub_btn = QPushButton("+ subfolders")
        self._depth_sub_btn.setCheckable(True)
        self._depth_sub_btn.setFixedHeight(22)
        self._depth_sub_btn.setStyleSheet(right_ss)
        self._depth_sub_btn.setToolTip("Show all files in this folder and descendants  (Ctrl+R)")
        self._depth_sub_btn.setAccessibleName("Filter: include subfolders")

        self._depth_grp = QButtonGroup(w)
        self._depth_grp.setExclusive(True)
        self._depth_grp.addButton(self._depth_this_btn, 0)
        self._depth_grp.addButton(self._depth_sub_btn, 1)
        self._depth_grp.idClicked.connect(self._on_depth_seg_clicked)

        lay.addWidget(self._depth_this_btn)
        lay.addWidget(self._depth_sub_btn)
        return w

    def _build_body(self) -> QSplitter:
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(1)

        self.folder_panel = FolderPanel()
        self.folder_panel.setMinimumWidth(180)
        self.folder_panel.folder_selected.connect(self._filter_by_folder)
        self._folder_rail = CollapsiblePanel(
            "Folders", self.folder_panel, border_side="right", icon_name="folder"
        )
        self._folder_rail.toggled.connect(self._set_folder_panel_visible)
        self.folder_panel.add_header_button(self._folder_rail.collapse_button)
        self.splitter.addWidget(self._folder_rail)

        self.center_tabs = QTabWidget()
        self.center_tabs.setDocumentMode(True)

        self._welcome_widget = self._build_welcome()
        self.center_tabs.addTab(self._welcome_widget, "")
        self.center_tabs.tabBar().hide()

        file_tab = QWidget()
        ftl      = QVBoxLayout(file_tab)
        ftl.setContentsMargins(0, 0, 0, 0)
        ftl.setSpacing(0)

        # Filter bar lives inside the Files tab (per design)
        ftl.addWidget(self._build_filterbar_container())

        # Breadcrumb bar (visible only in browser mode)
        self._breadcrumb_bar = QWidget()
        self._breadcrumb_bar.setStyleSheet(
            f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )
        self._breadcrumb_bar.setFixedHeight(36)
        self._breadcrumb_lay = QHBoxLayout(self._breadcrumb_bar)
        self._breadcrumb_lay.setContentsMargins(14, 0, 14, 0)
        self._breadcrumb_lay.setSpacing(4)
        self._breadcrumb_lay.addStretch()
        self._breadcrumb_lay.addWidget(self._depth_seg_ctrl)
        ftl.addWidget(self._breadcrumb_bar)

        self._view_stack = QStackedWidget()

        self.table_model = FileTableModel()
        self.table       = QTableView()
        self.table.setModel(self.table_model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(_density.get_row_height())
        self.table.horizontalHeader().setHighlightSections(False)
        for col, mode in [
            (COL_IDX["Filename"], QHeaderView.ResizeToContents),
            (COL_IDX["Category"], QHeaderView.ResizeToContents),
            (COL_IDX["Size"],     QHeaderView.ResizeToContents),
            (COL_IDX["Modified"], QHeaderView.ResizeToContents),
            (COL_IDX["Hash"],     QHeaderView.Fixed),
            (COL_IDX["Tags"],     QHeaderView.Stretch),
            (COL_IDX["Path"],     QHeaderView.ResizeToContents),
        ]:
            self.table.horizontalHeader().setSectionResizeMode(col, mode)
        self.table.setColumnWidth(COL_IDX["Hash"], 100)
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

        self._hover_card = HoverPeekCard()
        self.table.viewport().installEventFilter(self)

        self.icon_model = FileIconModel()
        self.grid_view  = QListView()
        self.grid_view.setModel(self.icon_model)
        self.grid_view.setViewMode(QListView.IconMode)
        self.grid_view.setResizeMode(QListView.Adjust)
        self.grid_view.setUniformItemSizes(True)
        self.grid_view.setSpacing(2)
        _card = FileCardDelegate()
        self.grid_view.setItemDelegate(_card)
        self.grid_view.setGridSize(QSize(_card.W, _card.H))
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

        self.empty_state = self._build_empty_state()
        self._view_stack.addWidget(self.empty_state)

        ftl.addWidget(self._view_stack)
        self.center_tabs.addTab(file_tab, _icons.icon("file", color=str(SUBTEXT)), "Files")

        self.similar_panel = SimilarFoldersPanel()
        self.similar_panel.status_message.connect(
            lambda m, lvl="info": self._set_status(m, lvl)
        )
        self.center_tabs.addTab(self.similar_panel, _icons.icon("similar", color=str(SUBTEXT)), "Similar Folders")

        self.scans_panel = ScansPanel()
        self.scans_panel.scan_deleted.connect(self._on_scan_deleted)
        self.scans_panel.scan_selected.connect(self._on_scan_panel_selected)
        self.center_tabs.addTab(self.scans_panel, _icons.icon("package", color=str(SUBTEXT)), "Scans")

        self.splitter.addWidget(self.center_tabs)

        self.detail = DetailPanel()
        self.detail.setStyleSheet(f"background: {PANEL_BG}; border-left: 1px solid {BORDER};")
        self.detail.status_message.connect(lambda m, lvl: self._set_status(m, lvl))
        self._process_panel = ProcessPanel()

        self._right_zone = RightZone(self.detail, self._process_panel)
        self._right_zone.inspector_toggled.connect(self._set_detail_panel_visible)
        self._right_zone.monitor_toggled.connect(self._set_process_dock_visible)
        self.detail.add_header_button(self._right_zone.inspector_collapse_btn)
        self._process_panel.add_header_button(self._right_zone.monitor_collapse_btn)
        self.splitter.addWidget(self._right_zone)
        self.center_tabs.currentChanged.connect(
            lambda idx: self.detail.clear() if idx != 1 else None
        )

        for i in range(3):
            self.splitter.setCollapsible(i, False)
        self.splitter.setSizes([248, 900, 616])
        return self.splitter

    def _build_welcome(self) -> QWidget:
        from PySide6.QtWidgets import QVBoxLayout
        w   = QWidget()
        w.setStyleSheet(f"background: {DARK_BG};")
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)

        icon = QLabel()
        icon.setPixmap(_icons.app_logo_pixmap(96, radius=20))
        icon.setFixedSize(96, 96)
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon, 0, Qt.AlignHCenter)

        headline = QLabel("ValScanner")
        headline.setStyleSheet(f"color: {TEXT}; font-size: 22px; font-weight: bold;")
        headline.setAlignment(Qt.AlignCenter)
        lay.addWidget(headline)

        sub = QLabel("Scan and explore your files with metadata, tags, and similarity detection.")
        sub.setStyleSheet(f"color: {SUBTEXT}; font-size: 13px;")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)

        lay.addSpacing(8)
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignCenter)
        btn_row.setSpacing(12)
        scan_btn = self._btn_primary("Scan a Folder", icon="scan")
        scan_btn.clicked.connect(self._browse_scan)
        open_btn = self._btn_secondary("Open Existing Database", icon="open")
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

    def _build_empty_state(self) -> QWidget:
        w   = QWidget()
        w.setStyleSheet(f"background: {DARK_BG};")
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(12)
        ico = QLabel()
        ico.setPixmap(_icons.pixmap("search", 64, color=str(SUBTEXT)))
        ico.setAlignment(Qt.AlignCenter)
        lay.addWidget(ico, 0, Qt.AlignHCenter)
        headline = QLabel("No files match these filters")
        headline.setStyleSheet(f"color: {TEXT}; font-size: 16px; font-weight: bold;")
        headline.setAlignment(Qt.AlignCenter)
        lay.addWidget(headline)
        hint = QLabel("Try clearing the search, changing the category, or resetting view filters.")
        hint.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint)
        clear_btn = self._btn_secondary("Clear all filters", icon="close")
        clear_btn.clicked.connect(self._reset_all_filters)
        lay.addWidget(clear_btn, 0, Qt.AlignHCenter)
        return w

    def _refresh_view_stack_page(self) -> None:
        if not hasattr(self, "_view_stack") or not hasattr(self, "empty_state"):
            return
        if not self._db_url:
            return
        model_empty = hasattr(self, "table_model") and self.table_model.rowCount() == 0
        if model_empty and self._any_filter_active():
            self._view_stack.setCurrentWidget(self.empty_state)
        else:
            self._view_stack.setCurrentIndex(self._current_view_index)

    def _build_task_pill(self) -> QWidget:
        pill = QWidget()
        pl = QHBoxLayout(pill)
        pl.setContentsMargins(4, 0, 4, 0)
        pl.setSpacing(4)

        from PySide6.QtWidgets import QToolButton
        self._task_gear_btn = QToolButton()
        self._task_gear_btn.setIcon(_icons.icon("settings", color=str(SUBTEXT)))
        self._task_gear_btn.setFixedSize(20, 20)
        self._task_gear_btn.setToolTip("Process monitor")
        self._task_gear_btn.setStyleSheet(
            f"QToolButton{{background:transparent;border:none;}}"
            f"QToolButton:hover{{background:{PANEL_BG};border-radius:3px;}}"
        )
        self._task_gear_btn.clicked.connect(
            lambda: self._set_process_dock_visible(
                not self._right_zone.is_monitor_visible() if hasattr(self, "_right_zone") else True
            )
        )
        pl.addWidget(self._task_gear_btn)

        self._task_count_lbl = QLabel()
        self._task_count_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:10px;")
        self._task_count_lbl.hide()
        pl.addWidget(self._task_count_lbl)

        self._task_name_lbl = QLabel()
        self._task_name_lbl.setMaximumWidth(160)
        self._task_name_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:10px;")
        self._task_name_lbl.hide()
        pl.addWidget(self._task_name_lbl)

        self._task_stop_btn = QPushButton("⏹")
        self._task_stop_btn.setFixedSize(18, 18)
        self._task_stop_btn.setToolTip("Cancel active task")
        self._task_stop_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{RED};border:none;font-size:11px;}}"
            f"QPushButton:hover{{background:{RED:22};border-radius:3px;}}"
        )
        self._task_stop_btn.clicked.connect(self._on_task_stop_clicked)
        self._task_stop_btn.hide()
        pl.addWidget(self._task_stop_btn)

        return pill

    def _update_task_pill(self) -> None:
        if not hasattr(self, "_task_gear_btn"):
            return
        from .panels.process import ProcessState
        entries = ProcessRegistry.instance().entries()
        active = [e for e in entries if e.state in (ProcessState.RUNNING, ProcessState.FROZEN)]
        n = len(active)
        if n == 0:
            self._task_count_lbl.hide()
            self._task_name_lbl.hide()
            self._task_stop_btn.hide()
            self._task_gear_btn.setStyleSheet(
                f"QToolButton{{background:transparent;border:none;}}"
                f"QToolButton:hover{{background:{PANEL_BG};border-radius:3px;}}"
            )
        else:
            self._task_count_lbl.setText(f"⚙ {n}")
            self._task_count_lbl.show()
            name = active[-1].name[:24] + "…" if len(active[-1].name) > 24 else active[-1].name
            self._task_name_lbl.setText(name)
            self._task_name_lbl.show()
            cancellable = [e for e in active if e.cancel_cb is not None]
            self._task_stop_btn.setVisible(bool(cancellable))
            self._task_gear_btn.setStyleSheet(
                f"QToolButton{{background:transparent;border:none;}}"
                f"QToolButton:hover{{background:{PANEL_BG};border-radius:3px;}}"
            )

    def _on_task_stop_clicked(self) -> None:
        from .panels.process import ProcessState
        from PySide6.QtCore import QPoint
        entries = ProcessRegistry.instance().entries()
        active = [e for e in entries
                  if e.state in (ProcessState.RUNNING, ProcessState.FROZEN)
                  and e.cancel_cb is not None]
        if not active:
            return
        if len(active) == 1:
            active[0].cancel_cb()
            self._set_status(f"Cancelling {active[0].name}…", level="info")
            return
        menu = QMenu(self)
        for e in active:
            menu.addAction(f"Cancel {e.name}", lambda cb=e.cancel_cb: cb())
        menu.addSeparator()
        menu.addAction("Cancel all", lambda: [e.cancel_cb() for e in active])
        menu.exec(self._task_stop_btn.mapToGlobal(QPoint(0, 0)))

    def _build_statsbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background: {PANEL_BG}; border-top: 1px solid {BORDER}; border-bottom: 1px solid {BORDER};")
        bar.setFixedHeight(32)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 0, 14, 0)
        bl.setSpacing(18)

        def _stat_pair(icon_name: str) -> tuple[QLabel, QWidget]:
            wrap = QWidget()
            wl   = QHBoxLayout(wrap)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setSpacing(7)
            ico  = self._icon_label(icon_name, 12, color=str(SUBTEXT))
            text = QLabel("—")
            text.setStyleSheet(
                f"color: {SUBTEXT}; font-size: 11px;"
            )
            wl.addWidget(ico); wl.addWidget(text)
            return text, wrap

        self._stat_files,   files_w   = _stat_pair("folder")
        self._stat_size,    size_w    = _stat_pair("save")
        self._stat_showing, showing_w = _stat_pair("search")
        bl.addWidget(files_w)
        bl.addWidget(size_w)
        bl.addWidget(showing_w)
        bl.addStretch()

        self._stat_partition = QLabel("partition · —")
        self._stat_partition.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; "
            f"font-family: '{mono_font_family()}', monospace;"
        )
        bl.addWidget(self._stat_partition)

        self._stat_dbhealth = QLabel("db · disconnected")
        self._stat_dbhealth.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; "
            f"font-family: '{mono_font_family()}', monospace;"
        )
        bl.addWidget(self._stat_dbhealth)

        self._statsbar = bar
        return bar

    def _update_stats(self, total: int, total_size: int, showing: int) -> None:
        self._stat_files.setText(f"{total:,} files")
        self._stat_size.setText(human_size(total_size))
        self._stat_showing.setText(f"Showing {showing:,}")
        if hasattr(self, "_stat_partition"):
            scan_id = self._active_scan_id
            self._stat_partition.setText(
                f"partition · scan #{scan_id}" if scan_id else "partition · all"
            )
        if hasattr(self, "_stat_dbhealth"):
            ok = bool(self._db_url or self._db_path)
            color = str(GREEN) if ok else str(SUBTEXT)
            label = "healthy" if ok else "disconnected"
            self._stat_dbhealth.setText(f"db · <span style='color:{color}'>{label}</span>")

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
        start = getattr(self, "db_edit", None)
        start = (start.text().strip() if start else "") or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Open existing database", start,
            "SQLite databases (*.db);;All files (*)",
        )
        if not path or not Path(path).exists():
            return
        self._push_recent(path)
        self._load_url(active_url(path))

    def _open_db_settings(self) -> None:
        dlg = DatabaseSettingsDialog(self)
        dlg.settings_saved.connect(lambda: self._load_url(active_url()))
        dlg.exec()

    def _load_url(self, url: str) -> None:
        """Async entry point: dispatch a ConnectWorker for the given URL."""
        if not url:
            return
        if self._connect_worker and self._connect_worker.isRunning():
            self._connect_worker.quit()

        self._db_url = url
        self._set_status("Connecting…")
        self._set_loading(True)

        self._connect_worker = ConnectWorker(url)
        self._connect_worker.connected.connect(self._on_connected)
        self._connect_worker.error.connect(self._on_connect_error)
        self._connect_worker.start()

    def _set_loading(self, on: bool) -> None:
        for w in (self.csv_btn, self.json_btn):
            w.setEnabled(not on)

    def _on_connected(self, result: dict) -> None:
        self._set_loading(False)
        url = result["url"]
        self._db_url  = url
        display = mask_url(url)
        self._set_status(f"Connected — {display}")
        self.setWindowTitle(f"ValScanner — {display}")

        # Derive a local path for legacy code that still needs _db_path.
        if url.startswith("sqlite:///"):
            self._db_path = url[len("sqlite:///"):]
        else:
            self._db_path = url

        if hasattr(self, "db_edit"):
            self.db_edit.setText(self._db_path)

        if self._db_path and Path(self._db_path).exists():
            self.recent_dbs.push(self._db_path)
            self.recent_dbs.set_active(self._db_path)

        self._load_db_panels(url)

    def _on_connect_error(self, msg: str) -> None:
        self._set_loading(False)
        self._set_status(f"Connection failed: {msg}")

    def _load_db_panels(self, url: str) -> None:
        """Re-feed every panel with the new URL after a successful connect."""
        self.csv_btn.setEnabled(True)
        self.json_btn.setEnabled(True)
        self.similar_panel.set_db(url)
        self.similar_panel.auto_load_last_run()
        self.detail.set_db(url)
        _THUMB_CACHE.set_db(url)
        self._refresh_scan_combo()
        self.scans_panel.load(url)
        self._load_from_db()
        self.folder_panel.load(url)
        self._switch_to_results()
        display = mask_url(url)
        if hasattr(self, "db_status_lbl"):
            self.db_status_lbl.setText(f"  ●  {display}  ")
            self.db_status_lbl.setStyleSheet(
                f"color: {GREEN}; font-size: 10px; background: {GREEN:11}; "
                f"border: 1px solid {GREEN:44}; border-radius: 8px; padding: 2px 10px;"
            )

    def _load_db(self, path: str) -> None:
        self._db_path = path
        self._push_recent(path)
        self.csv_btn.setEnabled(True)
        self.json_btn.setEnabled(True)
        self.similar_panel.set_db(path)
        self.similar_panel.auto_load_last_run()
        self.detail.set_db(path)
        _THUMB_CACHE.set_db(path)
        self._refresh_scan_combo()
        self.scans_panel.load(path)
        self._load_from_db()
        self.folder_panel.load(path)
        self._switch_to_results()
        name = Path(path).name
        self.db_status_lbl.setText(f"  ●  {name}  ")
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
            from .feedback import notify_error
            notify_error(self, "Scan path is not a folder",
                f"'{root}' does not point to a directory. "
                "Choose an existing folder to scan.",
                detail=root)
            return

        if self._worker and self._worker.isRunning():
            self._enqueue_scan()
            return

        db = self._db_url or self.db_edit.text().strip() or "file_index.db"
        self._db_path = db if not db.startswith("sqlite:///") else db[len("sqlite:///"):]
        self._clear_folder_filter()
        self.search_edit.clear()

        self._set_scan_btn_scanning()
        self.csv_btn.setEnabled(False)
        self.json_btn.setEnabled(False)
        self.progress.show()
        self.elapsed_lbl.show()
        self.db_status_lbl.setText("  ●  Scanning…  ")
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
        self._set_process_dock_visible(True)

        self._worker.progress.connect(self._on_progress)
        self._worker.progress.connect(
            lambda ev: reg.set_progress(pid, min(ev.get("scanned", 0) // 1000, 99))
        )
        self._worker.done.connect(self._on_scan_done)
        self._worker.error.connect(lambda e: self._set_status(f"Error: {e}"))
        self._worker.start()

    def _set_scan_btn_scanning(self) -> None:
        self.scan_btn.setText("Stop")
        self.scan_btn.setIcon(_icons.icon("stop", color="#ffffff"))
        self.scan_btn.setStyleSheet(
            f"QPushButton{{background:{RED};color:white;border:none;"
            f"border-radius:7px;padding:6px 16px;font-weight:600;font-size:12px;}}"
            f"QPushButton:hover{{background:{RED};}}"
        )
        try:
            self.scan_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.scan_btn.clicked.connect(self._stop_scan)
        self.scan_btn.setEnabled(True)

    def _set_scan_btn_idle(self) -> None:
        self.scan_btn.setText("Scan")
        self.scan_btn.setIcon(_icons.icon("scan", color="#ffffff"))
        self.scan_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:white;border:none;"
            f"border-radius:7px;padding:6px 16px;font-weight:600;font-size:12px;}}"
            f"QPushButton:hover{{background:{BTN_HOVER};}}"
            f"QPushButton:pressed{{background:{BTN_PRESSED};}}"
            f"QPushButton:disabled{{background:{BORDER};color:{SUBTEXT};}}"
        )
        try:
            self.scan_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.scan_btn.clicked.connect(self._start_scan)
        self.scan_btn.setEnabled(True)

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
            self.options_btn.setText("Options ·  " + ", ".join(labels[k] for k in active if k in labels))
        else:
            self.options_btn.setText("Options")

    def _stop_scan(self) -> None:
        if self._worker:
            self._worker.stop()
        self._elapsed_timer.stop()
        self._set_scan_btn_idle()
        self._set_status("Scan cancelled.")

    def _tick_elapsed(self) -> None:
        secs = int(time.time() - self._scan_start)
        m, s = divmod(secs, 60)
        self.elapsed_lbl.setText(f"{m:02d}:{s:02d}")

    def _on_progress(self, ev: dict) -> None:
        count = ev.get("scanned", 0)
        path  = ev.get("path", "")
        short = path[-70:] if len(path) > 70 else path
        self._set_status(f"Scanning… {count:,} files  —  {short}", level="busy")
        if count % 1000 == 0:
            self.console.log(f"Scanned {count:,} files…", "info")

    def _on_scan_done(self, stats: dict) -> None:
        self._elapsed_timer.stop()
        self.progress.hide()
        self.elapsed_lbl.hide()
        self._set_scan_btn_idle()
        self.csv_btn.setEnabled(True)
        self.json_btn.setEnabled(True)
        elapsed = int(time.time() - self._scan_start)

        if stats.get("cancelled"):
            msg = f"⏹  Scan cancelled — {stats['scanned']:,} files indexed in {elapsed}s"
        else:
            msg = f"Scan complete — {stats['scanned']:,} files in {elapsed}s"
            if stats["errors"]:
                msg += f", {stats['errors']} errors"

        self._set_status(msg)
        if self._db_url:
            self._load_db_panels(self._db_url)
        else:
            self._load_db(self._db_path)

        if not stats.get("cancelled") and self._scan_queue:
            self._dequeue_and_start()

    # ── Scan queue ────────────────────────────────────────────────────────────

    def _enqueue_scan(self) -> None:
        root = self.path_edit.text().strip()
        db = self._db_url or self.db_edit.text().strip() or "file_index.db"
        self._scan_queue.append({
            "root":     root,
            "db":       db,
            "label":    self.label_edit.text().strip(),
            "use_hash": self.hash_chk.isChecked(),
            "options":  self._scan_options.copy(),
        })
        self._refresh_queue_strip()
        name = Path(root).name
        n = len(self._scan_queue)
        self._set_status(f"Added '{name}' to scan queue ({n} pending)")

    def _dequeue_and_start(self) -> None:
        if not self._scan_queue:
            return
        item = self._scan_queue.pop(0)
        self._refresh_queue_strip()
        self.path_edit.setText(item["root"])
        self.label_edit.setText(item["label"])
        self.hash_chk.setChecked(item["use_hash"])
        self._scan_options = item["options"]
        self._start_scan()

    def _clear_queue(self) -> None:
        self._scan_queue.clear()
        self._refresh_queue_strip()
        self._set_status("Scan queue cleared.")

    # ── Load / filter ─────────────────────────────────────────────────────────

    def _load_from_db(self) -> None:
        if not self._db_path or not Path(self._db_path).exists():
            return
        self._browser_path = ""
        self._browser_history = []
        self._load_browser_view()

    def _on_db_loaded(self, data: dict) -> None:
        """Callback when database flat-view load completes."""
        total = data["total"]
        total_size = data["total_size"]
        rows = data["rows"]

        self._all_rows = rows
        self._total_row_count = total
        self._loaded_offset = PAGE_SIZE

        self._apply_filters()
        self._update_stats(total, total_size, len(self._all_rows))
        self.center_tabs.setTabText(1, f"Files ({total:,})")

        sb = self.table.verticalScrollBar()
        try:
            sb.valueChanged.disconnect(self._on_table_scroll)
        except RuntimeError:
            pass
        sb.valueChanged.connect(self._on_table_scroll)


    def _load_browser_view(self) -> None:
        """Browser view: load folders + files at the current path."""
        if not self._db_path:
            return
        self._breadcrumb_bar.show()
        self._update_breadcrumb()

        self.center_tabs.setTabText(1, "Files (loading…)")
        self._stat_showing.setText("Loading…")

        self._browser_worker = BrowserLoadWorker(
            self._db_path, self._active_scan_id, self._browser_path,
            recursive=self._folder_filter_recursive,
        )
        self._browser_worker.contents_ready.connect(self._on_browser_loaded)
        self._browser_worker.error.connect(lambda e: self._set_status(f"Error: {e}"))
        self._browser_worker.start()

    def _on_browser_loaded(self, data: dict) -> None:
        """Render folders + files at the current browser path."""
        folders = data["folders"]
        files = data["files"]
        path = data["path"]

        if path != self._browser_path:
            # Stale response — ignore
            return

        rows: list = []
        total_bytes = 0

        for f in folders:
            # f = (path, file_count, total_bytes, scan_id)
            fp, fcount, fbytes = f[0], f[1] or 0, f[2] or 0
            from ..core.schema import human_size as _hs
            rows.append(make_folder_row(fp, fcount, fbytes, _hs(fbytes)))
            total_bytes += fbytes

        rows.extend(files)
        for fr in files:
            total_bytes += fr[3] or 0

        self._all_rows = rows
        self._total_row_count = len(rows)
        self._loaded_offset = len(rows)  # no lazy paging needed in browser mode

        # Disconnect scroll lazy loader in browser mode
        sb = self.table.verticalScrollBar()
        try:
            sb.valueChanged.disconnect(self._on_table_scroll)
        except RuntimeError:
            pass

        self._apply_filters()
        self._update_stats(len(rows), total_bytes, len(rows))
        label = Path(self._browser_path).name if self._browser_path else "root"
        self.center_tabs.setTabText(1, f"{label} ({len(folders)} folders, {len(files)} files)")


    def _navigate_to(self, path: str) -> None:
        """Navigate browser to the given path."""
        if self._browser_path:
            self._browser_history.append(self._browser_path)
        self._browser_path = path
        self._load_browser_view()

    def _navigate_up(self) -> None:
        """Navigate to parent folder."""
        if not self._browser_path:
            return
        parent = str(Path(self._browser_path).parent)
        if parent == self._browser_path:
            self._browser_path = ""
        else:
            self._browser_path = "" if parent == "." else parent
        self._load_browser_view()

    def _update_breadcrumb(self) -> None:
        """Rebuild breadcrumb buttons from the current path."""
        # Clear existing buttons (keep last 2 items: stretch + depth_seg_ctrl)
        while self._breadcrumb_lay.count() > 2:
            item = self._breadcrumb_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._depth_seg_ctrl.setEnabled(True)

        crumb_ss = (
            f"QPushButton{{background:transparent;color:{SUBTEXT};border:none;"
            f"padding:2px 6px;font-size:12px;}}"
            f"QPushButton:hover{{color:{ACCENT};}}"
        )

        # Root segment — insert before the stretch (count()-2 keeps stretch+seg_ctrl at end)
        root_btn = QPushButton("Root")
        root_btn.setIcon(_icons.icon("folder", color=str(SUBTEXT)))
        root_btn.setIconSize(QSize(14, 14))
        root_btn.setStyleSheet(crumb_ss)
        root_btn.setCursor(Qt.PointingHandCursor)
        root_btn.clicked.connect(lambda: self._navigate_to_path(""))
        self._breadcrumb_lay.insertWidget(self._breadcrumb_lay.count() - 2, root_btn)

        if self._browser_path:
            # Split path into segments and build a button per segment
            parts = Path(self._browser_path).parts
            cumulative = ""
            for i, part in enumerate(parts):
                sep = QLabel("›")
                sep.setStyleSheet(f"color: {SUBTEXT}; padding: 0 2px;")
                self._breadcrumb_lay.insertWidget(self._breadcrumb_lay.count() - 2, sep)

                cumulative = str(Path(cumulative) / part) if cumulative else part
                btn = QPushButton(part)
                btn.setStyleSheet(crumb_ss)
                btn.setCursor(Qt.PointingHandCursor)
                # Capture cumulative path at this iteration
                target_path = cumulative
                btn.clicked.connect(lambda _c=False, p=target_path: self._navigate_to_path(p))
                self._breadcrumb_lay.insertWidget(self._breadcrumb_lay.count() - 2, btn)

        if self._browser_path:
            self._update_pill_label()
            self.folder_pill.show()
        else:
            self.folder_pill.hide()

    def _navigate_to_path(self, path: str) -> None:
        """Jump directly to a path (used by breadcrumb)."""
        if path == self._browser_path:
            return
        self._browser_path = path
        self._load_browser_view()

    def _apply_filters(self) -> None:
        term = self.search_edit.text().strip().lower()
        cat  = self.cat_combo.currentText()
        if cat == "All types":
            cat = ""

        filtered = []
        for r in self._all_rows:
            # Folder rows: only filter by search term
            if len(r) > 2 and r[2] == _FOLDER_SENTINEL:
                if term and term not in f"{r[1]} {r[0]}".lower():
                    continue
                filtered.append(r)
                continue
            if cat and r[2] != cat:
                continue
            if term and term not in f"{r[1]} {r[2]} {r[6]} {r[7] if len(r) > 7 else ''} {r[0]}".lower():
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
        self._stat_showing.setText(f"Showing {len(filtered):,}")
        if self._browser_path:
            self._update_pill_label(filtered_count=len(filtered))
        self._update_filterbar_summary()

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
        self._refresh_view_stack_page()

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
        persistence.set_json(persistence.Keys.FILES_FILTERS, filters)
        self._apply_filters()
        self._update_vf_btn_label()

    def _update_vf_btn_label(self) -> None:
        n = self._count_active_view_filters()
        self._vf_btn.setText(f"Filters  ·  {n}" if n else "Filters")
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
        self._current_view_index = mode
        if hasattr(self, "_hover_card"):
            self._hover_card.hide_now()
        old = self._view_stack.currentWidget()
        old_scroll = 0
        if old and hasattr(old, "verticalScrollBar"):
            old_scroll = old.verticalScrollBar().value()
        _views = [self.table, self.grid_view, self.list_view]
        if 0 <= mode < len(_views):
            new = _views[mode]
            if hasattr(new, "verticalScrollBar"):
                new.verticalScrollBar().setValue(old_scroll)
        self._refresh_view_stack_page()

    def _on_icon_selected(self, current, _prev) -> None:
        if not current.isValid():
            return
        row = self.icon_model.data(current, Qt.UserRole)
        if row and (len(row) <= 2 or row[2] != _FOLDER_SENTINEL):
            self.detail.show_file(row)

    def _filter_by_folder(self, folder_path: str) -> None:
        if not folder_path:
            return
        self._browser_path = folder_path
        self._folder_filter_recursive = False
        self._depth_grp.blockSignals(True)
        self._depth_this_btn.setChecked(True)
        self._depth_grp.blockSignals(False)
        self._load_browser_view()
        self.center_tabs.setCurrentIndex(1)

    def _on_depth_seg_clicked(self, btn_id: int) -> None:
        self._folder_filter_recursive = (btn_id == 1)
        self._load_browser_view()

    def _toggle_folder_depth(self) -> None:
        if not self._browser_path:
            return
        self._folder_filter_recursive = not self._folder_filter_recursive
        self._depth_grp.blockSignals(True)
        self._depth_grp.button(1 if self._folder_filter_recursive else 0).setChecked(True)
        self._depth_grp.blockSignals(False)
        self._load_browser_view()

    def _update_pill_label(self, filtered_count: int | None = None) -> None:
        short = Path(self._browser_path).name if self._browser_path else ""
        suffix = f"  ·  {filtered_count:,}" if filtered_count is not None else ""
        self.folder_pill_lbl.setText(f"{short}{suffix}")

    def _clear_folder_filter(self) -> None:
        self._folder_filter_recursive = False
        self._depth_grp.blockSignals(True)
        self._depth_this_btn.setChecked(True)
        self._depth_grp.blockSignals(False)
        self.folder_pill.hide()
        self._browser_path = ""
        self._load_browser_view()

    def _clear_filters(self) -> None:
        self.search_edit.clear()
        self.cat_combo.setCurrentIndex(0)
        self._clear_folder_filter()
        self._view_filters = {}
        persistence.set_json(persistence.Keys.FILES_FILTERS, {})
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
        if data and (len(data) <= 2 or data[2] != _FOLDER_SENTINEL):
            self.detail.show_file(data)

    def _open_selected(self, index) -> None:
        # Determine which model to read from based on sender
        sender = self.sender()
        row = None
        if sender is self.table:
            if index.isValid() and 0 <= index.row() < len(self.table_model._rows):
                row = self.table_model._rows[index.row()]
        else:
            if index.isValid():
                row = self.icon_model.data(index, Qt.UserRole)

        # Drill into folder if applicable
        if row and len(row) > 2 and row[2] == _FOLDER_SENTINEL:
            self._navigate_to(row[0])
            return

        self.detail._open_file()

    def _selected_rows_data(self, view) -> list:
        """Return data rows for all selected rows in the given view."""
        if view is self.table:
            sel_rows = self.table.selectionModel().selectedRows()
            rows = []
            for idx in sel_rows:
                r = self.table_model._rows[idx.row()]
                if r and (len(r) <= 2 or r[2] != _FOLDER_SENTINEL):
                    rows.append(r)
            return rows
        else:
            sel = view.selectionModel().selectedIndexes()
            rows = []
            for idx in sel:
                r = self.icon_model.data(idx, Qt.UserRole)
                if r and (len(r) <= 2 or r[2] != _FOLDER_SENTINEL):
                    rows.append(r)
            return rows

    def _open_selected_files(self) -> None:
        view = self._active_view()
        for row in self._selected_rows_data(view):
            self._open_path(row[0])

    def _reveal_selected(self) -> None:
        view = self._active_view()
        rows = self._selected_rows_data(view)
        if rows:
            self._reveal(str(Path(rows[0][0]).parent))

    def _copy_selected_paths(self) -> None:
        view = self._active_view()
        rows = self._selected_rows_data(view)
        if rows:
            text = "\n".join(r[0] for r in rows)
            QApplication.clipboard().setText(text)
            n = len(rows)
            self._set_status(f"Copied {n} path{'s' if n > 1 else ''}")

    def _active_view(self):
        idx = self._current_view_index
        return [self.table, self.grid_view, self.list_view][idx]

    def _context_menu(self, pos) -> None:
        view  = self.sender()
        index = view.indexAt(pos)
        if not index.isValid():
            return
        rows = self._selected_rows_data(view)
        if not rows:
            if view is self.table:
                row = self.table_model._rows[index.row()] if index.row() < len(self.table_model._rows) else None
            else:
                row = self.icon_model.data(index, Qt.UserRole)
            if not row:
                return
            rows = [row]
        n = len(rows)
        menu = QMenu(self)
        platform_label = "Finder" if sys.platform == "darwin" else "Explorer"
        open_act   = menu.addAction(_icons.icon("play",        color=str(TEXT)), f"Open {n} file{'s' if n > 1 else ''}")
        reveal_act = menu.addAction(_icons.icon("folder-open", color=str(TEXT)), f"Reveal in {platform_label}")
        menu.addSeparator()
        copy_path  = menu.addAction(_icons.icon("copy",       color=str(TEXT)), f"Copy {'path' if n == 1 else f'{n} paths'}")
        copy_name  = menu.addAction(_icons.icon("clipboard",  color=str(TEXT)), "Copy filename")
        if n > 1:
            copy_name.setEnabled(False)
        act = menu.exec(view.viewport().mapToGlobal(pos))
        if act == open_act:
            for row in rows:
                self._open_path(row[0])
        elif act == reveal_act:
            self._reveal(str(Path(rows[0][0]).parent))
        elif act == copy_path:
            text = "\n".join(r[0] for r in rows)
            QApplication.clipboard().setText(text)
            self._set_status(f"Copied {n} path{'s' if n > 1 else ''}")
        elif act == copy_name:
            QApplication.clipboard().setText(rows[0][1])
            self._set_status(f"Copied: {rows[0][1]}")

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
        self._lazy_worker.error.connect(lambda e: self._set_status(f"Error loading rows: {e}"))
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
            self._stat_showing.setText(f"Showing {len(self._filtered_rows):,}")

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_csv(self) -> None:
        if not self._db_path:
            return
        out  = self._db_path.replace(".db", ".csv")
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", out, "CSV files (*.csv)")
        if path:
            export_csv(self._db_path, path)
            self._set_status(f"CSV saved → {path}")

    def _export_json(self) -> None:
        if not self._db_path:
            return
        out  = self._db_path.replace(".db", ".json")
        path, _ = QFileDialog.getSaveFileName(self, "Export JSON", out, "JSON files (*.json)")
        if path:
            export_json(self._db_path, path)
            self._set_status(f"JSON saved → {path}")

    def _set_status(self, msg: str, level: str = "info",
                    timeout: int | None = None) -> None:
        """Single sink for all status messages."""
        from .feedback import TIMEOUTS, color_for
        # Update the persistent label (visible alongside dot & clock)
        if hasattr(self, "_status_lbl"):
            self._status_lbl.setText(msg)
            self._status_lbl.setStyleSheet(
                f"color: {color_for(level)}; font-size: 11px;"
            )
            # Color the dot too
            dot_color = color_for(level) if level != "info" else str(GREEN)
            if hasattr(self, "_status_dot"):
                self._status_dot.setStyleSheet(
                    f"background: {dot_color}; border-radius: 4px;"
                )
        else:
            msec = timeout if timeout is not None else TIMEOUTS.get(level, 5000)
            self.status.setStyleSheet(
                f"QStatusBar QLabel {{ color: {color_for(level)}; }}"
            )
            self.status.showMessage(msg, msec)
        if not hasattr(self, "console"):
            return
        if level in ("warning", "error", "success"):
            self.console.log(msg, level=level)


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
    load_fonts()
    icon = _app_icon()
    app.setWindowIcon(icon)
    win = MainWindow()
    win.setWindowIcon(icon)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
