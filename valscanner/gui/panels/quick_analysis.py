"""Quick-analyze GUI panel.

Mirrors the heuristic folder classifier exposed by the CLI ``--quick-analyze``
flag: photo / music / video libraries, code projects, document bins, with
media-library subtree rollup and cross-drive backup-mirror grouping. Runs
are persisted to ``quick_analysis_runs`` so history is browseable.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSpinBox, QCheckBox, QMenu, QFileDialog,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QToolButton, QSizePolicy,
)

from ..constants import DARK_BG, PANEL_BG, ACCENT, TEXT, SUBTEXT, BORDER
from .. import icons as _icons
from ..workers import QuickAnalysisWorker
from ..theme import Spacing, Margins, Sizes
from .process import ProcessRegistry
from ...core.db import (
    list_quick_analysis_runs,
    load_quick_analysis_run,
    delete_quick_analysis_run,
)
from ...core.export import (
    export_quick_analysis_csv,
    export_quick_analysis_json,
)
from ...core.quick_analysis import CATEGORY_ORDER
from ...core.schema import human_size


def _mirror_marker(row: dict) -> str:
    mirrors = row.get("mirrors") or []
    if not mirrors:
        return ""
    n = len(mirrors)
    noun = "copy" if n == 1 else "copies"
    shorter = [m for m in mirrors if m.get("files_delta", 0) < 0]
    if shorter:
        worst = min(m["files_delta"] for m in shorter)
        return f"  +{n} {noun} ({len(shorter)} short, worst {worst:+,} files)"
    return f"  +{n} {noun}"


_TABLE_MAX_H = 360  # px — cap so cards never push siblings off-screen


class _CategorySection(QFrame):
    """A collapsible header + bounded scrollable table for one category."""

    def __init__(self, category: str, rows: list[dict],
                 expanded: bool = False, parent=None):
        super().__init__(parent)
        self._rows = sorted(rows, key=lambda r: -r.get("total_bytes", 0))
        self._category = category
        self._built = False
        self._expanded = expanded

        self.setStyleSheet(
            f"QFrame#qa_card{{background:{PANEL_BG};border:1px solid {BORDER};"
            f"border-radius:8px;}}"
        )
        self.setObjectName("qa_card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        lay.setSpacing(Spacing.XS if hasattr(Spacing, "XS") else 4)

        total_bytes = sum(r.get("total_bytes", 0) for r in rows)
        total_files = sum(r.get("file_count", 0) for r in rows)
        with_mirrors = sum(1 for r in rows if r.get("has_mirrors"))

        self._toggle = QToolButton()
        self._toggle.setText(
            f"  {category}   —   {len(rows):,} folder(s)  "
            f"·  {human_size(total_bytes)}  ·  {total_files:,} files"
            + (f"  ·  {with_mirrors} with mirrors" if with_mirrors else "")
        )
        self._toggle.setCheckable(True)
        self._toggle.setChecked(expanded)
        self._toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._toggle.setStyleSheet(
            f"QToolButton{{background:transparent;color:{TEXT};border:none;"
            f"text-align:left;padding:6px 4px;font-weight:bold;font-size:12px;}}"
            f"QToolButton:hover{{color:{ACCENT};}}"
        )
        self._toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._toggle.clicked.connect(self._on_toggle)
        lay.addWidget(self._toggle)

        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, Spacing.XS if hasattr(Spacing, "XS") else 4)
        self._body_lay.setSpacing(0)
        self._body.setVisible(expanded)
        lay.addWidget(self._body)

        if expanded:
            self._build_table()

    def expand(self, expanded: bool = True) -> None:
        if expanded == self._expanded:
            return
        self._toggle.setChecked(expanded)
        self._on_toggle()

    def _on_toggle(self) -> None:
        self._expanded = self._toggle.isChecked()
        self._toggle.setArrowType(Qt.DownArrow if self._expanded else Qt.RightArrow)
        if self._expanded and not self._built:
            self._build_table()
        self._body.setVisible(self._expanded)
        self.updateGeometry()

    def _build_table(self) -> None:
        self._built = True
        rows = self._rows
        tbl = QTableWidget(len(rows), 4)
        tbl.setHorizontalHeaderLabels(["Size", "Files", "Dom.", "Folder"])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setSelectionBehavior(QTableWidget.SelectRows)
        tbl.setAlternatingRowColors(False)
        tbl.setShowGrid(False)
        tbl.setStyleSheet(
            f"QTableWidget{{background:{DARK_BG};color:{TEXT};"
            f"border:1px solid {BORDER};border-radius:6px;}}"
            f"QHeaderView::section{{background:{PANEL_BG};color:{SUBTEXT};"
            f"border:none;padding:4px 8px;font-weight:bold;}}"
            f"QTableWidget::item{{padding:4px 8px;}}"
            f"QTableWidget::item:selected{{background:{ACCENT};color:white;}}"
        )
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        tbl.setVerticalScrollMode(QTableWidget.ScrollPerPixel)

        for i, r in enumerate(rows):
            size_item = QTableWidgetItem(human_size(r.get("total_bytes", 0)))
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tbl.setItem(i, 0, size_item)

            files_item = QTableWidgetItem(f"{r.get('file_count', 0):,}")
            files_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tbl.setItem(i, 1, files_item)

            dom = r.get("dominance") or 0
            dom_text = f"{dom*100:.0f}%" if dom else "—"
            dom_item = QTableWidgetItem(dom_text)
            dom_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tbl.setItem(i, 2, dom_item)

            folder_path = r.get("folder", "")
            folder_text = folder_path + _mirror_marker(r)
            folder_item = QTableWidgetItem(folder_text)
            mirrors = r.get("mirrors") or []
            tip_lines = [folder_path]
            if mirrors:
                tip_lines.append("")
                tip_lines.append("Mirrors:")
                for m in mirrors:
                    tip_lines.append(
                        f"  {m['folder']}  ({m['file_count']:,} files, "
                        f"Δ={m.get('files_delta', 0):+,})"
                    )
            folder_item.setToolTip("\n".join(tip_lines))
            tbl.setItem(i, 3, folder_item)

        tbl.resizeRowsToContents()
        tbl.setMaximumHeight(_TABLE_MAX_H)
        tbl.setMinimumHeight(min(_TABLE_MAX_H,
                                 28 * min(len(rows), 6) + 32))
        tbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._body_lay.addWidget(tbl)


class QuickAnalysisPanel(QWidget):
    """Run, browse, and export heuristic folder-classification runs."""

    status_message = Signal(str, str)  # (msg, level)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db_path: str = ""
        self._worker: QuickAnalysisWorker | None = None
        self._results: list[dict] = []
        self._current_run_id: int | None = None
        self._build_ui()

    # ── public API ────────────────────────────────────────────────────
    def set_db(self, db_path: str) -> None:
        self._db_path = db_path or ""
        has_db = bool(self._db_path)
        self.run_btn.setEnabled(has_db)
        self.history_btn.setEnabled(has_db)
        self._refresh_state_buttons()

    def auto_load_last_run(self) -> None:
        if not self._db_path:
            return
        try:
            runs = list_quick_analysis_runs(self._db_path)
        except Exception:
            runs = []
        if runs:
            self._load_run(runs[0]["id"])

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*Margins.NONE)
        lay.setSpacing(Spacing.NONE)

        ctrl = QWidget()
        ctrl.setStyleSheet(f"background:{PANEL_BG};border-bottom:1px solid {BORDER};")
        ctrl.setFixedHeight(Sizes.HEADER_H_XL)
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(Spacing.LG, Spacing.NONE, Spacing.LG, Spacing.NONE)
        cl.setSpacing(Spacing.PX10)

        title_icon = QLabel()
        title_icon.setPixmap(_icons.pixmap("similar", 18, color=str(TEXT)))
        cl.addWidget(title_icon)
        title = QLabel("Quick Folder Analysis")
        title.setStyleSheet(f"color:{TEXT};font-weight:bold;font-size:13px;")
        cl.addWidget(title)
        cl.addStretch()

        cl.addWidget(self._sublabel("Min files:"))
        self.min_spin = QSpinBox()
        self.min_spin.setRange(1, 9999)
        self.min_spin.setValue(3)
        self.min_spin.setFixedWidth(62)
        self.min_spin.setFixedHeight(Sizes.CTRL_H)
        self.min_spin.setStyleSheet(self._input_ss())
        cl.addWidget(self.min_spin)

        self.mixed_chk = QCheckBox("Include mixed")
        self.mixed_chk.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        cl.addWidget(self.mixed_chk)

        ghost_ss = (
            f"QPushButton{{background:transparent;color:{SUBTEXT};"
            f"border:1px solid {BORDER};border-radius:6px;"
            f"padding:6px 12px;font-size:11px;}}"
            f"QPushButton:hover:enabled{{color:{TEXT};border-color:{TEXT};}}"
            f"QPushButton:disabled{{color:{BORDER};}}"
        )

        self.history_btn = QPushButton("History")
        self.history_btn.setIcon(_icons.icon("mdi.history", color=str(SUBTEXT)))
        self.history_btn.setIconSize(QSize(14, 14))
        self.history_btn.setStyleSheet(ghost_ss)
        self.history_btn.setEnabled(False)
        self.history_btn.clicked.connect(self._show_history_menu)
        cl.addWidget(self.history_btn)

        self.export_btn = QPushButton("Export")
        self.export_btn.setIcon(_icons.icon("download", color=str(SUBTEXT)))
        self.export_btn.setIconSize(QSize(14, 14))
        self.export_btn.setStyleSheet(ghost_ss)
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._show_export_menu)
        cl.addWidget(self.export_btn)

        self.delete_btn = QPushButton("Delete run")
        self.delete_btn.setIcon(_icons.icon("close", color=str(SUBTEXT)))
        self.delete_btn.setIconSize(QSize(14, 14))
        self.delete_btn.setStyleSheet(ghost_ss)
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._delete_current_run)
        cl.addWidget(self.delete_btn)

        self.run_btn = QPushButton("Analyze")
        self.run_btn.setIcon(_icons.icon("scan", color="#ffffff"))
        self.run_btn.setIconSize(QSize(14, 14))
        self.run_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:white;border:none;"
            f"border-radius:6px;padding:6px 16px;font-weight:bold;}}"
            f"QPushButton:disabled{{background:{BORDER};color:{SUBTEXT};}}"
        )
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._run_analysis)
        cl.addWidget(self.run_btn)

        lay.addWidget(ctrl)

        info = QWidget()
        info.setStyleSheet(f"background:{DARK_BG};border-bottom:1px solid {BORDER};")
        info.setFixedHeight(28)
        il = QHBoxLayout(info)
        il.setContentsMargins(Spacing.LG, 0, Spacing.LG, 0)
        self._info_lbl = QLabel("No run loaded.")
        self._info_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        il.addWidget(self._info_lbl)
        il.addStretch()
        lay.addWidget(info)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"QScrollArea{{background:{DARK_BG};border:none;}}"
        )
        self._content = QWidget()
        self._content.setStyleSheet(f"background:{DARK_BG};")
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        self._content_lay.setSpacing(Spacing.MD)
        self._content_lay.addStretch()
        self._scroll.setWidget(self._content)
        lay.addWidget(self._scroll, 1)

    def _sublabel(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        return lbl

    def _input_ss(self) -> str:
        return (
            f"QSpinBox{{background:{DARK_BG};color:{TEXT};border:1px solid {BORDER};"
            f"border-radius:6px;padding:4px 8px;font-size:11px;}}"
            f"QSpinBox:focus{{border-color:{ACCENT};}}"
        )

    # ── run / load / render ───────────────────────────────────────────
    def _run_analysis(self) -> None:
        if not self._db_path or self._worker is not None:
            return
        self.run_btn.setEnabled(False)
        self.run_btn.setText("Analyzing…")
        self.status_message.emit("Running quick analysis…", "info")

        worker = QuickAnalysisWorker(
            self._db_path,
            min_files=int(self.min_spin.value()),
            include_mixed=self.mixed_chk.isChecked(),
            scan_ids=None,
            scope_label="all-scans",
        )

        reg = ProcessRegistry.instance()
        pid = reg.register(
            name="Quick folder analysis",
            cancel_cb=worker.stop,
            kill_cb=worker.terminate,
        )
        worker._pid = pid

        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_error)
        worker.run_saved.connect(self._on_run_saved)
        self._worker = worker
        worker.start()

    def _on_finished(self, results: list) -> None:
        self._worker = None
        self.run_btn.setEnabled(bool(self._db_path))
        self.run_btn.setText("Analyze")
        self._results = list(results)
        self._render(self._results)
        if not self._results:
            self.status_message.emit("No classified folders found.", "info")
            self._info_lbl.setText("No classified folders found.")
        else:
            self.status_message.emit(
                f"Quick analysis complete — {len(self._results)} folder(s).", "info"
            )
            self._info_lbl.setText(
                f"Current run: {len(self._results)} folder(s)"
                + (f"  •  run #{self._current_run_id}" if self._current_run_id else "")
            )
        self._refresh_state_buttons()

    def _on_run_saved(self, run_id: int) -> None:
        self._current_run_id = run_id

    def _on_error(self, msg: str) -> None:
        self._worker = None
        self.run_btn.setEnabled(bool(self._db_path))
        self.run_btn.setText("Analyze")
        self.status_message.emit(f"Quick analysis failed: {msg}", "error")

    def _render(self, results: list[dict]) -> None:
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._sections: dict[str, _CategorySection] = {}

        by_cat: dict[str, list[dict]] = {}
        for r in results:
            by_cat.setdefault(r.get("category", "other"), []).append(r)
        ordered_cats: list[str] = [c for c in CATEGORY_ORDER if c in by_cat]
        ordered_cats += [c for c in by_cat if c not in CATEGORY_ORDER]

        if ordered_cats:
            self._content_lay.addWidget(self._build_jump_bar(ordered_cats, by_cat))

        for idx, cat in enumerate(ordered_cats):
            sect = _CategorySection(cat, by_cat[cat], expanded=(idx == 0))
            self._sections[cat] = sect
            self._content_lay.addWidget(sect)

        self._content_lay.addStretch()

    def _build_jump_bar(self, cats: list[str],
                        by_cat: dict[str, list[dict]]) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame{{background:{PANEL_BG};border:1px solid {BORDER};"
            f"border-radius:8px;}}"
        )
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        outer.setSpacing(Spacing.XS if hasattr(Spacing, "XS") else 4)

        top = QHBoxLayout()
        top.setSpacing(Spacing.SM)
        lbl = QLabel("Jump to category")
        lbl.setStyleSheet(f"color:{SUBTEXT};font-size:11px;font-weight:bold;")
        top.addWidget(lbl)
        top.addStretch()

        ghost = (
            f"QPushButton{{background:transparent;color:{SUBTEXT};"
            f"border:1px solid {BORDER};border-radius:6px;"
            f"padding:3px 10px;font-size:10px;}}"
            f"QPushButton:hover{{color:{TEXT};border-color:{TEXT};}}"
        )
        expand_btn = QPushButton("Expand all")
        expand_btn.setStyleSheet(ghost)
        expand_btn.clicked.connect(lambda: self._set_all_expanded(True))
        top.addWidget(expand_btn)
        collapse_btn = QPushButton("Collapse all")
        collapse_btn.setStyleSheet(ghost)
        collapse_btn.clicked.connect(lambda: self._set_all_expanded(False))
        top.addWidget(collapse_btn)
        outer.addLayout(top)

        chip_wrap = QWidget()
        chip_lay = QHBoxLayout(chip_wrap)
        chip_lay.setContentsMargins(0, 0, 0, 0)
        chip_lay.setSpacing(6)

        chip_ss = (
            f"QPushButton{{background:{DARK_BG};color:{TEXT};"
            f"border:1px solid {BORDER};border-radius:10px;"
            f"padding:3px 10px;font-size:10px;}}"
            f"QPushButton:hover{{border-color:{ACCENT};color:{ACCENT};}}"
        )
        for cat in cats:
            rows = by_cat[cat]
            total = sum(r.get("total_bytes", 0) for r in rows)
            chip = QPushButton(f"{cat}  ({len(rows):,} · {human_size(total)})")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(chip_ss)
            chip.clicked.connect(lambda _=False, c=cat: self._jump_to(c))
            chip_lay.addWidget(chip)
        chip_lay.addStretch()
        outer.addWidget(chip_wrap)
        return bar

    def _set_all_expanded(self, expanded: bool) -> None:
        for sect in getattr(self, "_sections", {}).values():
            sect.expand(expanded)

    def _jump_to(self, category: str) -> None:
        sect = getattr(self, "_sections", {}).get(category)
        if sect is None:
            return
        sect.expand(True)
        self._scroll.ensureWidgetVisible(sect, 0, 12)

    # ── history / export / delete ─────────────────────────────────────
    def _refresh_state_buttons(self) -> None:
        has_results = bool(self._results)
        self.export_btn.setEnabled(has_results)
        self.delete_btn.setEnabled(self._current_run_id is not None)

    def _show_history_menu(self) -> None:
        if not self._db_path:
            return
        try:
            runs = list_quick_analysis_runs(self._db_path)
        except Exception as exc:
            self.status_message.emit(f"History unavailable: {exc}", "error")
            return
        menu = QMenu(self)
        if not runs:
            act = menu.addAction("(no saved runs)")
            act.setEnabled(False)
        for r in runs[:30]:
            mix = "mixed" if r.get("include_mixed") else "no-mixed"
            label = (f"#{r['id']}  {r['ran_at']}  "
                     f"{r['row_count']} rows  min={r['min_files']}  {mix}")
            act = menu.addAction(label)
            act.triggered.connect(lambda _=False, rid=r["id"]: self._load_run(rid))
        menu.exec_(self.history_btn.mapToGlobal(self.history_btn.rect().bottomLeft()))

    def _load_run(self, run_id: int) -> None:
        try:
            run = load_quick_analysis_run(self._db_path, run_id)
        except Exception as exc:
            self.status_message.emit(f"Failed to load run #{run_id}: {exc}", "error")
            return
        if run is None:
            self.status_message.emit(f"Run #{run_id} not found.", "error")
            return
        self._current_run_id = run_id
        self._results = list(run.get("results") or [])
        self.min_spin.setValue(int(run.get("min_files") or 3))
        self.mixed_chk.setChecked(bool(run.get("include_mixed")))
        self._render(self._results)
        self._info_lbl.setText(
            f"Run #{run_id}  •  {run.get('ran_at', '')}  •  "
            f"{len(self._results)} folder(s)"
        )
        self.status_message.emit(f"Loaded quick-analysis run #{run_id}.", "info")
        self._refresh_state_buttons()

    def _show_export_menu(self) -> None:
        if not self._results:
            return
        menu = QMenu(self)
        menu.addAction("Export as CSV…", self._export_csv)
        menu.addAction("Export as JSON…", self._export_json)
        menu.exec_(self.export_btn.mapToGlobal(self.export_btn.rect().bottomLeft()))

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export quick-analysis as CSV",
            "quick-analysis.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            export_quick_analysis_csv(self._results, path)
            self.status_message.emit(f"Exported CSV → {path}", "info")
        except Exception as exc:
            self.status_message.emit(f"CSV export failed: {exc}", "error")

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export quick-analysis as JSON",
            "quick-analysis.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            export_quick_analysis_json(self._results, path)
            self.status_message.emit(f"Exported JSON → {path}", "info")
        except Exception as exc:
            self.status_message.emit(f"JSON export failed: {exc}", "error")

    def _delete_current_run(self) -> None:
        if self._current_run_id is None:
            return
        run_id = self._current_run_id
        confirm = QMessageBox.question(
            self, "Delete quick-analysis run",
            f"Delete saved run #{run_id}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            delete_quick_analysis_run(self._db_path, run_id)
        except Exception as exc:
            self.status_message.emit(f"Delete failed: {exc}", "error")
            return
        self.status_message.emit(f"Deleted quick-analysis run #{run_id}.", "info")
        self._current_run_id = None
        self._info_lbl.setText(
            f"Current run: {len(self._results)} folder(s) (no longer saved)"
        )
        self._refresh_state_buttons()
