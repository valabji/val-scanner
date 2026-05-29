from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QStandardItemModel, QStandardItem, QKeySequence, QShortcut
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QHeaderView, QAbstractItemView, QMenu, QStackedWidget,
    QFileDialog, QMessageBox,
)

from ..constants import DARK_BG, PANEL_BG, ACCENT, TEXT, SUBTEXT, BORDER, RED, SEL_BG, SEL_TEXT
from ..density import get_row_height, on_changed as _density_on_changed
from ...core.db import list_scans, delete_scan, remap_scan
from ...core.schema import human_size
from .. import icons as _icons
from ..feedback import confirm_destructive, undo_toast
from .. import persistence


class ScansPanel(QWidget):
    scan_deleted  = Signal(int)
    scan_remapped = Signal(int)
    scan_selected = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db_path = ""
        self._pending_ids: list[int] = []
        self._pending_timer: QTimer | None = None
        self._build_ui()
        from ..theme import Theme
        Theme.instance().on_changed(self._apply_stylesheet)
        _density_on_changed(self._on_density_changed)

    def _on_density_changed(self) -> None:
        self.table.verticalHeader().setDefaultSectionSize(get_row_height())
        self.table.update()

    def _apply_stylesheet(self) -> None:
        self._hdr.setStyleSheet(f"background:{PANEL_BG};border-bottom:1px solid {BORDER};")
        self._title.setStyleSheet(f"color:{TEXT};font-weight:bold;font-size:13px;")
        self._hint.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        self._del_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{RED};border:1px solid {RED}44;"
            f"border-radius:6px;padding:4px 10px;font-size:11px;}}"
            f"QPushButton:hover{{background:{RED}22;}}"
            f"QPushButton:disabled{{color:{SUBTEXT};border-color:{BORDER};}}"
        )
        self.table.setStyleSheet(f"""
            QTableView {{
                background:{DARK_BG};color:{TEXT};border:none;font-size:12px;
                selection-background-color:{SEL_BG};selection-color:{SEL_TEXT};
            }}
            QTableView::item:selected {{ background:{SEL_BG}; color:{SEL_TEXT}; }}
            QHeaderView::section {{
                background:{PANEL_BG};color:{SUBTEXT};border:none;
                border-bottom:1px solid {BORDER};padding:6px 10px;
                font-size:11px;font-weight:bold;
            }}
        """)
        self._foot.setStyleSheet(f"background:{PANEL_BG};border-top:1px solid {BORDER};")
        self._show_all_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{ACCENT};border:1px solid {ACCENT}44;"
            f"border-radius:6px;padding:4px 12px;font-size:11px;}}"
            f"QPushButton:hover{{background:{ACCENT}22;}}"
        )
        self.count_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        self._scans_empty_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:12px;padding:40px;")

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._hdr = QWidget()
        self._hdr.setStyleSheet(f"background:{PANEL_BG};border-bottom:1px solid {BORDER};")
        self._hdr.setFixedHeight(44)
        hl = QHBoxLayout(self._hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(8)
        title_icon = QLabel()
        title_icon.setPixmap(_icons.pixmap("package", 18, color=str(TEXT)))
        hl.addWidget(title_icon)
        self._title = QLabel("Scan Sessions")
        self._title.setStyleSheet(f"color:{TEXT};font-weight:bold;font-size:13px;")
        hl.addWidget(self._title)
        hl.addStretch()
        self._hint = QLabel("Double-click a scan to filter the Files view")
        self._hint.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        hl.addWidget(self._hint)

        self._del_btn = QPushButton("Delete selected")
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{RED};border:1px solid {RED}44;"
            f"border-radius:6px;padding:4px 10px;font-size:11px;}}"
            f"QPushButton:hover{{background:{RED}22;}}"
            f"QPushButton:disabled{{color:{SUBTEXT};border-color:{BORDER};}}"
        )
        self._del_btn.setAccessibleName("Delete selected scans")
        self._del_btn.setAccessibleDescription(
            "Permanently delete the selected scans and their indexed files. "
            "This cannot be undone after the undo window passes.")
        self._del_btn.clicked.connect(self._delete_selected)
        hl.addWidget(self._del_btn)
        lay.addWidget(self._hdr)

        self.table = QTableView()
        self.table.setAccessibleName("Scan history")
        self.table.setAccessibleDescription(
            "Past scans with their root folder, file count, and size. "
            "Select rows and press Delete to remove them. Double-click to open a scan in Files view.")
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(get_row_height())
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.setStyleSheet(f"""
            QTableView {{
                background:{DARK_BG};color:{TEXT};border:none;font-size:12px;
                selection-background-color:{SEL_BG};selection-color:{SEL_TEXT};
            }}
            QTableView::item:selected {{ background:{SEL_BG}; color:{SEL_TEXT}; }}
            QHeaderView::section {{
                background:{PANEL_BG};color:{SUBTEXT};border:none;
                border-bottom:1px solid {BORDER};padding:6px 10px;
                font-size:11px;font-weight:bold;
            }}
        """)
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["ID", "Label", "Root", "Scanned", "Files", "Size"])
        self.table.setModel(self._model)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        saved_hdr = persistence.settings().value(persistence.Keys.SCANS_HEADER)
        if saved_hdr is not None:
            self.table.horizontalHeader().restoreState(saved_hdr)
        self.table.doubleClicked.connect(self._on_click)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        for seq in (QKeySequence.Delete, QKeySequence("Backspace")):
            sc = QShortcut(seq, self.table)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(self._delete_selected)
        sc_a = QShortcut(QKeySequence("Ctrl+A"), self.table)
        sc_a.setContext(Qt.WidgetShortcut)
        sc_a.activated.connect(self.table.selectAll)

        self._content_stack = QStackedWidget()
        empty_w = QWidget()
        empty_lay = QVBoxLayout(empty_w)
        empty_lay.setAlignment(Qt.AlignCenter)
        self._scans_empty_lbl = QLabel(
            "No scans yet.\nRun a scan from the toolbar to add your first entry."
        )
        self._scans_empty_lbl.setAlignment(Qt.AlignCenter)
        self._scans_empty_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:12px;padding:40px;")
        self._scans_empty_lbl.setWordWrap(True)
        empty_lay.addWidget(self._scans_empty_lbl)
        self._content_stack.addWidget(empty_w)      # page 0: empty
        self._content_stack.addWidget(self.table)   # page 1: table
        lay.addWidget(self._content_stack, 1)

        self._foot = QWidget()
        self._foot.setStyleSheet(f"background:{PANEL_BG};border-top:1px solid {BORDER};")
        self._foot.setFixedHeight(40)
        fl = QHBoxLayout(self._foot)
        fl.setContentsMargins(16, 0, 16, 0)
        self._show_all_btn = QPushButton("Show all scans in Files view")
        self._show_all_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{ACCENT};border:1px solid {ACCENT}44;"
            f"border-radius:6px;padding:4px 12px;font-size:11px;}}"
            f"QPushButton:hover{{background:{ACCENT}22;}}"
        )
        self._show_all_btn.setAccessibleName("Show all scans in Files view")
        self._show_all_btn.setAccessibleDescription(
            "Switch to the Files view and list files from every scan")
        self._show_all_btn.clicked.connect(lambda: self.scan_selected.emit(0, ""))
        fl.addWidget(self._show_all_btn)
        fl.addStretch()
        self.count_lbl = QLabel()
        self.count_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        fl.addWidget(self.count_lbl)
        lay.addWidget(self._foot)

    def _on_selection_changed(self) -> None:
        n = len(self.table.selectionModel().selectedRows())
        self._del_btn.setEnabled(n > 0)

    def load(self, db_path: str) -> None:
        self._db_path = db_path
        self._model.removeRows(0, self._model.rowCount())
        if not db_path:
            self._content_stack.setCurrentIndex(0)
            return
        scans = list_scans(db_path)
        if not scans:
            self._content_stack.setCurrentIndex(0)
            self.count_lbl.setText("0 scans in database")
            return
        for s in scans:
            sid        = QStandardItem(str(s["id"]))
            plain_label = s["label"] or "—"
            display_label = (plain_label + " (resumed)") if s.get("status") == "resumed" else plain_label
            label_item = QStandardItem(display_label)
            root_item  = QStandardItem(s["root"])
            date_item  = QStandardItem(s["scanned_at"])
            files_item = QStandardItem(f"{s['file_count']:,}")
            size_item  = QStandardItem(s["total_human"] or human_size(s["total_bytes"]))

            for item in (sid, label_item, root_item, date_item, files_item, size_item):
                item.setForeground(QColor(TEXT))
            files_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            sid.setData(s["id"], Qt.UserRole)
            label_item.setData(s["label"] or s["root"], Qt.UserRole + 1)

            self._model.appendRow([sid, label_item, root_item, date_item, files_item, size_item])

        self._content_stack.setCurrentIndex(1)
        self.count_lbl.setText(f"{len(scans)} scan{'s' if len(scans) != 1 else ''} in database")

    def _persist_header(self) -> None:
        persistence.settings().setValue(
            persistence.Keys.SCANS_HEADER,
            self.table.horizontalHeader().saveState(),
        )

    def _scan_id_for_row(self, row: int) -> int:
        item = self._model.item(row, 0)
        return item.data(Qt.UserRole) if item else -1

    def _scan_label_for_row(self, row: int) -> str:
        item = self._model.item(row, 1)
        return item.data(Qt.UserRole + 1) if item else ""

    def _on_click(self, index) -> None:
        row = index.row()
        scan_id = self._scan_id_for_row(row)
        label   = self._scan_label_for_row(row)
        self.scan_selected.emit(scan_id, label)

    def _show_context_menu(self, pos) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        n = len(rows)
        menu = QMenu(self)
        remap_act = None
        if n == 1:
            remap_act = menu.addAction(
                _icons.icon("folder", color=str(ACCENT)),
                "Remap root…",
            )
            menu.addSeparator()
        del_act = menu.addAction(
            _icons.icon("delete", color=str(RED)),
            f"Delete {n} scan{'s' if n > 1 else ''}",
        )
        act = menu.exec(self.table.viewport().mapToGlobal(pos))
        if act == del_act:
            self._delete_selected()
        elif remap_act is not None and act == remap_act:
            self._remap_root_for_selected()

    def _remap_root_for_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if len(rows) != 1:
            return
        row = rows[0].row()
        scan_id = self._scan_id_for_row(row)
        old_root_item = self._model.item(row, 2)
        old_root = old_root_item.text() if old_root_item else ""

        start_dir = old_root if old_root and Path(old_root).exists() else str(Path.home())
        new_root = QFileDialog.getExistingDirectory(
            self, "Pick the new root for this scan", start_dir,
        )
        if not new_root:
            return
        new_root = str(Path(new_root).expanduser())

        if not Path(new_root).exists():
            if not confirm_destructive(
                self, "Remap root",
                f"The chosen folder does not exist on disk:\n  {new_root}\n\n"
                "Remap anyway? File-open actions will fail until the drive is mounted.",
                confirm_label="Remap",
            ):
                return

        try:
            summary = remap_scan(self._db_path, scan_id, new_root)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, "Remap failed", f"Could not remap scan {scan_id}:\n{exc}",
            )
            return

        self.load(self._db_path)
        self.scan_remapped.emit(scan_id)

        if summary["files_updated"] == 0 and summary["folders_updated"] == 0 \
           and not summary["files_skipped"] and not summary["folders_skipped"]:
            body = f"Root already {summary['new_root']} — nothing to update."
        else:
            body = (
                f"Old: {summary['old_root']}\n"
                f"New: {summary['new_root']}\n\n"
                f"{summary['files_updated']:,} files, "
                f"{summary['folders_updated']:,} folders updated."
            )
            n_skip = len(summary["files_skipped"]) + len(summary["folders_skipped"])
            if n_skip:
                body += f"\n{n_skip} row(s) skipped (path not under old root)."
        QMessageBox.information(self, "Scan remapped", body)

    def _delete_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        ids    = [self._scan_id_for_row(r.row()) for r in rows]
        labels = [self._scan_label_for_row(r.row()) for r in rows]
        n = len(ids)
        summary = labels[0] if n == 1 else f"{n} scans"
        if not confirm_destructive(
            self, "Delete scans",
            f"Permanently delete {summary}?\n\n"
            "Files will disappear from the view immediately.\n"
            "Click Undo in the next 8 seconds to cancel.",
        ):
            return

        # Cancel any previous pending delete — commit it first
        if self._pending_timer is not None:
            self._pending_timer.stop()
            self._commit_delete(self._pending_ids)

        self._pending_ids = ids
        # Optimistic UI: hide selected rows immediately
        self.load(self._db_path)     # reload to reflect state (rows still in DB)
        # Actually hide the rows by reloading without deleted IDs shown
        # We rebuild the model excluding pending IDs
        self._hide_pending_rows(ids)

        self._pending_timer = QTimer(self)
        self._pending_timer.setSingleShot(True)
        self._pending_timer.timeout.connect(lambda: self._commit_delete(ids))
        self._pending_timer.start(8000)

        undo_toast(
            self.window(),
            f"Deleted {n} scan{'s' if n > 1 else ''}",
            undo_cb=self._undo_delete,
        )

    def _hide_pending_rows(self, ids: list[int]) -> None:
        pending_set = set(ids)
        rows_to_remove = []
        for row in range(self._model.rowCount()):
            if self._scan_id_for_row(row) in pending_set:
                rows_to_remove.append(row)
        for row in reversed(rows_to_remove):
            self._model.removeRow(row)
        n = self._model.rowCount()
        if n == 0:
            self._content_stack.setCurrentIndex(0)
        self.count_lbl.setText(f"{n} scan{'s' if n != 1 else ''} in database")

    def _undo_delete(self) -> None:
        if self._pending_timer is not None:
            self._pending_timer.stop()
            self._pending_timer = None
        self._pending_ids = []
        self.load(self._db_path)

    def _commit_delete(self, ids: list[int]) -> None:
        self._pending_timer = None
        self._pending_ids   = []
        for sid in ids:
            try:
                delete_scan(self._db_path, sid)
                self.scan_deleted.emit(sid)
            except Exception:
                pass
        self.load(self._db_path)
