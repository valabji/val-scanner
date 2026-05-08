from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit,
    QDialogButtonBox, QFrame, QPushButton, QGridLayout,
)

from .constants import CATEGORY_COLORS, DARK_BG, PANEL_BG, ACCENT, TEXT, SUBTEXT, BORDER
from ..core.metadata import PIL_AVAILABLE, FFMPEG_AVAILABLE


class ScanOptionsDialog(QDialog):
    def __init__(self, parent=None, options: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Scan Options")
        self.setMinimumWidth(440)
        self.setStyleSheet(f"""
            QDialog       {{ background:{DARK_BG}; color:{TEXT}; }}
            QGroupBox     {{ color:{SUBTEXT}; font-size:11px; font-weight:bold;
                            border:1px solid {BORDER}; border-radius:6px; margin-top:10px;
                            padding:10px 8px 8px 8px; }}
            QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 4px; }}
            QLabel        {{ color:{TEXT}; font-size:12px; }}
            QCheckBox     {{ color:{TEXT}; font-size:12px; spacing:6px; }}
            QCheckBox::indicator {{
                width:16px; height:16px; border:1px solid {BORDER};
                border-radius:4px; background:{DARK_BG};
            }}
            QCheckBox::indicator:checked {{ background:{ACCENT}; border-color:{ACCENT}; }}
            QCheckBox::indicator:hover   {{ border-color:{ACCENT}; }}
            QSpinBox {{
                background:{PANEL_BG}; color:{TEXT}; border:1px solid {BORDER};
                border-radius:5px; padding:3px 6px; font-size:12px;
            }}
            QSpinBox:focus {{ border-color:{ACCENT}; }}
        """)
        self._build_ui(options or {})

    def _build_ui(self, opts: dict) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        thumb_grp = QGroupBox("Thumbnails")
        tl = QVBoxLayout(thumb_grp)
        tl.setSpacing(8)

        self.thumb_chk = QCheckBox("Store thumbnails in database")
        self.thumb_chk.setChecked(opts.get("store_thumbnails", False))
        tl.addWidget(self.thumb_chk)

        caps = []
        caps.append("Images ✓ (Pillow)" if PIL_AVAILABLE    else "Images ✗ (install Pillow)")
        caps.append("Video ✓ (ffmpeg)"  if FFMPEG_AVAILABLE else "Video ✗ (ffmpeg not found)")
        cap_lbl = QLabel("  " + "  ·  ".join(caps))
        cap_lbl.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        tl.addWidget(cap_lbl)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Max size:"))
        self.thumb_size = QSpinBox()
        self.thumb_size.setRange(32, 512)
        self.thumb_size.setSingleStep(32)
        self.thumb_size.setValue(opts.get("thumb_size", 128))
        self.thumb_size.setSuffix(" px")
        self.thumb_size.setFixedWidth(90)
        row1.addWidget(self.thumb_size)
        row1.addSpacing(16)
        row1.addWidget(QLabel("JPEG quality:"))
        self.thumb_quality = QSpinBox()
        self.thumb_quality.setRange(40, 95)
        self.thumb_quality.setSingleStep(5)
        self.thumb_quality.setValue(opts.get("thumb_quality", 75))
        self.thumb_quality.setSuffix(" %")
        self.thumb_quality.setFixedWidth(80)
        row1.addWidget(self.thumb_quality)
        row1.addStretch()
        tl.addLayout(row1)

        self.thumb_chk.toggled.connect(lambda v: (
            self.thumb_size.setEnabled(v), self.thumb_quality.setEnabled(v)
        ))
        self.thumb_size.setEnabled(self.thumb_chk.isChecked())
        self.thumb_quality.setEnabled(self.thumb_chk.isChecked())
        lay.addWidget(thumb_grp)

        sample_grp = QGroupBox("Media Samples")
        sl = QVBoxLayout(sample_grp)
        sl.setSpacing(8)

        self.sample_chk = QCheckBox("Store audio / video samples in database")
        self.sample_chk.setChecked(opts.get("store_samples", False))
        sl.addWidget(self.sample_chk)

        ffmpeg_lbl = QLabel(
            f"  ffmpeg {'✓ found' if FFMPEG_AVAILABLE else '✗ not found — samples will be skipped'}"
        )
        ffmpeg_lbl.setStyleSheet(
            f"color:{'#a6e3a1' if FFMPEG_AVAILABLE else '#f38ba8'};font-size:11px;"
        )
        sl.addWidget(ffmpeg_lbl)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Duration:"))
        self.sample_dur = QSpinBox()
        self.sample_dur.setRange(1, 30)
        self.sample_dur.setValue(opts.get("sample_duration", 5))
        self.sample_dur.setSuffix(" s")
        self.sample_dur.setFixedWidth(70)
        row2.addWidget(self.sample_dur)
        note = QLabel("Low quality: audio 32 kbps mp3 · video 240p mp4")
        note.setStyleSheet(f"color:{SUBTEXT};font-size:11px;")
        row2.addSpacing(12)
        row2.addWidget(note)
        row2.addStretch()
        sl.addLayout(row2)

        self.sample_chk.toggled.connect(self.sample_dur.setEnabled)
        self.sample_dur.setEnabled(self.sample_chk.isChecked())
        lay.addWidget(sample_grp)

        filter_grp = QGroupBox("Filters")
        fl = QVBoxLayout(filter_grp)
        fl.setSpacing(6)

        folder_lbl = QLabel("Folders")
        folder_lbl.setStyleSheet(
            f"color:{SUBTEXT}; font-size:10px; font-weight:bold;"
        )
        fl.addWidget(folder_lbl)

        self.skip_hidden_dirs_chk = QCheckBox("Hidden folders  (names starting with .)")
        self.skip_hidden_dirs_chk.setChecked(opts.get("skip_hidden_dirs", True))
        fl.addWidget(self.skip_hidden_dirs_chk)

        self.skip_vcs_chk = QCheckBox("Version control  (.git, .svn, .hg, …)")
        self.skip_vcs_chk.setChecked(opts.get("skip_vcs", False))
        fl.addWidget(self.skip_vcs_chk)

        self.skip_system_chk = QCheckBox("System folders  (Windows, Library, /proc, …)")
        self.skip_system_chk.setChecked(opts.get("skip_system", False))
        fl.addWidget(self.skip_system_chk)

        self.skip_caches_chk = QCheckBox("Cache & build dirs  (node_modules, __pycache__, venv, …)")
        self.skip_caches_chk.setChecked(opts.get("skip_caches", False))
        fl.addWidget(self.skip_caches_chk)

        sep_hline = QFrame()
        sep_hline.setFrameShape(QFrame.HLine)
        sep_hline.setStyleSheet(f"color:{BORDER};")
        fl.addWidget(sep_hline)

        files_lbl = QLabel("Files")
        files_lbl.setStyleSheet(
            f"color:{SUBTEXT}; font-size:10px; font-weight:bold;"
        )
        fl.addWidget(files_lbl)

        self.skip_hidden_files_chk = QCheckBox("Hidden files  (names starting with .)")
        self.skip_hidden_files_chk.setChecked(opts.get("skip_hidden_files", False))
        fl.addWidget(self.skip_hidden_files_chk)

        self.skip_binaries_chk = QCheckBox("Binary / compiled  (.exe, .dll, .so, .pyc, …)")
        self.skip_binaries_chk.setChecked(opts.get("skip_binaries", False))
        fl.addWidget(self.skip_binaries_chk)

        self.skip_temp_chk = QCheckBox("Temporary files  (.tmp, .bak, .swp, .DS_Store, …)")
        self.skip_temp_chk.setChecked(opts.get("skip_temp", False))
        fl.addWidget(self.skip_temp_chk)

        self.skip_logs_chk = QCheckBox("Log files  (.log)")
        self.skip_logs_chk.setChecked(opts.get("skip_logs", False))
        fl.addWidget(self.skip_logs_chk)

        lay.addWidget(filter_grp)

        btns = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        btns.setStyleSheet(f"""
            QPushButton {{
                background:{ACCENT}; color:white; border:none;
                border-radius:6px; padding:6px 18px; font-weight:bold; font-size:12px;
            }}
            QPushButton:hover {{ background:#9d8fff; }}
            QPushButton[text="Cancel"] {{
                background:transparent; color:{TEXT}; border:1px solid {BORDER};
            }}
            QPushButton[text="Cancel"]:hover {{ background:{PANEL_BG}; }}
        """)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def get_options(self) -> dict:
        return {
            "store_thumbnails": self.thumb_chk.isChecked(),
            "thumb_size":       self.thumb_size.value(),
            "thumb_quality":    self.thumb_quality.value(),
            "store_samples":    self.sample_chk.isChecked(),
            "sample_duration":  self.sample_dur.value(),
            "skip_hidden_dirs":  self.skip_hidden_dirs_chk.isChecked(),
            "skip_vcs":          self.skip_vcs_chk.isChecked(),
            "skip_system":       self.skip_system_chk.isChecked(),
            "skip_caches":       self.skip_caches_chk.isChecked(),
            "skip_hidden_files": self.skip_hidden_files_chk.isChecked(),
            "skip_binaries":     self.skip_binaries_chk.isChecked(),
            "skip_temp":         self.skip_temp_chk.isChecked(),
            "skip_logs":         self.skip_logs_chk.isChecked(),
        }


_DLG_SS = f"""
    QDialog   {{ background:{DARK_BG}; color:{TEXT}; }}
    QGroupBox {{ color:{SUBTEXT}; font-size:11px; font-weight:bold;
                border:1px solid {BORDER}; border-radius:6px; margin-top:10px;
                padding:10px 8px 8px 8px; }}
    QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 4px; }}
    QLabel    {{ color:{TEXT}; font-size:12px; }}
    QCheckBox {{ color:{TEXT}; font-size:12px; spacing:6px; }}
    QCheckBox::indicator {{
        width:15px; height:15px; border:1px solid {BORDER};
        border-radius:4px; background:{DARK_BG};
    }}
    QCheckBox::indicator:checked {{ background:{ACCENT}; border-color:{ACCENT}; }}
    QCheckBox::indicator:hover   {{ border-color:{ACCENT}; }}
    QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {{
        background:{PANEL_BG}; color:{TEXT}; border:1px solid {BORDER};
        border-radius:5px; padding:3px 7px; font-size:12px;
    }}
    QDoubleSpinBox:focus, QLineEdit:focus, QComboBox:focus {{ border-color:{ACCENT}; }}
    QPushButton {{
        background:transparent; color:{SUBTEXT}; border:1px solid {BORDER};
        border-radius:5px; padding:3px 10px; font-size:11px;
    }}
    QPushButton:hover {{ color:{TEXT}; border-color:{ACCENT}; }}
"""


class ViewFiltersDialog(QDialog):
    """Non-modal dialog for live view-only filters (no re-scan needed)."""
    filters_changed = Signal(dict)

    def __init__(self, parent=None, filters: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("View Filters")
        self.setMinimumWidth(520)
        self.setStyleSheet(_DLG_SS)
        self._suppress = False
        self._build_ui(filters or {})

    def _build_ui(self, filters: dict) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # ── Categories ────────────────────────────────────────────────────────
        cat_grp = QGroupBox("Show categories")
        cg_lay  = QVBoxLayout(cat_grp)
        cg_lay.setSpacing(6)

        cat_grid = QGridLayout()
        cat_grid.setHorizontalSpacing(16)
        cat_grid.setVerticalSpacing(5)
        cats   = sorted(CATEGORY_COLORS.keys())
        hidden = set(filters.get("hidden_categories", ()))
        self._cat_chks: dict[str, QCheckBox] = {}
        mid = (len(cats) + 1) // 2
        for i, cat in enumerate(cats):
            col = i // mid
            row = i % mid
            chk = QCheckBox(cat)
            chk.setChecked(cat not in hidden)
            chk.toggled.connect(self._on_change)
            cat_grid.addWidget(chk, row, col)
            self._cat_chks[cat] = chk
        cg_lay.addLayout(cat_grid)

        btn_row = QHBoxLayout()
        for label, val in (("Select all", True), ("Select none", False)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, v=val: self._select_all_cats(v))
            btn_row.addWidget(b)
        btn_row.addStretch()
        cg_lay.addLayout(btn_row)
        lay.addWidget(cat_grp)

        # ── Size range ────────────────────────────────────────────────────────
        size_grp = QGroupBox("Size range  (0 = no limit)")
        sl = QHBoxLayout(size_grp)
        sl.setSpacing(8)

        sl.addWidget(QLabel("Min:"))
        self._min_spin = QDoubleSpinBox()
        self._min_spin.setRange(0, 999_999)
        self._min_spin.setDecimals(1)
        self._min_spin.setFixedWidth(90)
        sl.addWidget(self._min_spin)

        sl.addWidget(QLabel("Max:"))
        self._max_spin = QDoubleSpinBox()
        self._max_spin.setRange(0, 999_999)
        self._max_spin.setDecimals(1)
        self._max_spin.setFixedWidth(90)
        sl.addWidget(self._max_spin)

        self._size_unit = QComboBox()
        self._size_unit.addItems(["B", "KB", "MB", "GB"])
        self._size_unit.setCurrentIndex(2)
        self._size_unit.setFixedWidth(62)
        sl.addWidget(self._size_unit)
        sl.addStretch()

        # Restore saved size filter if present
        saved_min = filters.get("min_bytes", 0)
        saved_max = filters.get("max_bytes", 0)
        saved_unit_idx = filters.get("size_unit_idx", 2)
        self._size_unit.setCurrentIndex(saved_unit_idx)
        unit_mult = [1, 1024, 1024**2, 1024**3][saved_unit_idx]
        if unit_mult:
            self._min_spin.setValue(saved_min / unit_mult)
            self._max_spin.setValue(saved_max / unit_mult)

        self._min_spin.valueChanged.connect(self._on_change)
        self._max_spin.valueChanged.connect(self._on_change)
        self._size_unit.currentIndexChanged.connect(self._on_change)
        lay.addWidget(size_grp)

        # ── Extension filter ──────────────────────────────────────────────────
        ext_grp = QGroupBox("Extensions  (comma-separated, leave empty for all)")
        el = QVBoxLayout(ext_grp)
        self._ext_edit = QLineEdit()
        self._ext_edit.setPlaceholderText("e.g. jpg, png, mp4, pdf")
        saved_exts = filters.get("extensions", set())
        if saved_exts:
            self._ext_edit.setText(", ".join(sorted(saved_exts)))
        self._ext_timer = None
        self._ext_edit.textChanged.connect(self._on_ext_changed)
        el.addWidget(self._ext_edit)
        lay.addWidget(ext_grp)

        # ── Path & file filters ───────────────────────────────────────────────
        pf_grp = QGroupBox("Path & file filters  (hide matching items from view)")
        pf_lay = QVBoxLayout(pf_grp)
        pf_lay.setSpacing(5)

        _sub_lbl_ss = f"color:{SUBTEXT}; font-size:10px; font-weight:bold;"

        dir_lbl = QLabel("Folders"); dir_lbl.setStyleSheet(_sub_lbl_ss)
        pf_lay.addWidget(dir_lbl)

        self._pf_chks: dict[str, QCheckBox] = {}
        _FOLDER_PF = [
            ("hide_hidden_dirs",  "Hidden folders  (names starting with .)"),
            ("hide_vcs",          "Version control  (.git, .svn, .hg, …)"),
            ("hide_system",       "System folders  (Windows, Library, /proc, …)"),
            ("hide_caches",       "Cache & build dirs  (node_modules, __pycache__, venv, …)"),
        ]
        for key, label in _FOLDER_PF:
            chk = QCheckBox(label)
            chk.setChecked(filters.get(key, False))
            chk.toggled.connect(self._on_change)
            pf_lay.addWidget(chk)
            self._pf_chks[key] = chk

        sep_pf = QFrame(); sep_pf.setFrameShape(QFrame.HLine)
        sep_pf.setStyleSheet(f"color:{BORDER};")
        pf_lay.addWidget(sep_pf)

        file_lbl = QLabel("Files"); file_lbl.setStyleSheet(_sub_lbl_ss)
        pf_lay.addWidget(file_lbl)

        _FILE_PF = [
            ("hide_hidden_files", "Hidden files  (names starting with .)"),
            ("hide_binaries",     "Binary / compiled  (.exe, .dll, .so, .pyc, …)"),
            ("hide_temp",         "Temporary files  (.tmp, .bak, .swp, .DS_Store, …)"),
            ("hide_logs",         "Log files  (.log)"),
        ]
        for key, label in _FILE_PF:
            chk = QCheckBox(label)
            chk.setChecked(filters.get(key, False))
            chk.toggled.connect(self._on_change)
            pf_lay.addWidget(chk)
            self._pf_chks[key] = chk

        lay.addWidget(pf_grp)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_bar = QHBoxLayout()
        reset_btn = QPushButton("Reset all filters")
        reset_btn.clicked.connect(self.reset)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_bar.addWidget(reset_btn)
        btn_bar.addStretch()
        btn_bar.addWidget(close_btn)
        lay.addLayout(btn_bar)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _select_all_cats(self, checked: bool) -> None:
        self._suppress = True
        for chk in self._cat_chks.values():
            chk.setChecked(checked)
        self._suppress = False
        self._on_change()

    def _on_ext_changed(self, _text: str) -> None:
        from PySide6.QtCore import QTimer
        if self._ext_timer is None:
            self._ext_timer = QTimer(self)
            self._ext_timer.setSingleShot(True)
            self._ext_timer.timeout.connect(self._on_change)
        self._ext_timer.start(300)

    def _on_change(self) -> None:
        if self._suppress:
            return
        self.filters_changed.emit(self.get_filters())

    # ── public API ────────────────────────────────────────────────────────────

    def get_filters(self) -> dict:
        hidden = {cat for cat, chk in self._cat_chks.items() if not chk.isChecked()}
        unit_idx  = self._size_unit.currentIndex()
        unit_mult = [1, 1024, 1024**2, 1024**3][unit_idx]
        min_bytes = int(self._min_spin.value() * unit_mult)
        max_bytes = int(self._max_spin.value() * unit_mult)
        exts_raw  = self._ext_edit.text().strip()
        exts = {e.strip().lstrip(".").lower() for e in exts_raw.split(",") if e.strip()} if exts_raw else set()
        result = {
            "hidden_categories": hidden,
            "min_bytes":         min_bytes,
            "max_bytes":         max_bytes,
            "extensions":        exts,
            "size_unit_idx":     unit_idx,
        }
        for key, chk in self._pf_chks.items():
            result[key] = chk.isChecked()
        return result

    def set_filters(self, filters: dict) -> None:
        """Update widgets from an external filters dict without emitting signals."""
        self._suppress = True
        hidden = set(filters.get("hidden_categories", ()))
        for cat, chk in self._cat_chks.items():
            chk.setChecked(cat not in hidden)
        unit_idx = filters.get("size_unit_idx", 2)
        self._size_unit.setCurrentIndex(unit_idx)
        unit_mult = [1, 1024, 1024**2, 1024**3][unit_idx] or 1
        self._min_spin.setValue(filters.get("min_bytes", 0) / unit_mult)
        self._max_spin.setValue(filters.get("max_bytes", 0) / unit_mult)
        exts = filters.get("extensions", set())
        self._ext_edit.setText(", ".join(sorted(exts)) if exts else "")
        for key, chk in self._pf_chks.items():
            chk.setChecked(filters.get(key, False))
        self._suppress = False

    def reset(self) -> None:
        self._suppress = True
        for chk in self._cat_chks.values():
            chk.setChecked(True)
        self._min_spin.setValue(0)
        self._max_spin.setValue(0)
        self._size_unit.setCurrentIndex(2)
        self._ext_edit.clear()
        for chk in self._pf_chks.values():
            chk.setChecked(False)
        self._suppress = False
        self._on_change()
