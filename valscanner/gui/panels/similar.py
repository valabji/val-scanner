from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QProgressBar, QScrollArea, QSpinBox, QComboBox,
)

from ..constants import DARK_BG, PANEL_BG, ACCENT, TEXT, SUBTEXT, BORDER, GREEN
from ..workers import AnalysisWorker
from .process import ProcessRegistry
from ...core.db import list_scans
from ...core.schema import human_size

LABEL_COLORS: dict[str, str] = {
    "near-identical":   "#f38ba8",
    "highly similar":   "#fab387",
    "similar":          "#f9e2af",
    "possibly related": "#a6e3a1",
}


class FolderPairCard(QFrame):
    open_folder = Signal(str)

    def __init__(self, result: dict, is_child: bool = False, parent=None):
        super().__init__(parent)
        self._is_child = is_child
        bg     = DARK_BG  if is_child else PANEL_BG
        margin = "2px 0px" if is_child else "4px 8px"
        self.setStyleSheet(f"""
            FolderPairCard {{
                background: {bg};
                border: 1px solid {BORDER};
                border-radius: {"6px" if is_child else "10px"};
                margin: {margin};
            }}
        """)
        self._build(result)

    def _build(self, r: dict) -> None:
        lay = QVBoxLayout(self)
        m   = 8 if self._is_child else 14
        lay.setContentsMargins(m, 10, m, 10)
        lay.setSpacing(6)

        lc       = LABEL_COLORS.get(r["label"], "#9E9E9E")
        children = r.get("children", [])

        hdr = QHBoxLayout()
        hdr.setSpacing(6)

        badge = QLabel(f"  {r['label'].upper()}  ")
        badge.setStyleSheet(
            f"background:{lc}22;color:{lc};border:1px solid {lc};"
            f"border-radius:8px;padding:2px 6px;font-size:10px;font-weight:bold;"
        )
        hdr.addWidget(badge)

        score_lbl = QLabel(f"  {int(r['score']*100)}%")
        score_lbl.setStyleSheet(
            f"color:{lc};font-size:{'11px' if self._is_child else '13px'};font-weight:bold;"
        )
        hdr.addWidget(score_lbl)
        hdr.addStretch()

        if children and not self._is_child:
            n              = len(children)
            total_sub_files = sum(c.get("files_a", 0) + c.get("files_b", 0) for c in children)
            sub_badge = QLabel(
                f"  ＋{n} subfolder pair{'s' if n>1 else ''}  ·  {total_sub_files:,} more files  "
            )
            sub_badge.setStyleSheet(
                f"color:{ACCENT};background:{ACCENT:11};border:1px solid {ACCENT:44};"
                f"border-radius:8px;padding:2px 8px;font-size:10px;"
            )
            hdr.addWidget(sub_badge)

        if not self._is_child:
            dismiss = QPushButton("✓ Dismiss")
            dismiss.setFixedSize(80, 24)
            dismiss.setStyleSheet(
                f"QPushButton{{background:transparent;color:{SUBTEXT};"
                f"border:1px solid {BORDER};border-radius:6px;font-size:10px;}}"
                f"QPushButton:hover{{color:{TEXT};border-color:{TEXT};}}"
            )
            dismiss.clicked.connect(self.hide)
            hdr.addWidget(dismiss)

        lay.addLayout(hdr)

        if not self._is_child:
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(r["score"] * 100))
            bar.setFixedHeight(4)
            bar.setTextVisible(False)
            bar.setStyleSheet(
                f"QProgressBar{{background:{DARK_BG};border:none;border-radius:2px;}}"
                f"QProgressBar::chunk{{background:{lc};border-radius:2px;}}"
            )
            lay.addWidget(bar)

        parent_a   = r.get("_parent_a", "")
        parent_b   = r.get("_parent_b", "")
        multi_scan = r.get("scan_id_a", 0) != r.get("scan_id_b", 0)

        for fkey, bkey, cnt_key, label_key in (
            ("folder_a", "bytes_a", "files_a", "scan_label_a"),
            ("folder_b", "bytes_b", "files_b", "scan_label_b"),
        ):
            abs_path = r[fkey]
            scan_lbl = r.get(label_key, "")
            if self._is_child:
                base = parent_a if fkey == "folder_a" else parent_b
                try:
                    rel     = str(Path(abs_path).relative_to(base))
                    display = f"  ↳ …/{rel}"
                except ValueError:
                    display = abs_path
            elif multi_scan and scan_lbl:
                display = f"[{scan_lbl}]  {abs_path}"
            else:
                display = abs_path

            frow = QHBoxLayout()
            frow.setSpacing(6)
            icon_lbl = QLabel("📁")
            icon_lbl.setFixedWidth(18)
            frow.addWidget(icon_lbl)

            pl = QLabel(display)
            pl.setStyleSheet(
                f"color:{SUBTEXT if self._is_child else TEXT};font-size:11px;"
            )
            pl.setWordWrap(True)
            pl.setToolTip(abs_path)
            frow.addWidget(pl, 1)

            ml = QLabel(f"{human_size(r[bkey])}  ·  {r[cnt_key]:,} files")
            ml.setStyleSheet(f"color:{SUBTEXT};font-size:10px;min-width:110px;")
            ml.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            frow.addWidget(ml)

            ob = QPushButton("Open")
            ob.setFixedSize(46, 20)
            ob.setStyleSheet(
                f"QPushButton{{background:transparent;color:{ACCENT};"
                f"border:1px solid {ACCENT:55};border-radius:4px;font-size:10px;}}"
                f"QPushButton:hover{{background:{ACCENT};color:white;border-color:{ACCENT};}}"
            )
            fp = abs_path
            ob.clicked.connect(lambda _, p=fp: self.open_folder.emit(p))
            frow.addWidget(ob)
            lay.addLayout(frow)

        sigs = QHBoxLayout()
        sigs.setSpacing(6)
        for icon, key in (("📛 Names", "name_score"), ("📦 Exts", "ext_score"), ("⚖️ Size", "size_score")):
            c = QLabel(f"{icon} {int(r[key]*100)}%")
            c.setStyleSheet(
                f"color:{SUBTEXT};background:{DARK_BG};border:1px solid {BORDER:22};"
                f"border-radius:5px;padding:1px 6px;font-size:10px;"
            )
            sigs.addWidget(c)
        if r.get("hash_score", 0) > 0:
            hc = QLabel(f"🔑 Hashes {int(r['hash_score']*100)}%")
            hc.setStyleSheet(
                f"color:{GREEN};background:{DARK_BG};border:1px solid {GREEN:44};"
                f"border-radius:5px;padding:1px 6px;font-size:10px;"
            )
            sigs.addWidget(hc)
        if r.get("shared_names", 0):
            sigs.addWidget(QLabel(f"  {r['shared_names']} shared names"))
        if r.get("shared_hashes", 0):
            sh = QLabel(f"  {r['shared_hashes']} identical files")
            sh.setStyleSheet(f"color:{GREEN};font-size:10px;")
            sigs.addWidget(sh)
        sigs.addStretch()
        lay.addLayout(sigs)

        if children and not self._is_child:
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet(f"color:{BORDER:44};")
            lay.addWidget(sep)

            n               = len(children)
            total_cf        = sum(c.get("files_a", 0) + c.get("files_b", 0) for c in children)
            toggle_row      = QHBoxLayout()
            self._toggle_btn = QPushButton(
                f"▶  {n} duplicate subfolder pair{'s' if n>1 else ''} hidden  ({total_cf:,} files)"
            )
            self._toggle_btn.setStyleSheet(
                f"QPushButton{{background:{ACCENT:0a};color:{ACCENT};border:1px solid {ACCENT:33};"
                f"border-radius:6px;font-size:11px;text-align:left;padding:5px 10px;}}"
                f"QPushButton:hover{{background:{ACCENT:22};border-color:{ACCENT};}}"
            )
            toggle_row.addWidget(self._toggle_btn, 1)
            lay.addLayout(toggle_row)

            self._children_widget = QWidget()
            self._children_widget.setStyleSheet(
                f"background:{DARK_BG:88};border-radius:6px;border:1px dashed {BORDER:66};"
            )
            cl = QVBoxLayout(self._children_widget)
            cl.setContentsMargins(6, 6, 6, 6)
            cl.setSpacing(3)

            for child in children:
                enriched   = dict(child, _parent_a=r["folder_a"], _parent_b=r["folder_b"])
                child_card = FolderPairCard(enriched, is_child=True)
                child_card.open_folder.connect(self.open_folder)
                cl.addWidget(child_card)

            self._children_widget.hide()
            lay.addWidget(self._children_widget)
            self._toggle_btn.clicked.connect(self._toggle_children)

    def _toggle_children(self) -> None:
        visible = self._children_widget.isVisible()
        self._children_widget.setVisible(not visible)
        n = self._children_widget.layout().count()
        if visible:
            self._toggle_btn.setText(
                f"▶  {n} duplicate subfolder pair{'s' if n>1 else ''} hidden"
            )
        else:
            self._toggle_btn.setText(
                f"▼  Hide {n} subfolder pair{'s' if n>1 else ''}"
            )


class SimilarFoldersPanel(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db_path   = ""
        self._worker    = None
        self._results:  list = []
        self._scan_pills: dict[int, QPushButton] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        ctrl = QWidget()
        ctrl.setStyleSheet(f"background:{PANEL_BG};border-bottom:1px solid {BORDER};")
        ctrl.setFixedHeight(52)
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(16, 0, 16, 0)
        cl.setSpacing(10)
        title = QLabel("🗂  Similar & Duplicate Folder Detector")
        title.setStyleSheet(f"color:{TEXT};font-weight:bold;font-size:13px;")
        cl.addWidget(title)
        cl.addStretch()

        cl.addWidget(self._sublabel("Min files:"))
        self.min_spin = QSpinBox()
        self.min_spin.setRange(1, 9999)
        self.min_spin.setValue(3)
        self.min_spin.setFixedWidth(62)
        self.min_spin.setFixedHeight(28)
        self.min_spin.setStyleSheet(self._input_ss())
        cl.addWidget(self.min_spin)

        cl.addWidget(self._sublabel("Threshold:"))
        self.thresh_combo = QComboBox()
        self.thresh_combo.addItems(["0.30 — broad", "0.40 — balanced", "0.55 — strict", "0.70 — very strict"])
        self.thresh_combo.setCurrentIndex(1)
        self.thresh_combo.setFixedWidth(150)
        cl.addWidget(self.thresh_combo)

        self.analyze_btn = QPushButton("⚡ Analyze")
        self.analyze_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:white;border:none;"
            f"border-radius:6px;padding:6px 16px;font-weight:bold;}}"
            f"QPushButton:disabled{{background:{BORDER};color:{SUBTEXT};}}"
        )
        self.analyze_btn.clicked.connect(self._run_analysis)
        self.analyze_btn.setEnabled(False)
        cl.addWidget(self.analyze_btn)
        lay.addWidget(ctrl)

        part_bar = QWidget()
        part_bar.setStyleSheet(f"background:{DARK_BG};border-bottom:1px solid {BORDER};")
        part_bar.setFixedHeight(44)
        pl = QHBoxLayout(part_bar)
        pl.setContentsMargins(16, 0, 8, 0)
        pl.setSpacing(8)
        part_lbl = self._sublabel("Partitions:")
        part_lbl.setFixedWidth(68)
        pl.addWidget(part_lbl)

        self._part_scroll = QScrollArea()
        self._part_scroll.setWidgetResizable(True)
        self._part_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._part_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._part_scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:transparent;}}"
            f"QScrollBar:horizontal{{height:3px;background:{DARK_BG};}}"
            f"QScrollBar::handle:horizontal{{background:{BORDER};border-radius:1px;}}"
        )
        self._part_scroll.setFixedHeight(40)

        self._part_inner  = QWidget()
        self._part_inner.setStyleSheet("background:transparent;")
        self._part_layout = QHBoxLayout(self._part_inner)
        self._part_layout.setContentsMargins(0, 0, 8, 0)
        self._part_layout.setSpacing(6)
        self._no_parts_lbl = QLabel("No scans loaded yet.")
        self._no_parts_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:11px;font-style:italic;")
        self._part_layout.addWidget(self._no_parts_lbl)
        self._part_layout.addStretch()
        self._part_scroll.setWidget(self._part_inner)
        pl.addWidget(self._part_scroll, 1)
        lay.addWidget(part_bar)

        view_bar = QWidget()
        view_bar.setStyleSheet(f"background:{DARK_BG};border-bottom:1px solid {BORDER};")
        view_bar.setFixedHeight(36)
        vl = QHBoxLayout(view_bar)
        vl.setContentsMargins(16, 0, 16, 0)
        vl.setSpacing(8)
        vl.addWidget(self._sublabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Score ↓", "Total size ↓", "Files ↓", "Name ↑"])
        self.sort_combo.setFixedWidth(130)
        self.sort_combo.setFixedHeight(24)
        self.sort_combo.currentIndexChanged.connect(self._apply_sort_filter)
        vl.addWidget(self.sort_combo)
        vl.addSpacing(12)
        vl.addWidget(self._sublabel("Min size:"))
        self.min_size_combo = QComboBox()
        self.min_size_combo.setEditable(True)
        self.min_size_combo.addItems(["0", "1 MB", "10 MB", "100 MB", "500 MB", "1 GB"])
        self.min_size_combo.setCurrentIndex(0)
        self.min_size_combo.setFixedWidth(90)
        self.min_size_combo.setFixedHeight(24)
        self.min_size_combo.currentTextChanged.connect(self._apply_sort_filter)
        vl.addWidget(self.min_size_combo)
        vl.addStretch()
        self.result_count_lbl = QLabel()
        self.result_count_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        vl.addWidget(self.result_count_lbl)
        lay.addWidget(view_bar)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.progress.setStyleSheet(
            f"QProgressBar{{border:none;background:{DARK_BG};}}"
            f"QProgressBar::chunk{{background:{ACCENT};}}"
        )
        lay.addWidget(self.progress)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{border:none;background:{DARK_BG};}}")
        self.cards_widget = QWidget()
        self.cards_widget.setStyleSheet(f"background:{DARK_BG};")
        self.cards_lay = QVBoxLayout(self.cards_widget)
        self.cards_lay.setContentsMargins(0, 8, 0, 16)
        self.cards_lay.setSpacing(4)
        self.empty_lbl = QLabel("Scan a folder first, then click ⚡ Analyze to find similar folders.")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:13px;padding:60px;")
        self.cards_lay.addWidget(self.empty_lbl)
        self.cards_lay.addStretch()
        scroll.setWidget(self.cards_widget)
        lay.addWidget(scroll, 1)

        self.footer = QLabel()
        self.footer.setAlignment(Qt.AlignCenter)
        self.footer.setFixedHeight(30)
        self.footer.setStyleSheet(
            f"color:{SUBTEXT};font-size:11px;background:{PANEL_BG};border-top:1px solid {BORDER};"
        )
        lay.addWidget(self.footer)

    @staticmethod
    def _sublabel(text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        return l

    @staticmethod
    def _input_ss() -> str:
        return (
            f"QSpinBox{{background:{DARK_BG};color:{TEXT};border:1px solid {BORDER};"
            f"border-radius:5px;padding:3px 6px;font-size:11px;}}"
            f"QSpinBox:focus{{border-color:{ACCENT};}}"
        )

    @staticmethod
    def _parse_size(text: str) -> int:
        text = text.strip().upper().replace(",", "")
        if not text or text in ("0", "-", "—"):
            return 0
        units = [("TB", 1 << 40), ("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10), ("B", 1)]
        for suffix, mult in units:
            if text.endswith(suffix):
                try:
                    return int(float(text[:-len(suffix)].strip()) * mult)
                except ValueError:
                    return 0
        try:
            return int(text)
        except ValueError:
            return 0

    def set_db(self, db_path: str) -> None:
        self._db_path = db_path
        self.analyze_btn.setEnabled(bool(db_path))
        self._rebuild_partition_row()

    def _rebuild_partition_row(self) -> None:
        while self._part_layout.count() > 1:
            item = self._part_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._scan_pills = {}

        scans = list_scans(self._db_path) if self._db_path else []
        if not scans:
            self._part_layout.insertWidget(0, self._no_parts_lbl)
            return

        _pill_ss = (
            f"QPushButton{{background:transparent;color:{SUBTEXT};"
            f"border:1px solid {BORDER};border-radius:10px;"
            f"padding:2px 12px;font-size:11px;}}"
            f"QPushButton:checked{{background:{ACCENT:22};color:{ACCENT};"
            f"border-color:{ACCENT};}}"
            f"QPushButton:hover:!checked{{color:{TEXT};border-color:#5a5a7a;}}"
        )
        for s in scans:
            label = s["label"] or Path(s["root"]).name
            fc    = s.get("file_count") or 0
            size  = s.get("total_human") or ""
            text  = f"{label}  ·  {fc:,} files" + (f"  ·  {size}" if size else "")
            pill  = QPushButton(text)
            pill.setToolTip(f"Root: {s['root']}\nScan ID: {s['id']}")
            pill.setCheckable(True)
            pill.setFixedHeight(26)
            pill.setStyleSheet(_pill_ss)
            self._part_layout.insertWidget(self._part_layout.count() - 1, pill)
            self._scan_pills[s["id"]] = pill

    def _get_selected_scan_ids(self) -> list | None:
        selected = [sid for sid, btn in self._scan_pills.items() if btn.isChecked()]
        return selected if selected else None

    def _run_analysis(self) -> None:
        if not self._db_path:
            return
        min_files = self.min_spin.value()
        threshold = float(self.thresh_combo.currentText().split()[0])
        while self.cards_lay.count() > 2:
            item = self.cards_lay.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        scan_ids = self._get_selected_scan_ids()
        scope    = ("  ·  ".join(
            self._scan_pills[sid].text().split("·")[0].strip()
            for sid in scan_ids if sid in self._scan_pills
        ) if scan_ids else "all partitions")

        self.empty_lbl.hide()
        self.progress.show()
        self.analyze_btn.setEnabled(False)
        self.footer.setText(f"Analysing {scope}…")
        self.status_message.emit(f"Comparing folders for similarity across {scope}…")
        self._worker = AnalysisWorker(self._db_path, min_files, threshold, scan_ids=scan_ids)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

        # Register with process monitor
        reg = ProcessRegistry.instance()
        pid = reg.register(
            name="Similarity analysis",
            cancel_cb=self._worker.stop,
            kill_cb=self._worker.terminate,
        )
        self._worker._pid = pid

    def _on_done(self, results: list) -> None:
        self.progress.hide()
        self.analyze_btn.setEnabled(True)
        self._results = results
        self._apply_sort_filter()
        lc: dict = {}
        for r in results:
            lc[r["label"]] = lc.get(r["label"], 0) + 1
        summary = (
            f"Found {len(results)} pairs:  " + "  ·  ".join(f"{v} {k}" for k, v in lc.items())
            if results else "No similar folders found above the threshold. 🎉"
        )
        self.status_message.emit(summary)

    def _apply_sort_filter(self) -> None:
        results   = list(self._results)
        min_bytes = self._parse_size(self.min_size_combo.currentText())
        if min_bytes > 0:
            results = [r for r in results if r["bytes_a"] + r["bytes_b"] >= min_bytes]

        idx = self.sort_combo.currentIndex()
        if idx == 0:
            results.sort(key=lambda r: r["score"], reverse=True)
        elif idx == 1:
            results.sort(key=lambda r: r["bytes_a"] + r["bytes_b"], reverse=True)
        elif idx == 2:
            results.sort(key=lambda r: r["files_a"] + r["files_b"], reverse=True)
        elif idx == 3:
            results.sort(key=lambda r: r["folder_a"].lower())

        while self.cards_lay.count() > 2:
            item = self.cards_lay.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

        if not results:
            msg = ("No pairs match the current filters." if self._results
                   else "No similar folders found above the threshold. 🎉")
            self.empty_lbl.setText(msg)
            self.empty_lbl.show()
            self.footer.setText("No matches found.")
            self.result_count_lbl.setText("")
            return

        self.empty_lbl.hide()
        for r in results:
            card = FolderPairCard(r)
            card.open_folder.connect(self._open_folder)
            self.cards_lay.insertWidget(self.cards_lay.count() - 1, card)

        shown = len(results)
        total = len(self._results)
        self.result_count_lbl.setText(
            f"{shown} of {total} pairs" if shown != total else f"{total} pairs"
        )
        lc2: dict = {}
        for r in results:
            lc2[r["label"]] = lc2.get(r["label"], 0) + 1
        self.footer.setText("  ·  ".join(f"{v} {k}" for k, v in lc2.items()))

    def _on_error(self, msg: str) -> None:
        self.progress.hide()
        self.analyze_btn.setEnabled(True)
        self.empty_lbl.setText(f"Error: {msg}")
        self.empty_lbl.show()
        self.footer.setText("Analysis failed.")
        self.status_message.emit(f"⚠ Analysis error: {msg}")

    def _open_folder(self, path: str) -> None:
        p      = Path(path)
        target = str(p) if p.is_dir() else str(p.parent)
        if sys.platform == "darwin":
            subprocess.Popen(["open", target])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", target])
        else:
            subprocess.Popen(["xdg-open", target])
