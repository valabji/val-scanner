from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QHeaderView, QAbstractItemView, QMessageBox,
)

from ..constants import DARK_BG, PANEL_BG, ACCENT, TEXT, SUBTEXT, BORDER, RED, SEL_BG, SEL_TEXT
from ...core.db import list_scans, delete_scan
from ...core.schema import human_size


class ScansPanel(QWidget):
    scan_deleted  = Signal(int)
    scan_selected = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db_path = ""
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet(f"background:{PANEL_BG};border-bottom:1px solid {BORDER};")
        hdr.setFixedHeight(44)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        title = QLabel("📦  Scan Sessions")
        title.setStyleSheet(f"color:{TEXT};font-weight:bold;font-size:13px;")
        hl.addWidget(title)
        hl.addStretch()
        hint = QLabel("Click a scan to filter the Files view")
        hint.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        hl.addWidget(hint)
        lay.addWidget(hdr)

        self.table = QTableView()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
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
        self._model.setHorizontalHeaderLabels(["ID", "Label", "Root", "Scanned", "Files", "Size", ""])
        self.table.setModel(self._model)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.clicked.connect(self._on_click)
        lay.addWidget(self.table, 1)

        foot = QWidget()
        foot.setStyleSheet(f"background:{PANEL_BG};border-top:1px solid {BORDER};")
        foot.setFixedHeight(40)
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 0, 16, 0)
        show_all = QPushButton("Show all scans in Files view")
        show_all.setStyleSheet(
            f"QPushButton{{background:transparent;color:{ACCENT};border:1px solid {ACCENT:44};"
            f"border-radius:6px;padding:4px 12px;font-size:11px;}}"
            f"QPushButton:hover{{background:{ACCENT:22};}}"
        )
        show_all.clicked.connect(lambda: self.scan_selected.emit(0, ""))
        fl.addWidget(show_all)
        fl.addStretch()
        self.count_lbl = QLabel()
        self.count_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        fl.addWidget(self.count_lbl)
        lay.addWidget(foot)

    def load(self, db_path: str) -> None:
        self._db_path = db_path
        self._model.removeRows(0, self._model.rowCount())
        if not db_path:
            return
        scans = list_scans(db_path)
        for s in scans:
            sid        = QStandardItem(str(s["id"]))
            label_item = QStandardItem(s["label"] or "—")
            root_item  = QStandardItem(s["root"])
            date_item  = QStandardItem(s["scanned_at"])
            files_item = QStandardItem(f"{s['file_count']:,}")
            size_item  = QStandardItem(s["total_human"] or human_size(s["total_bytes"]))
            del_item   = QStandardItem("🗑 Delete")

            for item in (sid, label_item, root_item, date_item, files_item, size_item):
                item.setForeground(QColor(TEXT))
            del_item.setForeground(QColor(RED))
            files_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            sid.setData(s["id"], Qt.UserRole)
            label_item.setData(s["label"] or s["root"], Qt.UserRole + 1)
            del_item.setData(s["id"], Qt.UserRole)

            self._model.appendRow([sid, label_item, root_item, date_item, files_item, size_item, del_item])

        self.count_lbl.setText(f"{len(scans)} scan{'s' if len(scans) != 1 else ''} in database")

    def _on_click(self, index) -> None:
        col      = index.column()
        row      = index.row()
        sid_item = self._model.item(row, 0)
        scan_id  = sid_item.data(Qt.UserRole)

        if col == 6:
            label = self._model.item(row, 1).data(Qt.UserRole + 1)
            reply = QMessageBox.question(
                self, "Delete scan",
                f"Delete scan #{scan_id} ({label})?\n\nAll indexed files from this scan will be removed.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                delete_scan(self._db_path, scan_id)
                self.load(self._db_path)
                self.scan_deleted.emit(scan_id)
        else:
            label = self._model.item(row, 1).data(Qt.UserRole + 1)
            self.scan_selected.emit(scan_id, label)
