from __future__ import annotations
from datetime import datetime

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit

from ..constants import PANEL_BG, BORDER, SUBTEXT, TEXT, GREEN, YELLOW, RED
from ..fonts import mono_font_family
from .. import icons as _icons


class _StderrBridge:
    """Tees stderr writes to the ConsolePanel while keeping the original stream."""

    def __init__(self, console: "ConsolePanel", original):
        self._console  = console
        self._original = original
        self._buf      = ""

    def write(self, text: str) -> None:
        self._original.write(text)
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._console.log(line, "error")

    def flush(self) -> None:
        self._original.flush()
        if self._buf.strip():
            self._console.log(self._buf, "error")
            self._buf = ""

    def __getattr__(self, name):
        return getattr(self._original, name)


class ConsolePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        from ..theme import Theme
        Theme.instance().on_changed(self._apply_stylesheet)

    def _apply_stylesheet(self) -> None:
        self._hdr.setStyleSheet(f"background:{PANEL_BG};border-top:1px solid {BORDER};")
        self._title.setStyleSheet(f"color:{SUBTEXT};font-size:11px;font-weight:bold;")
        self._clear_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{SUBTEXT};border:1px solid {BORDER};"
            f"border-radius:3px;font-size:10px;}}"
            f"QPushButton:hover{{color:{TEXT};border-color:{TEXT};}}"
        )
        self._output.setStyleSheet(f"""
            QTextEdit {{
                background: {PANEL_BG};
                color: {TEXT}; border: none;
                font-family: '{mono_font_family()}', 'SF Mono', 'Menlo', monospace;
                font-size: 11px; padding: 4px 8px;
            }}
        """)

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._hdr = QWidget()
        self._hdr.setFixedHeight(28)
        self._hdr.setStyleSheet(f"background:{PANEL_BG};border-top:1px solid {BORDER};")
        hl = QHBoxLayout(self._hdr)
        hl.setContentsMargins(12, 0, 8, 0)
        hl.setSpacing(6)
        icon = QLabel()
        icon.setPixmap(_icons.pixmap("console", 14, color=str(SUBTEXT)))
        hl.addWidget(icon)
        self._title = QLabel("Console")
        self._title.setStyleSheet(f"color:{SUBTEXT};font-size:11px;font-weight:bold;")
        hl.addWidget(self._title)
        hl.addStretch()
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedSize(48, 18)
        self._clear_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{SUBTEXT};border:1px solid {BORDER};"
            f"border-radius:3px;font-size:10px;}}"
            f"QPushButton:hover{{color:{TEXT};border-color:{TEXT};}}"
        )
        self._clear_btn.setAccessibleName("Clear console")
        self._clear_btn.setAccessibleDescription("Erase the diagnostic output shown below")
        self._clear_btn.clicked.connect(lambda: self._output.clear())
        hl.addWidget(self._clear_btn)
        lay.addWidget(self._hdr)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setAccessibleName("Console")
        self._output.setAccessibleDescription("Read-only diagnostic output from scans and analysis")
        self._output.setStyleSheet(f"""
            QTextEdit {{
                background: {PANEL_BG};
                color: {TEXT}; border: none;
                font-family: '{mono_font_family()}', 'SF Mono', 'Menlo', monospace;
                font-size: 11px; padding: 4px 8px;
            }}
        """)
        lay.addWidget(self._output)

    def log(self, msg: str, level: str = "info") -> None:
        t      = datetime.now().strftime("%H:%M:%S")
        colors = {"info": TEXT, "success": GREEN, "warning": YELLOW, "error": RED}
        color  = colors.get(level, TEXT)
        safe   = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._output.append(
            f'<span style="color:{SUBTEXT};">[{t}]</span> '
            f'<span style="color:{color};">{safe}</span>'
        )
        sb = self._output.verticalScrollBar()
        sb.setValue(sb.maximum())
