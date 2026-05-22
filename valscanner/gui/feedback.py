"""Centralised UI feedback helpers.

Provides a level taxonomy, color/icon mapping, standardised error modals,
and destructive-action confirmation dialogs used across all GUI panels.
"""

from __future__ import annotations

from enum import Enum


class Level(str, Enum):
    INFO    = "info"     # default; muted text; auto-dismiss 5 s
    SUCCESS = "success"  # green; auto-dismiss 3 s
    WARNING = "warning"  # yellow; auto-dismiss 8 s
    ERROR   = "error"    # red; sticky
    BUSY    = "busy"     # neutral; sticky until replaced


TIMEOUTS = {
    "info":    5000,
    "success": 3000,
    "warning": 8000,
    "error":   0,    # sticky
    "busy":    0,    # sticky
}


def color_for(level: str) -> str:
    from .constants import GREEN, RED, YELLOW, SUBTEXT, TEXT

    return {
        "info":    str(SUBTEXT),
        "success": str(GREEN),
        "warning": str(YELLOW),
        "error":   str(RED),
        "busy":    str(TEXT),
    }.get(level, str(SUBTEXT))


def icon_for(level: str) -> str:
    return {
        "info":    "info",
        "success": "check",
        "warning": "alert",
        "error":   "error",
        "busy":    "spinner",
    }.get(level, "info")


def notify_error(
    parent,
    title: str,
    body: str,
    detail: str | None = None,
) -> None:
    """Standardised error modal.

    `title` is a specific noun phrase (not "Error").
    `body` is one user-facing sentence describing what happened and next steps.
    `detail` is technical content (stack trace, raw error) shown via "Show Details".
    """
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(body)
    box.setIcon(QMessageBox.Critical)
    if detail:
        box.setDetailedText(detail)
    box.setStandardButtons(QMessageBox.Ok)
    box.exec()


def confirm_destructive(
    parent,
    title: str,
    body: str,
    confirm_label: str = "Delete",
) -> bool:
    """Standardised destructive-action confirmation.

    Returns True if the user confirmed, False if they cancelled.
    """
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(body)
    box.setIcon(QMessageBox.Warning)
    yes_btn = box.addButton(confirm_label, QMessageBox.DestructiveRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is yes_btn


_TOAST_ATTR = "_active_undo_toast"


class UndoToast:
    """Small banner pinned to the bottom of `parent` with an Undo button.

    Auto-dismisses after `timeout_ms`. If a new toast is shown while one is
    active, the old toast is dismissed (its pending action commits immediately).
    The 'Undo' button calls `undo_cb` and cancels the pending commit.

    Note: 'Undo' for scan deletes is not a true restore — it cancels the
    deferred delete before it commits. If the toast has already expired,
    the data is gone and no restore is performed.
    """

    def __init__(self, parent, msg: str, undo_cb, timeout_ms: int = 8000):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
        from .constants import DARK_BG, ACCENT

        self._undo_cb    = undo_cb
        self._committed  = False
        self._dismissed  = False

        self._frame = QFrame(parent)
        self._frame.setObjectName("undo_toast")
        self._frame.setStyleSheet(
            f"QFrame#undo_toast {{"
            f"  background:{ACCENT};"
            f"  border-radius:20px;"
            f"}}"
        )
        self._frame.setFixedHeight(40)

        lay = QHBoxLayout(self._frame)
        lay.setContentsMargins(16, 0, 10, 0)
        lay.setSpacing(8)

        lbl = QLabel(msg)
        lbl.setStyleSheet(f"color:{DARK_BG}; font-size:12px; font-weight:600; border:none; background:transparent;")
        lay.addWidget(lbl, 1)

        undo_btn = QPushButton("Undo")
        undo_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{DARK_BG};border:none;"
            f"font-size:12px;font-weight:bold;padding:0 6px;}}"
            f"QPushButton:hover{{text-decoration:underline;}}"
        )
        undo_btn.clicked.connect(self._on_undo)
        lay.addWidget(undo_btn)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{DARK_BG};border:none;font-size:14px;}}"
            f"QPushButton:hover{{opacity:0.7;}}"
        )
        close_btn.clicked.connect(self._commit_and_dismiss)
        lay.addWidget(close_btn)

        self._reposition(parent)
        self._frame.show()
        self._frame.raise_()

        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._commit_and_dismiss)
        self._timer.start(timeout_ms)

    def _reposition(self, parent) -> None:
        pw, ph = parent.width(), parent.height()
        w = min(400, pw - 40)
        self._frame.setFixedWidth(w)
        self._frame.move((pw - w) // 2, ph - 40 - 24)

    def _on_undo(self) -> None:
        if self._dismissed:
            return
        self._timer.stop()
        self._dismissed = True
        if self._undo_cb:
            self._undo_cb()
        self._frame.hide()
        self._frame.deleteLater()

    def _commit_and_dismiss(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self._committed = True
        self._timer.stop()
        self._frame.hide()
        self._frame.deleteLater()

    def dismiss_immediately(self) -> None:
        """Dismiss without undo (used when a new toast replaces this one)."""
        self._commit_and_dismiss()


def undo_toast(
    parent,
    msg: str,
    undo_cb,
    timeout_ms: int = 8000,
) -> "UndoToast":
    """Show a toast on `parent`. Replaces any existing toast (singleton)."""
    existing = getattr(parent, _TOAST_ATTR, None)
    if existing is not None:
        existing.dismiss_immediately()
    toast = UndoToast(parent, msg, undo_cb, timeout_ms)
    setattr(parent, _TOAST_ATTR, toast)
    return toast
