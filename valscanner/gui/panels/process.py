"""
ProcessPanel: dockable process monitor with freeze detection and graceful fallbacks.

Components:
- ProcessRegistry: singleton, zero Qt deps, tracks all background workers
- ProcessPanel(QDockWidget): floating panel with process cards
- _ProcessCard: per-process UI with progress, status, cancel/kill buttons, lazy log
- _Notifier: Qt signal bridge for cross-thread updates from workers
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal, Slot, QObject, QMetaObject, QModelIndex
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QPlainTextEdit,
    QScrollArea, QFrame, QCheckBox,
)

from ..constants import DARK_BG, PANEL_BG, ACCENT, TEXT, SUBTEXT, BORDER, GREEN, RED, YELLOW
from .. import icons as _icons

# Module-level constants
FREEZE_THRESHOLD_SECS = 30
WATCHDOG_INTERVAL_MS = 2_000
LOG_RING_BUFFER_SIZE = 500


class ProcessState(Enum):
    """State of a registered worker process."""
    RUNNING = auto()
    FROZEN = auto()
    DONE = auto()
    ERROR = auto()


@dataclass
class ProcessEntry:
    """Registry entry for a background worker (no Qt deps)."""
    pid: str  # UUID string, stable unique id
    name: str
    start_time: float  # time.monotonic()
    last_heartbeat: float
    state: ProcessState = ProcessState.RUNNING
    progress: int = -1  # 0-100, -1 = indeterminate
    processed: int = 0  # items processed so far
    total: int = 0      # total expected items (0 = unknown)
    cancel_cb: Optional[Callable[[], None]] = None
    kill_cb: Optional[Callable[[], None]] = None
    log: deque = field(default_factory=lambda: deque(maxlen=LOG_RING_BUFFER_SIZE))


class ProcessRegistry:
    """Singleton registry for all background workers (threads, processes, etc.)

    Zero Qt dependencies — safe to import from core or tests.
    Worker threads call heartbeat(), push_log(), set_progress(), mark_done(), mark_error().
    Qt slots connect to the singleton's _notifier.changed signal.
    """

    _instance: Optional[ProcessRegistry] = None

    @classmethod
    def instance(cls) -> ProcessRegistry:
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._entries: dict[str, ProcessEntry] = {}
        self._notifier: _Notifier | None = None  # lazily created on first use

    def register(
        self,
        name: str,
        cancel_cb: Optional[Callable[[], None]] = None,
        kill_cb: Optional[Callable[[], None]] = None,
    ) -> str:
        """Register a new worker. Returns a stable pid string."""
        pid = str(uuid.uuid4())
        now = time.monotonic()
        self._entries[pid] = ProcessEntry(
            pid=pid,
            name=name,
            start_time=now,
            last_heartbeat=now,
            cancel_cb=cancel_cb,
            kill_cb=kill_cb,
        )
        self._notify()
        return pid

    def unregister(self, pid: str) -> None:
        """Remove a worker from the registry."""
        if pid in self._entries:
            del self._entries[pid]
            self._notify()

    # --- Worker API (called from worker threads) ---

    def heartbeat(self, pid: str) -> None:
        """Worker calls this periodically. Updates last_heartbeat (thread-safe)."""
        if pid in self._entries:
            self._entries[pid].last_heartbeat = time.monotonic()

    def set_progress(self, pid: str, value: int) -> None:
        """Set progress to 0-100; -1 for indeterminate."""
        if pid in self._entries:
            self._entries[pid].progress = value
            self._notify()

    def set_progress_detailed(self, pid: str, processed: int, total: int) -> None:
        """Set detailed progress with processed/total counts. Computes percentage."""
        if pid in self._entries:
            e = self._entries[pid]
            e.processed = processed
            e.total = total
            if total > 0:
                e.progress = min(int(processed / total * 100), 100)
            else:
                e.progress = -1
            e.last_heartbeat = time.monotonic()
            self._notify()

    def push_log(self, pid: str, msg: str) -> None:
        """Append to ring buffer (GIL-protected, thread-safe)."""
        if pid in self._entries:
            self._entries[pid].log.append(msg)

    def mark_done(self, pid: str) -> None:
        """Mark process as completed."""
        if pid in self._entries:
            self._entries[pid].state = ProcessState.DONE
            self._notify()

    def mark_error(self, pid: str, msg: str = "") -> None:
        """Mark process as errored."""
        if pid in self._entries:
            self._entries[pid].state = ProcessState.ERROR
            if msg:
                self._entries[pid].log.append(f"[ERROR] {msg}")
            self._notify()

    # --- Panel API ---

    def entries(self) -> list[ProcessEntry]:
        """Get all registered entries."""
        return list(self._entries.values())

    def get(self, pid: str) -> Optional[ProcessEntry]:
        """Get a specific entry by pid."""
        return self._entries.get(pid)

    def add_listener(self, cb: Callable[[], None]) -> None:
        """Register a listener (typically a ProcessPanel._refresh slot)."""
        if self._notifier is None:
            self._notifier = _Notifier()
        self._notifier.changed.connect(cb)

    def _notify(self) -> None:
        """Signal listeners (on main thread via _Notifier)."""
        if self._notifier is None:
            self._notifier = _Notifier()
        self._notifier.notify_queued()


class _Notifier(QObject):
    """Qt signal bridge: worker threads call notify_queued(), main thread gets changed signal."""
    changed = Signal()

    def notify_queued(self) -> None:
        """Post changed signal to the event loop (safe from any thread)."""
        QMetaObject.invokeMethod(self, "_emit_changed", Qt.QueuedConnection)

    @Slot()
    def _emit_changed(self) -> None:
        """Emitted on the main thread."""
        self.changed.emit()


class ProcessPanel(QDockWidget):
    """Dockable process monitor showing status of all registered workers."""

    def __init__(self, parent=None):
        super().__init__("Processes", parent)
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.setFloating(False)  # Start docked, not floating
        self._cards: dict[str, _ProcessCard] = {}
        self._auto_clear = True
        self._auto_clear_delay_ms = 2_000
        self._build_ui()
        self._setup_watchdog()
        ProcessRegistry.instance().add_listener(self._refresh)

    def _build_ui(self) -> None:
        """Build the dock widget layout."""
        container = QWidget()
        container.setStyleSheet(f"background: {DARK_BG};")
        self.setWidget(container)

        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header bar
        hdr = QWidget()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 8, 0)
        hl.setSpacing(6)

        title_icon = QLabel()
        title_icon.setPixmap(_icons.pixmap("settings", 14, color=str(TEXT)))
        hl.addWidget(title_icon)
        title = QLabel("Processes")
        title.setStyleSheet(f"color: {TEXT}; font-weight: bold; font-size: 12px;")
        hl.addWidget(title)
        hl.addStretch()

        self._auto_clear_chk = QCheckBox("Auto-clear")
        self._auto_clear_chk.setChecked(self._auto_clear)
        self._auto_clear_chk.setToolTip(
            "Automatically remove processes when they complete (after a short delay)"
        )
        self._auto_clear_chk.setStyleSheet(
            f"QCheckBox {{color: {SUBTEXT}; font-size: 10px; spacing: 4px;}}"
            f"QCheckBox::indicator {{width: 12px; height: 12px;}}"
        )
        self._auto_clear_chk.toggled.connect(self._on_auto_clear_toggled)
        hl.addWidget(self._auto_clear_chk)

        clear_btn = QPushButton("Clear done")
        clear_btn.setFixedHeight(22)
        clear_btn.setStyleSheet(
            f"QPushButton {{background: {PANEL_BG}; color: {TEXT}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 2px 8px; font-size: 10px;}}"
        )
        clear_btn.clicked.connect(self._clear_done)
        hl.addWidget(clear_btn)

        outer.addWidget(hdr)

        # Scrollable card area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{border: none; background: {DARK_BG}; margin: 0px; padding: 0px;}}"
        )

        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet(f"background: {DARK_BG};")
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(6, 6, 6, 6)
        self._cards_layout.setSpacing(4)
        self._cards_layout.addStretch()

        scroll.setWidget(self._cards_widget)
        outer.addWidget(scroll, 1)

    def _setup_watchdog(self) -> None:
        """Start the freeze-detection timer."""
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(WATCHDOG_INTERVAL_MS)
        self._watchdog.timeout.connect(self._check_frozen)
        self._watchdog.start()

    @Slot()
    def _refresh(self) -> None:
        """Update all cards (called from registry listener on main thread)."""
        reg = ProcessRegistry.instance()
        for entry in reg.entries():
            if entry.pid not in self._cards:
                card = _ProcessCard(entry.pid)
                self._cards[entry.pid] = card
                self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._cards[entry.pid].update_from(entry)

            # Auto-clear: schedule removal of completed/errored entries
            if self._auto_clear and entry.state in (ProcessState.DONE, ProcessState.ERROR):
                if not getattr(self._cards[entry.pid], "_clear_scheduled", False):
                    self._cards[entry.pid]._clear_scheduled = True
                    pid = entry.pid
                    QTimer.singleShot(self._auto_clear_delay_ms, lambda p=pid: self._remove_pid(p))

    def _remove_pid(self, pid: str) -> None:
        """Remove a specific process entry (used by auto-clear)."""
        reg = ProcessRegistry.instance()
        entry = reg.get(pid)
        if entry and entry.state in (ProcessState.DONE, ProcessState.ERROR):
            reg.unregister(pid)
        if pid in self._cards:
            self._cards[pid].deleteLater()
            del self._cards[pid]

    def _on_auto_clear_toggled(self, checked: bool) -> None:
        """Handle auto-clear checkbox toggle."""
        self._auto_clear = checked
        if checked:
            # Sweep any already-done entries
            self._refresh()

    def _check_frozen(self) -> None:
        """Watchdog: detect frozen processes and escalate to force-kill."""
        reg = ProcessRegistry.instance()
        now = time.monotonic()
        for entry in list(reg.entries()):
            if entry.state not in (ProcessState.RUNNING, ProcessState.FROZEN):
                continue
            gap = now - entry.last_heartbeat
            if entry.state == ProcessState.RUNNING and gap > FREEZE_THRESHOLD_SECS:
                entry.state = ProcessState.FROZEN
                reg._notify()
            elif (
                entry.state == ProcessState.FROZEN
                and gap > FREEZE_THRESHOLD_SECS * 2
            ):
                reg._notify()

    def _clear_done(self) -> None:
        """Remove all done/error entries."""
        reg = ProcessRegistry.instance()
        finished = [
            pid
            for pid, e in reg._entries.items()
            if e.state in (ProcessState.DONE, ProcessState.ERROR)
        ]
        for pid in finished:
            reg.unregister(pid)
            if pid in self._cards:
                self._cards[pid].deleteLater()
                del self._cards[pid]


class _ProcessCard(QFrame):
    """Per-process card showing name, progress, status, buttons, and lazy-loaded log."""

    def __init__(self, pid: str, parent=None):
        super().__init__(parent)
        self._pid = pid
        self._log_expanded = False
        self._build_ui()

    def _build_ui(self) -> None:
        """Build the card layout."""
        self.setStyleSheet(
            f"QFrame {{background: {PANEL_BG}; border: 1px solid {BORDER}; border-radius: 8px;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)

        # Row 1: name + badge
        r1 = QHBoxLayout()
        self._name_lbl = QLabel()
        self._name_lbl.setStyleSheet(
            f"color: {TEXT}; font-weight: bold; font-size: 12px; border: none; background: transparent;"
        )
        self._badge_lbl = QLabel()
        self._badge_lbl.setFixedWidth(70)
        self._badge_lbl.setAlignment(Qt.AlignCenter)
        r1.addWidget(self._name_lbl, 1)
        r1.addWidget(self._badge_lbl)
        lay.addLayout(r1)

        # Row 2: progress bar
        self._progress = QProgressBar()
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar {{background: {DARK_BG}; border: none; border-radius: 2px;}}"
            f"QProgressBar::chunk {{background: {ACCENT}; border-radius: 2px;}}"
        )
        lay.addWidget(self._progress)

        # Row 3: elapsed time + buttons
        r3 = QHBoxLayout()
        self._elapsed_lbl = QLabel()
        self._elapsed_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; border: none; background: transparent;"
        )
        r3.addWidget(self._elapsed_lbl, 1)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedSize(60, 22)
        self._cancel_btn.setStyleSheet(
            f"QPushButton {{background: {PANEL_BG}; color: {TEXT}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 2px 6px; font-size: 10px;}}"
        )
        self._cancel_btn.clicked.connect(self._on_cancel)
        r3.addWidget(self._cancel_btn)

        self._kill_btn = QPushButton("Force kill")
        self._kill_btn.setFixedSize(70, 22)
        self._kill_btn.setStyleSheet(
            f"QPushButton {{background: {RED}44; color: {RED}; border: 1px solid {RED}; "
            f"border-radius: 4px; padding: 2px 6px; font-size: 10px;}}"
        )
        self._kill_btn.clicked.connect(self._on_kill)
        self._kill_btn.hide()
        r3.addWidget(self._kill_btn)

        self._log_btn = QPushButton("▶ Logs")
        self._log_btn.setFixedSize(56, 22)
        self._log_btn.setCheckable(True)
        self._log_btn.setStyleSheet(
            f"QPushButton {{background: {PANEL_BG}; color: {TEXT}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 2px 6px; font-size: 10px;}}"
        )
        self._log_btn.toggled.connect(self._toggle_log)
        r3.addWidget(self._log_btn)

        lay.addLayout(r3)

        # Row 4: lazy log area (hidden by default)
        self._log_edit = QPlainTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumHeight(100)
        self._log_edit.setStyleSheet(
            f"QPlainTextEdit {{background: {DARK_BG}; color: {SUBTEXT}; "
            f"border: 1px solid {BORDER}44; border-radius: 4px; font-size: 10px; "
            f"font-family: monospace; padding: 4px;}}"
        )
        self._log_edit.hide()
        lay.addWidget(self._log_edit)

    def update_from(self, entry: ProcessEntry) -> None:
        """Update card UI from ProcessEntry."""
        self._name_lbl.setText(entry.name)

        # State badge
        state_colors = {
            ProcessState.RUNNING: (ACCENT, "Running"),
            ProcessState.FROZEN: (YELLOW, "Frozen"),
            ProcessState.DONE: (GREEN, "Done"),
            ProcessState.ERROR: (RED, "Error"),
        }
        color, label = state_colors[entry.state]
        self._badge_lbl.setText(f"  {label}  ")
        self._badge_lbl.setStyleSheet(
            f"background: {color}22; color: {color}; border: 1px solid {color}; "
            f"border-radius: 8px; padding: 2px 6px; font-size: 10px; font-weight: bold;"
        )

        # Progress bar
        if entry.state == ProcessState.DONE:
            self._progress.setRange(0, 100)
            self._progress.setValue(100)
        elif entry.state == ProcessState.ERROR:
            self._progress.setRange(0, 100)
            self._progress.setValue(0)
        elif entry.progress < 0:
            self._progress.setRange(0, 0)  # indeterminate (animated)
        else:
            self._progress.setRange(0, 100)
            self._progress.setValue(entry.progress)

        # Elapsed time + ETA + rate
        elapsed = time.monotonic() - entry.start_time
        m, s = divmod(int(elapsed), 60)
        elapsed_text = f"{m:02d}:{s:02d}"

        info_parts = [elapsed_text]
        if entry.state in (ProcessState.RUNNING, ProcessState.FROZEN) and entry.total > 0 and entry.processed > 0:
            rate = entry.processed / elapsed if elapsed > 0 else 0
            if rate > 0:
                remaining = entry.total - entry.processed
                eta_secs = int(remaining / rate)
                em, es = divmod(eta_secs, 60)
                eh, em = divmod(em, 60)
                if eh > 0:
                    eta_text = f"{eh}h{em:02d}m"
                elif em > 0:
                    eta_text = f"{em}m{es:02d}s"
                else:
                    eta_text = f"{es}s"
                info_parts.append(f"ETA {eta_text}")
                info_parts.append(f"{int(rate):,}/s")
            info_parts.append(f"{entry.processed:,}/{entry.total:,}")

        self._elapsed_lbl.setText("  ·  ".join(info_parts))

        # Button visibility
        is_active = entry.state in (ProcessState.RUNNING, ProcessState.FROZEN)
        self._cancel_btn.setVisible(is_active and entry.cancel_cb is not None)
        self._kill_btn.setVisible(entry.state == ProcessState.FROZEN and entry.kill_cb is not None)

        # Lazy log population: only fill when expanded
        if self._log_expanded:
            self._populate_log(entry)

    def _toggle_log(self, checked: bool) -> None:
        """Toggle log expansion."""
        self._log_expanded = checked
        self._log_edit.setVisible(checked)
        self._log_btn.setText("▼ Logs" if checked else "▶ Logs")
        if checked:
            entry = ProcessRegistry.instance().get(self._pid)
            if entry:
                self._populate_log(entry)

    def _populate_log(self, entry: ProcessEntry) -> None:
        """Drain the ring-buffer into the edit widget (on-demand only)."""
        self._log_edit.setPlainText("\n".join(entry.log))
        sb = self._log_edit.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def _on_cancel(self) -> None:
        """User clicked Cancel button."""
        entry = ProcessRegistry.instance().get(self._pid)
        if entry and entry.cancel_cb:
            entry.cancel_cb()

    def _on_kill(self) -> None:
        """User clicked Force kill button."""
        entry = ProcessRegistry.instance().get(self._pid)
        if entry and entry.kill_cb:
            entry.kill_cb()
            ProcessRegistry.instance().mark_done(self._pid)
