from __future__ import annotations
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QPushButton,
    QTextEdit, QHBoxLayout, QMessageBox,
)

from ..constants import CATEGORY_COLORS, PANEL_BG, ACCENT, TEXT, SUBTEXT, BORDER, GREEN


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


class FlowLayout(QHBoxLayout):
    """Minimal flow-style layout using wrapping QHBoxLayout trick."""
    pass


class DetailPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)
        self._db_path = ""
        self._current_path: str | None = None
        self._build_ui()

    def set_db(self, db_path: str) -> None:
        self._db_path = db_path

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        self.icon_label = QLabel("📄")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("font-size: 48px;")
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

        self.open_btn = QPushButton("Open File")
        self.open_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; color: white; border: none;
                border-radius: 6px; padding: 6px 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background: #9d8fff; }}
            QPushButton:pressed {{ background: #6a58d4; }}
        """)
        self.open_btn.clicked.connect(self._open_file)
        self.open_btn.hide()
        lay.addWidget(self.open_btn)

        self.sample_btn = QPushButton("▶  Play Sample")
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

    def _grid_row(self, label: str, value, row: int) -> None:
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        val = QLabel(str(value))
        val.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        val.setWordWrap(True)
        self.grid_lay.addWidget(lbl, row, 0)
        self.grid_lay.addWidget(val, row, 1)

    def show_file(self, row) -> None:
        self._current_path = row[0]
        cat = row[2]

        icons = {
            "photo": "🖼️", "video": "🎬", "audio": "🎵",
            "document": "📄", "spreadsheet": "📊", "presentation": "📑",
            "code": "💻", "data": "🗃️", "archive": "📦",
            "executable": "⚙️", "font": "🔤", "ebook": "📚",
        }

        thumb_loaded = False
        if self._db_path and cat in ("photo", "image", "video"):
            try:
                conn = sqlite3.connect(self._db_path)
                res  = conn.execute(
                    "SELECT t.data FROM thumbnails t JOIN files f ON f.id = t.file_id WHERE f.path=?",
                    (row[0],),
                ).fetchone()
                conn.close()
                if res:
                    px = QPixmap()
                    px.loadFromData(res[0])
                    self.icon_label.setPixmap(
                        px.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    )
                    self.icon_label.setStyleSheet("font-size: 0px;")
                    thumb_loaded = True
            except Exception:
                pass
        if not thumb_loaded:
            self.icon_label.clear()
            self.icon_label.setText(icons.get(cat, "📄"))
            self.icon_label.setStyleSheet("font-size: 48px;")

        self.name_label.setText(row[1])
        color = CATEGORY_COLORS.get(cat, "#9E9E9E")
        self.cat_label.setText(cat)
        self.cat_label.setStyleSheet(
            f"color: {color}; font-size: 11px; border: 1px solid {color};"
            f"border-radius:8px; padding:2px 8px;"
        )

        for i in reversed(range(self.grid_lay.count())):
            self.grid_lay.itemAt(i).widget().deleteLater()

        self._grid_row("Size",     row[4], 0)
        self._grid_row("Modified", row[5], 1)
        path_lbl = QLabel(row[0])
        path_lbl.setWordWrap(True)
        path_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 10px;")
        self.grid_lay.addWidget(QLabel("Path"), 2, 0)
        self.grid_lay.addWidget(path_lbl, 2, 1)

        for i in reversed(range(self.tags_layout.count())):
            w = self.tags_layout.itemAt(i).widget()
            if w:
                w.deleteLater()
        for tag in (row[6] or "").split(", "):
            tag = tag.strip()
            if tag:
                self.tags_layout.addWidget(TagChip(tag))

        meta: dict = {}
        if row[7]:
            try:
                meta = json.loads(row[7])
            except Exception:
                pass
        self.meta_text.setPlainText(
            "\n".join(f"{k}: {v}" for k, v in meta.items()) if meta else "(no extra metadata)"
        )

        self.open_btn.show()

        self.sample_btn.hide()
        if self._db_path and cat in ("audio", "video"):
            try:
                conn = sqlite3.connect(self._db_path)
                has  = conn.execute(
                    "SELECT 1 FROM media_samples ms JOIN files f ON f.id = ms.file_id WHERE f.path=?",
                    (row[0],),
                ).fetchone()
                conn.close()
                if has:
                    self.sample_btn.show()
            except Exception:
                pass

    def _play_sample(self) -> None:
        if not self._current_path or not self._db_path:
            return
        try:
            conn = sqlite3.connect(self._db_path)
            res  = conn.execute(
                "SELECT ms.data, ms.format FROM media_samples ms"
                " JOIN files f ON f.id = ms.file_id WHERE f.path=?",
                (self._current_path,),
            ).fetchone()
            conn.close()
            if not res:
                return
            data, fmt = res
            suffix = f".{fmt or 'mp3'}"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            if sys.platform == "darwin":
                subprocess.Popen(["open", tmp_path])
            elif sys.platform == "win32":
                os.startfile(tmp_path)
            else:
                subprocess.Popen(["xdg-open", tmp_path])
        except Exception as e:
            QMessageBox.warning(self, "Sample error", str(e))

    def _open_file(self) -> None:
        if not self._current_path:
            return
        p = Path(self._current_path)
        if not p.exists():
            QMessageBox.warning(self, "Not found", f"File not found:\n{self._current_path}")
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        elif sys.platform == "win32":
            os.startfile(str(p))
        else:
            subprocess.Popen(["xdg-open", str(p)])
