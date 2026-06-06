from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Optional

from PySide6.QtCore import Qt, QRect, QPoint, QSettings, QEvent
from PySide6.QtGui import QPainter, QColor, QPen, QKeyEvent, QPaintEvent, QResizeEvent, QRegion
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFrame, QSizePolicy,
)

from .constants import PANEL_BG, ACCENT, TEXT, SUBTEXT, BORDER, BTN_HOVER, BTN_PRESSED
from .theme import ORG_NAME, APP_NAME, Spacing


Placement = Literal["above", "below", "left", "right", "center"]


@dataclass(frozen=True)
class TourStep:
    target: Callable[[QWidget], Optional[QWidget]]
    title: str
    body: str
    placement: Placement = "below"


def _similar_tab_widget(w: QWidget) -> Optional[QWidget]:
    tabs = getattr(w, "center_tabs", None)
    if tabs is None:
        return None
    return tabs.tabBar()


def _view_mode_anchor(w: QWidget) -> Optional[QWidget]:
    grp = getattr(w, "_view_btn_grp", None)
    if grp is None:
        return None
    btns = grp.buttons()
    if not btns:
        return None
    return btns[0].parentWidget() or btns[0]


def _filter_anchor(w: QWidget) -> Optional[QWidget]:
    pill = getattr(w, "_filter_pill", None)
    if pill is not None and pill.isVisible():
        return pill
    return getattr(w, "_filterbar", None)


def _stop_anchor(w: QWidget) -> Optional[QWidget]:
    return getattr(w, "scan_btn", None)


def _tour_steps() -> list[TourStep]:
    return [
        TourStep(
            lambda w: getattr(w, "path_edit", None),
            "Start a scan",
            "Type, paste, or drag a folder here, then press Scan to add its files to the database.",
            "below",
        ),
        TourStep(
            lambda w: getattr(getattr(w, "folder_panel", None), "tree", None),
            "Browse what was scanned",
            "Folders show cumulative size and file counts. Click one to filter the file list.",
            "right",
        ),
        TourStep(
            _similar_tab_widget,
            "Find duplicate folders",
            "The Similar Folders tab compares scanned folders by content overlap.",
            "below",
        ),
        TourStep(
            _filter_anchor,
            "Live-filter without rescanning",
            "View filters narrow what you see without touching the database. Toggle them freely.",
            "below",
        ),
        TourStep(
            _view_mode_anchor,
            "Three ways to see files",
            "Switch between a detailed table, an icon grid, and a compact list. Scroll position is preserved.",
            "below",
        ),
        TourStep(
            lambda w: getattr(w, "_task_pill", None),
            "Background tasks live here",
            "Scans and analyses run in the background. Click the gear to see all tasks. Click the red ⏹ to cancel the running one.",
            "above",
        ),
        TourStep(
            _stop_anchor,
            "Stopping is always one click away",
            "Long actions show Stop in place of Start. Press Esc or Ctrl+. anytime to cancel a running task.",
            "left",
        ),
    ]


class _Card(QFrame):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("OnboardingCard")
        self.setStyleSheet(f"""
            QFrame#OnboardingCard {{
                background: {PANEL_BG};
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}
        """)
        v = QVBoxLayout(self)
        v.setContentsMargins(Spacing.LG, Spacing.PX14, Spacing.LG, Spacing.PX14)
        v.setSpacing(Spacing.SM)

        self.title_lbl = QLabel()
        self.title_lbl.setStyleSheet(f"color: {TEXT}; font-weight: bold; font-size: 14px;")
        self.title_lbl.setWordWrap(True)
        v.addWidget(self.title_lbl)

        self.body_lbl = QLabel()
        self.body_lbl.setWordWrap(True)
        self.body_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        v.addWidget(self.body_lbl)

        row = QHBoxLayout()
        row.setSpacing(Spacing.SM)
        self.progress_lbl = QLabel()
        self.progress_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        row.addWidget(self.progress_lbl)
        row.addStretch()

        self.back_btn = QPushButton("← Back")
        self.back_btn.setFlat(True)
        self.back_btn.setStyleSheet(
            f"QPushButton {{ color: {SUBTEXT}; border: none; padding: 4px 8px; background: transparent; }}"
            f"QPushButton:hover {{ color: {TEXT}; }}"
        )
        row.addWidget(self.back_btn)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setStyleSheet(
            f"QPushButton {{ color: {SUBTEXT}; background: transparent; border: 1px solid {BORDER};"
            f"border-radius: 6px; padding: 4px 12px; }}"
            f"QPushButton:hover {{ color: {TEXT}; border-color: {SUBTEXT}; }}"
        )
        row.addWidget(self.skip_btn)

        self.next_btn = QPushButton("Next →")
        self.next_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT}; color: white; border: none; border-radius: 6px;"
            f"padding: 4px 12px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {BTN_HOVER}; }}"
            f"QPushButton:pressed {{ background: {BTN_PRESSED}; }}"
        )
        row.addWidget(self.next_btn)
        v.addLayout(row)

        self.setFixedWidth(340)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)


class OnboardingOverlay(QWidget):
    SETTINGS_KEY = "onboarding/completed"
    BACKDROP_ALPHA = 160
    CUTOUT_PADDING = 8
    CUTOUT_RADIUS = 8
    CARD_GAP = 16

    def __init__(self, window: QWidget, steps: list[TourStep]) -> None:
        super().__init__(window)
        self._win = window
        self._steps = steps
        self._idx = 0

        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        self._card = _Card(self)
        self._card.skip_btn.clicked.connect(self._on_skip)
        self._card.next_btn.clicked.connect(self._on_next)
        self._card.back_btn.clicked.connect(self._on_back)

        self._fit_to_window()
        self._refresh_step()
        self.raise_()
        self.show()
        self.setFocus()
        self._win.installEventFilter(self)

    def _fit_to_window(self) -> None:
        self.setGeometry(self._win.rect())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reposition_card()
        self._update_passthrough_mask()
        self.update()

    def eventFilter(self, obj, event):
        if obj is self._win and event.type() == QEvent.Resize:
            self._fit_to_window()
            self._reposition_card()
            self._update_passthrough_mask()
            self.update()
        return super().eventFilter(obj, event)

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(0, 0, 0, self.BACKDROP_ALPHA))
        rect = self._target_rect_padded()
        if rect.isValid():
            p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
            p.setBrush(QColor(0, 0, 0, 255))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(rect, self.CUTOUT_RADIUS, self.CUTOUT_RADIUS)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawRoundedRect(rect, self.CUTOUT_RADIUS, self.CUTOUT_RADIUS)

    def _target_widget(self) -> Optional[QWidget]:
        try:
            return self._steps[self._idx].target(self._win)
        except Exception:
            return None

    def _update_passthrough_mask(self) -> None:
        rect = self._target_rect_padded()
        if rect.isValid() and not rect.isEmpty():
            self.setMask(QRegion(self.rect()).subtracted(QRegion(rect)))
        else:
            self.clearMask()

    def _target_rect_padded(self) -> QRect:
        w = self._target_widget()
        if w is None or not w.isVisible():
            return QRect()
        top_left = self.mapFromGlobal(w.mapToGlobal(QPoint(0, 0)))
        r = QRect(top_left, w.size())
        return r.adjusted(-self.CUTOUT_PADDING, -self.CUTOUT_PADDING,
                          self.CUTOUT_PADDING, self.CUTOUT_PADDING)

    def _refresh_step(self) -> None:
        step = self._steps[self._idx]
        self._card.title_lbl.setText(step.title)
        self._card.body_lbl.setText(step.body)
        self._card.progress_lbl.setText(f"Step {self._idx + 1} of {len(self._steps)}")
        is_last = (self._idx == len(self._steps) - 1)
        self._card.next_btn.setText("Done" if is_last else "Next →")
        self._card.back_btn.setVisible(self._idx > 0)
        self._card.adjustSize()
        self._reposition_card()
        self._update_passthrough_mask()
        self.update()

    def _reposition_card(self) -> None:
        rect = self._target_rect_padded()
        card_size = self._card.size()
        overlay = self.rect()
        placement: Placement = self._steps[self._idx].placement
        if not rect.isValid():
            placement = "center"

        if placement == "below":
            x = rect.center().x() - card_size.width() // 2
            y = rect.bottom() + self.CARD_GAP
        elif placement == "above":
            x = rect.center().x() - card_size.width() // 2
            y = rect.top() - card_size.height() - self.CARD_GAP
        elif placement == "left":
            x = rect.left() - card_size.width() - self.CARD_GAP
            y = rect.center().y() - card_size.height() // 2
        elif placement == "right":
            x = rect.right() + self.CARD_GAP
            y = rect.center().y() - card_size.height() // 2
        else:
            x = overlay.center().x() - card_size.width() // 2
            y = overlay.center().y() - card_size.height() // 2

        margin = self.CARD_GAP
        max_x = max(margin, overlay.width() - card_size.width() - margin)
        max_y = max(margin, overlay.height() - card_size.height() - margin)
        x = max(margin, min(max_x, x))
        y = max(margin, min(max_y, y))
        self._card.move(x, y)

    def _on_skip(self) -> None:
        self._finish()

    def _on_next(self) -> None:
        if self._idx == len(self._steps) - 1:
            self._finish()
        else:
            self._idx += 1
            self._refresh_step()

    def _on_back(self) -> None:
        if self._idx > 0:
            self._idx -= 1
            self._refresh_step()

    def _finish(self) -> None:
        QSettings(ORG_NAME, APP_NAME).setValue(self.SETTINGS_KEY, True)
        try:
            self._win.removeEventFilter(self)
        except Exception:
            pass
        self.close()
        self.deleteLater()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        k = event.key()
        if k == Qt.Key_Escape:
            self._on_skip()
        elif k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Right):
            self._on_next()
        elif k == Qt.Key_Left:
            self._on_back()
        else:
            super().keyPressEvent(event)


def run_tour(window: QWidget, force: bool = False) -> None:
    if not force:
        completed = QSettings(ORG_NAME, APP_NAME).value(
            OnboardingOverlay.SETTINGS_KEY, False, type=bool
        )
        if completed:
            return
    OnboardingOverlay(window, _tour_steps())
