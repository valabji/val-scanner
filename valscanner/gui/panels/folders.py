from __future__ import annotations
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from PySide6.QtCore import Qt, Signal, QSortFilterProxyModel
from PySide6.QtGui import QColor, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeView, QHeaderView, QAbstractItemView,
)

from ..constants import DARK_BG, PANEL_BG, ACCENT, TEXT, SUBTEXT, BORDER, GREEN, SEL_BG, SEL_TEXT
from ...core.db import repo_for
from ...core.schema import human_size
from .. import icons as _icons


class FolderPanel(QWidget):
    folder_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_db_path   = ""
        self._last_scan_id   = 0
        self._separate_scans = False
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.tree = QTreeView()
        self.tree.setHeaderHidden(False)
        self.tree.setRootIsDecorated(True)
        self.tree.setAnimated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setIndentation(14)
        self.tree.setStyleSheet(f"""
            QTreeView {{
                background: {DARK_BG}; color: {TEXT}; border: none; font-size: 11px;
            }}
            QTreeView::item {{ padding: 2px 0; }}
            QTreeView::item:selected {{
                background: {SEL_BG}; color: {SEL_TEXT}; border-radius: 4px;
            }}
            QTreeView::item:hover:!selected {{
                background: {PANEL_BG}; border-radius: 4px;
            }}
            QTreeView::branch {{ background: {DARK_BG}; }}
            QHeaderView::section {{
                background: {PANEL_BG}; color: {SUBTEXT}; border: none;
                border-bottom: 1px solid {BORDER}; padding: 4px 6px;
                font-size: 10px; font-weight: bold;
            }}
        """)

        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Folder", "Size", "Files"])

        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setRecursiveFilteringEnabled(True)
        self.proxy.setSortCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setSortRole(Qt.UserRole + 1)

        self.tree.setModel(self.proxy)
        self.tree.setSortingEnabled(True)
        self.tree.header().setSortIndicatorShown(True)
        self.tree.header().setSectionsClickable(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSortIndicator(1, Qt.DescendingOrder)
        self.tree.clicked.connect(self._on_click)

        hdr = QWidget()
        hdr.setStyleSheet(f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};")
        hdr.setFixedHeight(36)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 0, 8, 0)
        hl.setSpacing(6)
        title_icon = QLabel()
        title_icon.setPixmap(_icons.pixmap("folder-open", 14, color=str(TEXT)))
        hl.addWidget(title_icon)
        title = QLabel("Folders")
        title.setStyleSheet(f"color: {TEXT}; font-size: 11px; font-weight: bold;")
        hl.addWidget(title)
        hl.addStretch()

        icon_btn_ss = (
            f"QPushButton{{background:transparent;border:none;}}"
            f"QPushButton:hover{{background:{PANEL_BG};border-radius:4px;}}"
            f"QPushButton:checked{{background:{ACCENT:22};border-radius:4px;}}"
        )

        self.scan_split_btn = QPushButton()
        self.scan_split_btn.setIcon(_icons.icon("database-edit", color=str(SUBTEXT)))
        from PySide6.QtCore import QSize as _QSize
        self.scan_split_btn.setIconSize(_QSize(14, 14))
        self.scan_split_btn.setFixedSize(22, 22)
        self.scan_split_btn.setCheckable(True)
        self.scan_split_btn.setToolTip("Show each scan as a separate root")
        self.scan_split_btn.setStyleSheet(icon_btn_ss)
        self.scan_split_btn.toggled.connect(self._on_split_toggled)

        self.expand_btn = QPushButton()
        self.expand_btn.setIcon(_icons.icon("mdi.unfold-more-horizontal", color=str(SUBTEXT)))
        self.expand_btn.setIconSize(_QSize(14, 14))
        self.expand_btn.setFixedSize(22, 22)
        self.expand_btn.setToolTip("Expand all")
        self.expand_btn.setStyleSheet(icon_btn_ss)
        self.expand_btn.clicked.connect(self.tree.expandAll)

        self.collapse_btn = QPushButton()
        self.collapse_btn.setIcon(_icons.icon("mdi.unfold-less-horizontal", color=str(SUBTEXT)))
        self.collapse_btn.setIconSize(_QSize(14, 14))
        self.collapse_btn.setFixedSize(22, 22)
        self.collapse_btn.setToolTip("Collapse all")
        self.collapse_btn.setStyleSheet(icon_btn_ss)
        self.collapse_btn.clicked.connect(self.tree.collapseAll)

        hl.addWidget(self.scan_split_btn)
        hl.addWidget(self.expand_btn)
        hl.addWidget(self.collapse_btn)

        lay.addWidget(hdr)
        lay.addWidget(self.tree)

    @staticmethod
    def _size_color(ratio: float) -> str:
        if ratio > 0.5:  return "#f38ba8"
        if ratio > 0.2:  return "#fab387"
        if ratio > 0.05: return "#f9e2af"
        return GREEN

    def _make_row(self, path_str: str, tb: int, fc: int, root_bytes: int,
                  label_override: str = "") -> list:
        name  = label_override or (Path(path_str).name or path_str)
        ratio = tb / (root_bytes or 1)
        color = self._size_color(ratio)

        name_item = QStandardItem(_icons.icon("folder", color=str(ACCENT)), name)
        name_item.setData(path_str, Qt.UserRole)
        name_item.setData(name.lower(), Qt.UserRole + 1)
        name_item.setToolTip(path_str)
        name_item.setForeground(QColor(TEXT))

        size_item = QStandardItem(human_size(tb))
        size_item.setData(tb, Qt.UserRole + 1)
        size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        size_item.setForeground(QColor(color))

        count_item = QStandardItem(f"{fc:,}")
        count_item.setData(fc, Qt.UserRole + 1)
        count_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        count_item.setForeground(QColor(SUBTEXT))

        return [name_item, size_item, count_item]

    def _build_subtree(self, parent_item, data: dict, root_bytes: int) -> None:
        all_paths = sorted(data.keys())
        item_map:  dict[str, QStandardItem] = {}

        for path_str in all_paths:
            tb, fc    = data[path_str]
            row       = self._make_row(path_str, tb, fc, root_bytes)
            name_item = row[0]

            parent_candidate = None
            for ancestor in list(Path(path_str).parents):
                anc_str = str(ancestor)
                if anc_str in item_map:
                    parent_candidate = item_map[anc_str]
                    break

            if parent_candidate is not None:
                parent_candidate.appendRow(row)
            elif parent_item is not None:
                parent_item.appendRow(row)
            else:
                self.model.appendRow(row)

            item_map[path_str] = name_item

    def load(self, db_path: str, scan_id: int = 0) -> None:
        self._last_db_path = db_path
        self._last_scan_id = scan_id
        self._reload()

    def _reload(self) -> None:
        db_path = self._last_db_path
        scan_id = self._last_scan_id
        if not db_path:
            return

        self.model.removeRows(0, self.model.rowCount())
        engine = repo_for(db_path).engine

        if self._separate_scans and scan_id == 0:
            try:
                with engine.connect() as conn:
                    scans = conn.execute(
                        text("SELECT id, label, total_bytes, file_count FROM scans ORDER BY label")
                    ).fetchall()
            except OperationalError:
                scans = []

            global_max = 0
            scan_data: list[tuple] = []
            for sid, label, stb, sfc in scans:
                with engine.connect() as conn:
                    rows = conn.execute(
                        text("SELECT path, SUM(total_bytes), SUM(file_count) "
                             "FROM folders WHERE scan_id=:sid GROUP BY path ORDER BY path"),
                        {"sid": sid},
                    ).fetchall()
                data = {r[0]: (r[1], r[2]) for r in rows}
                if data:
                    local_max  = max(v[0] for v in data.values())
                    global_max = max(global_max, local_max)
                scan_data.append((sid, label, stb or 0, sfc or 0, data))
            root_bytes = global_max or 1

            for sid, label, stb, sfc, data in scan_data:
                scan_tb = stb or (max(v[0] for v in data.values()) if data else 0)
                scan_fc = sfc or (sum(v[1] for v in data.values()) if data else 0)
                ratio   = scan_tb / root_bytes
                color   = self._size_color(ratio)

                scan_name_item = QStandardItem(_icons.icon("database", color=str(ACCENT)), label)
                scan_name_item.setData("", Qt.UserRole)
                scan_name_item.setData(label.lower(), Qt.UserRole + 1)
                scan_name_item.setToolTip(f"Scan: {label}")
                scan_name_item.setForeground(QColor(ACCENT))
                f = scan_name_item.font(); f.setBold(True); scan_name_item.setFont(f)

                scan_size_item = QStandardItem(human_size(scan_tb))
                scan_size_item.setData(scan_tb, Qt.UserRole + 1)
                scan_size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                scan_size_item.setForeground(QColor(color))

                scan_count_item = QStandardItem(f"{scan_fc:,}")
                scan_count_item.setData(scan_fc, Qt.UserRole + 1)
                scan_count_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                scan_count_item.setForeground(QColor(SUBTEXT))

                self.model.appendRow([scan_name_item, scan_size_item, scan_count_item])
                if data:
                    self._build_subtree(scan_name_item, data, root_bytes)

        else:
            with engine.connect() as conn:
                if scan_id:
                    rows = conn.execute(
                        text("SELECT path, SUM(total_bytes) AS total_bytes, SUM(file_count) AS file_count "
                             "FROM folders WHERE scan_id=:sid GROUP BY path ORDER BY path"),
                        {"sid": scan_id},
                    ).fetchall()
                else:
                    rows = conn.execute(
                        text("SELECT path, SUM(total_bytes) AS total_bytes, SUM(file_count) AS file_count "
                             "FROM folders GROUP BY path ORDER BY path")
                    ).fetchall()
            if not rows:
                return
            data       = {r[0]: (r[1], r[2]) for r in rows}
            root_bytes = max(v[0] for v in data.values()) or 1
            self._build_subtree(None, data, root_bytes)

        self.tree.expandToDepth(1)
        col   = self.tree.header().sortIndicatorSection()
        order = self.tree.header().sortIndicatorOrder()
        self.proxy.sort(col, order)

    def _on_split_toggled(self, checked: bool) -> None:
        self._separate_scans = checked
        self._reload()

    def _on_click(self, proxy_index) -> None:
        source_index = self.proxy.mapToSource(
            self.proxy.index(proxy_index.row(), 0, proxy_index.parent())
        )
        item = self.model.itemFromIndex(source_index)
        if item:
            path = item.data(Qt.UserRole)
            if path:
                self.folder_selected.emit(path)
