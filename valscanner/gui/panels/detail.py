from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import text

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QPushButton,
    QTextEdit, QHBoxLayout, QMessageBox, QStackedWidget,
)

from ..layouts import FlowLayout

from ...core.db import repo_for
from ..constants import CATEGORY_COLORS, PANEL_BG, ACCENT, TEXT, SUBTEXT, BORDER, GREEN, BTN_HOVER, BTN_PRESSED
from .. import icons as _icons


class TagChip(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            QLabel {{
                background: {PANEL_BG};
                color: {ACCENT};
                border: 1px solid {ACCENT};
                border-radius: 8px;
                padding: 2px 8px;
                font-size: 11px;
            }}
        """)


class DetailPanel(QWidget):
    status_message = Signal(str, str)  # (msg, level)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)
        self._db_path = ""
        self._current_path: str | None = None
        self._build_ui()
        from ..theme import Theme
        Theme.instance().on_changed(self._apply_stylesheet)

    def _apply_stylesheet(self) -> None:
        self.name_label.setStyleSheet(f"color: {TEXT}; font-weight: bold; font-size: 13px;")
        self.cat_label.setStyleSheet(
            f"color: {ACCENT}; font-size: 11px; border: 1px solid {ACCENT};"
            f"border-radius:8px; padding:2px 8px;"
        )
        self.tags_title.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px; font-weight: bold;")
        self.meta_title.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px; font-weight: bold;")
        self._exif_toggle.setStyleSheet(
            f"QPushButton{{color:{SUBTEXT};font-size:11px;font-weight:bold;"
            f"text-align:left;padding:2px 0;border:none;background:transparent;}}"
            f"QPushButton:hover{{color:{TEXT};}}"
        )
        self.meta_text.setStyleSheet(f"""
            QTextEdit {{
                background: {PANEL_BG}; color: {SUBTEXT};
                border: 1px solid {BORDER}; border-radius: 6px;
                font-size: 11px; font-family: monospace; padding: 4px;
            }}
        """)
        self.open_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; color: white; border: none;
                border-radius: 6px; padding: 6px 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {BTN_HOVER}; }}
            QPushButton:pressed {{ background: {BTN_PRESSED}; }}
        """)
        self.sample_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {GREEN};
                border: 1px solid {GREEN}66; border-radius: 6px;
                padding: 6px 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {GREEN}22; border-color: {GREEN}; }}
            QPushButton:pressed {{ background: {GREEN}33; }}
        """)

    def set_db(self, db_path: str) -> None:
        self._db_path = db_path

    def _build_placeholder(self) -> QWidget:
        w   = QWidget()
        pl  = QVBoxLayout(w)
        pl.setAlignment(Qt.AlignCenter)
        pl.setSpacing(10)
        ico = QLabel()
        ico.setPixmap(_icons.pixmap("file", 48, color=str(SUBTEXT)))
        ico.setAlignment(Qt.AlignCenter)
        pl.addWidget(ico, 0, Qt.AlignHCenter)
        title = QLabel("Select a file")
        title.setStyleSheet(f"color: {SUBTEXT}; font-weight: bold; font-size: 13px;")
        title.setAlignment(Qt.AlignCenter)
        pl.addWidget(title)
        hint = QLabel("Metadata, tags, and previews will appear here.")
        hint.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        pl.addWidget(hint)
        return w

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_placeholder())   # page 0: placeholder

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setMinimumHeight(72)
        self.icon_label.setPixmap(_icons.pixmap("file", 64, color=str(SUBTEXT)))
        lay.addWidget(self.icon_label)

        self.name_label = QLabel("Select a file")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet(f"color: {TEXT}; font-weight: bold; font-size: 13px;")
        lay.addWidget(self.name_label)

        self.cat_label = QLabel()
        self.cat_label.setAlignment(Qt.AlignCenter)
        self.cat_label.setStyleSheet(
            f"color: {ACCENT}; font-size: 11px; border: 1px solid {ACCENT};"
            f"border-radius:8px; padding:2px 8px;"
        )
        lay.addWidget(self.cat_label)

        self.grid = QWidget()
        self.grid_lay = QGridLayout(self.grid)
        self.grid_lay.setContentsMargins(0, 0, 0, 0)
        self.grid_lay.setSpacing(4)
        lay.addWidget(self.grid)

        self.tags_title = QLabel("Tags")
        self.tags_title.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px; font-weight: bold;")
        lay.addWidget(self.tags_title)

        self.tags_container = QWidget()
        self.tags_layout    = FlowLayout(self.tags_container)
        lay.addWidget(self.tags_container)

        self.meta_title = QLabel("Metadata")
        self.meta_title.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px; font-weight: bold;")
        lay.addWidget(self.meta_title)

        self.meta_text = QTextEdit()
        self.meta_text.setReadOnly(True)
        self.meta_text.setMaximumHeight(160)
        self.meta_text.setStyleSheet(f"""
            QTextEdit {{
                background: {PANEL_BG}; color: {SUBTEXT};
                border: 1px solid {BORDER}; border-radius: 6px;
                font-size: 11px; font-family: monospace; padding: 4px;
            }}
        """)
        lay.addWidget(self.meta_text)

        # Collapsible EXIF section
        self._exif_section = QWidget()
        exif_outer = QVBoxLayout(self._exif_section)
        exif_outer.setContentsMargins(0, 4, 0, 0)
        exif_outer.setSpacing(2)

        self._exif_toggle = QPushButton("▼  EXIF")
        self._exif_toggle.setCheckable(True)
        self._exif_toggle.setChecked(True)
        self._exif_toggle.setFlat(True)
        self._exif_toggle.setStyleSheet(
            f"QPushButton{{color:{SUBTEXT};font-size:11px;font-weight:bold;"
            f"text-align:left;padding:2px 0;border:none;background:transparent;}}"
            f"QPushButton:hover{{color:{TEXT};}}"
        )
        self._exif_toggle.clicked.connect(self._on_exif_toggle)
        exif_outer.addWidget(self._exif_toggle)

        self._exif_content = QWidget()
        self._exif_grid_lay = QGridLayout(self._exif_content)
        self._exif_grid_lay.setContentsMargins(0, 0, 0, 0)
        self._exif_grid_lay.setSpacing(4)
        exif_outer.addWidget(self._exif_content)

        self._exif_section.hide()
        lay.addWidget(self._exif_section)

        self.open_btn = QPushButton("Open File")
        self.open_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; color: white; border: none;
                border-radius: 6px; padding: 6px 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {BTN_HOVER}; }}
            QPushButton:pressed {{ background: {BTN_PRESSED}; }}
        """)
        self.open_btn.clicked.connect(self._open_file)
        self.open_btn.hide()
        lay.addWidget(self.open_btn)

        self.sample_btn = QPushButton("Play Sample")
        self.sample_btn.setIcon(_icons.icon("play", color=str(GREEN)))
        self.sample_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {GREEN};
                border: 1px solid {GREEN}66; border-radius: 6px;
                padding: 6px 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {GREEN}22; border-color: {GREEN}; }}
            QPushButton:pressed {{ background: {GREEN}33; }}
        """)
        self.sample_btn.clicked.connect(self._play_sample)
        self.sample_btn.hide()
        lay.addWidget(self.sample_btn)

        lay.addStretch()

        self._stack.addWidget(content)      # page 1: live detail
        self._stack.setCurrentIndex(0)      # start on placeholder
        outer.addWidget(self._stack)

    def _grid_row(self, label: str, value, row: int) -> None:
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        val = QLabel(str(value))
        val.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        val.setWordWrap(True)
        self.grid_lay.addWidget(lbl, row, 0)
        self.grid_lay.addWidget(val, row, 1)

    def _on_exif_toggle(self) -> None:
        expanded = self._exif_toggle.isChecked()
        self._exif_content.setVisible(expanded)
        self._exif_toggle.setText("▼  EXIF" if expanded else "▶  EXIF")

    def _exif_fields(self, meta: dict, cat: str) -> list:
        if cat not in ("photo", "image") or not meta:
            return []
        fields = []
        make  = meta.get("exif_camera_make", "")
        model = meta.get("exif_camera_model", "")
        if make or model:
            fields.append(("Camera", " ".join(filter(None, [make, model]))))
        for key, label in [
            ("exif_lens",         "Lens"),
            ("exif_exposure",     "Exposure"),
            ("exif_iso",          "ISO"),
            ("exif_focal_length", "Focal Length"),
            ("exif_datetime",     "Captured"),
        ]:
            val = meta.get(key)
            if val:
                fields.append((label, str(val)))
        if meta.get("has_gps"):
            lat = meta.get("gps_lat", "")
            lon = meta.get("gps_lon", "")
            fields.append(("GPS", f"{lat}, {lon}" if (lat and lon) else "Yes"))
        w = meta.get("img_width")
        h = meta.get("img_height")
        if w and h:
            fields.append(("Dimensions", f"{w} × {h}"))
        return fields

    def show_file(self, row) -> None:
        self._stack.setCurrentIndex(1)
        self._current_path = row[0]
        cat = row[2]

        thumb_loaded = False
        if self._db_path and cat in ("photo", "image", "video"):
            try:
                engine = repo_for(self._db_path).engine
                with engine.connect() as conn:
                    res = conn.execute(
                        text("SELECT t.data FROM thumbnails t"
                             " JOIN files f ON f.id = t.file_id WHERE f.path=:p"),
                        {"p": row[0]},
                    ).fetchone()
                if res:
                    data = bytes(res[0])
                    px = QPixmap()
                    if px.loadFromData(data):
                        self.icon_label.setPixmap(
                            px.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        )
                        thumb_loaded = True
            except Exception:
                pass
        if not thumb_loaded:
            cat_color = CATEGORY_COLORS.get(cat, str(SUBTEXT))
            self.icon_label.setPixmap(_icons.pixmap(f"cat-{cat}", 64, color=cat_color))

        self.name_label.setText(row[1])
        color = CATEGORY_COLORS.get(cat, str(SUBTEXT))
        self.cat_label.setText(cat)
        self.cat_label.setStyleSheet(
            f"color: {color}; font-size: 11px; border: 1px solid {color};"
            f"border-radius:8px; padding:2px 8px;"
        )

        for i in reversed(range(self.grid_lay.count())):
            self.grid_lay.itemAt(i).widget().deleteLater()

        self._grid_row("Size",     row[4], 0)
        self._grid_row("Modified", row[5], 1)
        sha = row[7] if len(row) > 7 else ""
        if sha:
            sha_lbl = QLabel(sha)
            sha_lbl.setWordWrap(True)
            sha_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 9px; font-family: monospace;")
            self.grid_lay.addWidget(QLabel("SHA-256"), 2, 0)
            self.grid_lay.addWidget(sha_lbl, 2, 1)
        path_row = 3 if sha else 2
        path_lbl = QLabel(row[0])
        path_lbl.setWordWrap(True)
        path_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 10px;")
        self.grid_lay.addWidget(QLabel("Path"), path_row, 0)
        self.grid_lay.addWidget(path_lbl, path_row, 1)

        for i in reversed(range(self.tags_layout.count())):
            w = self.tags_layout.itemAt(i).widget()
            if w:
                w.deleteLater()
        for tag in (row[6] or "").split(", "):
            tag = tag.strip()
            if tag:
                self.tags_layout.addWidget(TagChip(tag))

        meta: dict = {}
        extra = row[8] if len(row) > 8 else (row[7] if len(row) > 7 else "")
        if extra:
            try:
                meta = json.loads(extra)
            except Exception:
                pass
        self.meta_text.setPlainText(
            "\n".join(f"{k}: {v}" for k, v in meta.items()) if meta else "(no extra metadata)"
        )

        exif = self._exif_fields(meta, cat)
        for i in reversed(range(self._exif_grid_lay.count())):
            w = self._exif_grid_lay.itemAt(i).widget()
            if w:
                w.deleteLater()
        if exif:
            for i, (label, value) in enumerate(exif):
                lbl = QLabel(label)
                lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
                val = QLabel(str(value))
                val.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
                val.setWordWrap(True)
                self._exif_grid_lay.addWidget(lbl, i, 0)
                self._exif_grid_lay.addWidget(val, i, 1)
            self._exif_section.show()
            self._exif_content.setVisible(self._exif_toggle.isChecked())
        else:
            self._exif_section.hide()

        self.open_btn.show()

        self.sample_btn.hide()
        if self._db_path and cat in ("audio", "video"):
            try:
                engine = repo_for(self._db_path).engine
                with engine.connect() as conn:
                    has = conn.execute(
                        text("SELECT 1 FROM media_samples ms"
                             " JOIN files f ON f.id = ms.file_id WHERE f.path=:p"),
                        {"p": row[0]},
                    ).fetchone()
                if has:
                    self.sample_btn.show()
            except Exception:
                pass

    def _play_sample(self) -> None:
        if not self._current_path or not self._db_path:
            return
        try:
            engine = repo_for(self._db_path).engine
            with engine.connect() as conn:
                res = conn.execute(
                    text("SELECT ms.data, ms.format FROM media_samples ms"
                         " JOIN files f ON f.id = ms.file_id WHERE f.path=:p"),
                    {"p": self._current_path},
                ).fetchone()
            if not res:
                from ..feedback import notify_error
                notify_error(self, "Sample unavailable",
                    "No sample is stored for this file. "
                    "Re-scan with 'Store samples' enabled to generate one.")
                return
            data, fmt = res
            suffix = f".{fmt or 'mp3'}"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            name = Path(self._current_path).name
            self.status_message.emit(f"Opening sample for {name}…", "info")
            try:
                if sys.platform == "darwin":
                    subprocess.Popen(["open", tmp_path])
                elif sys.platform == "win32":
                    os.startfile(tmp_path)
                else:
                    subprocess.Popen(["xdg-open", tmp_path])
            except OSError as exc:
                from ..feedback import notify_error
                notify_error(self, "Could not open sample",
                    "The system reported an error when opening this media file.",
                    detail=str(exc))
        except Exception as e:
            from ..feedback import notify_error
            notify_error(self, "Could not open sample",
                "An unexpected error occurred when reading the sample.",
                detail=str(e))

    def _open_file(self) -> None:
        if not self._current_path:
            return
        p = Path(self._current_path)
        if not p.exists():
            from ..feedback import notify_error
            notify_error(self, "File no longer exists",
                f"'{p.name}' was indexed previously but is missing now. "
                "Re-scan to refresh.",
                detail=str(p))
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        elif sys.platform == "win32":
            os.startfile(str(p))
        else:
            subprocess.Popen(["xdg-open", str(p)])
