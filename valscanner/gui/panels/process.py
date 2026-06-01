"""
ProcessPanel: Process Monitor panel (4th column, mockup parity).

Layout matches local_plans/04_re_design — four collapsible sections:
  1. Summary  — Processed / Elapsed / Throughput / ETA
  2. Meters   — Progress / CPU / RAM / Disk read
  3. Workers  — compact per-worker tiles + queue header
  4. Throughput · 60s — gradient sparkline

Backend (ProcessRegistry) is unchanged in API; extended with rate/mem fields
and aggregate helpers (total_processed, throughput_per_sec, queue_depth, …).
A SystemSampler (psutil, 1Hz) feeds CPU/RAM/disk meters and the sparkline.

Components:
- ProcessRegistry: singleton, zero Qt deps, tracks all background workers
- SystemSampler:   QTimer-driven psutil sampler (CPU/RAM/disk)
- ProcessPanel(QWidget): vertical layout (header + 4 sections)
- _PMSection: collapsible header with chevron + optional badge
- _PMStat / _PMMeter / _PMWorker: tile primitives
- _Notifier: Qt signal bridge for cross-thread updates from workers
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional, Tuple

import psutil

from PySide6.QtCore import (
    Qt, QTimer, Signal, Slot, QObject, QMetaObject, QPropertyAnimation, Property,
    QEasingCurve, QSize,
)
from PySide6.QtGui import QAction, QPainter, QColor, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QScrollArea, QMenu, QSizePolicy,
    QToolButton,
)

from ..constants import (
    DARK_BG, PANEL_BG, ACCENT, TEXT, SUBTEXT, BORDER,
    GREEN, RED, YELLOW, BG2, BG3, DIVIDER2,
)
from ..fonts import mono_font_family
from ..widgets.sparkline import Sparkline
from .. import icons as _icons
from ..persistence import settings, Keys
from ..theme import Spacing, Margins, Sizes


# ── Constants ────────────────────────────────────────────────────────────────

FREEZE_THRESHOLD_SECS = 30
WATCHDOG_INTERVAL_MS = 2_000
LOG_RING_BUFFER_SIZE = 500
SAMPLER_INTERVAL_MS = 1_000
THROUGHPUT_WINDOW_SECS = 5
SPARKLINE_CAPACITY = 60


# ── Backend: registry data model ─────────────────────────────────────────────

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
    rate: str = "—"        # human-readable rate ("12.4 f/s", "118 MB/s")
    mem: str = "0 MB"      # human-readable memory footprint
    task_detail: str = ""  # short status line e.g. "thumb · DSC_04412.ARW"
    cancel_cb: Optional[Callable[[], None]] = None
    kill_cb: Optional[Callable[[], None]] = None
    log: deque = field(default_factory=lambda: deque(maxlen=LOG_RING_BUFFER_SIZE))


class ProcessRegistry:
    """Singleton registry for all background workers.

    Zero Qt dependencies — safe to import from core or tests.
    Worker threads call heartbeat(), push_log(), set_progress(), mark_done(),
    mark_error(); panels read via entries() and aggregates().
    Qt slots connect to the singleton's _notifier.changed signal.
    """

    _instance: Optional["ProcessRegistry"] = None

    @classmethod
    def instance(cls) -> "ProcessRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._entries: dict[str, ProcessEntry] = {}
        self._notifier: _Notifier | None = None
        self._session_start: float = time.monotonic()
        # Rolling samples of (monotonic_ts, total_processed) for throughput.
        # Only sample_throughput() appends — keep throughput_per_sec() pure
        # so callers can read it many times per tick without disturbing the
        # rolling window (otherwise dt collapses to ~0 and the rate flickers).
        self._throughput_samples: deque[Tuple[float, int]] = deque(maxlen=60)
        self._throughput_cached: float = 0.0

    # ── Worker lifecycle ──

    def register(
        self,
        name: str,
        cancel_cb: Optional[Callable[[], None]] = None,
        kill_cb: Optional[Callable[[], None]] = None,
    ) -> str:
        pid = str(uuid.uuid4())
        now = time.monotonic()
        if not self._entries:
            # Fresh session start when first worker arrives
            self._session_start = now
            self._throughput_samples.clear()
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
        if pid in self._entries:
            del self._entries[pid]
            self._notify()

    # ── Worker API (called from worker threads) ──

    def heartbeat(self, pid: str) -> None:
        if pid in self._entries:
            self._entries[pid].last_heartbeat = time.monotonic()

    def set_progress(self, pid: str, value: int) -> None:
        if pid in self._entries:
            self._entries[pid].progress = value
            self._notify()

    def set_progress_detailed(self, pid: str, processed: int, total: int) -> None:
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

    def set_rate(self, pid: str, rate: str) -> None:
        if pid in self._entries:
            self._entries[pid].rate = rate

    def set_mem(self, pid: str, mem: str) -> None:
        if pid in self._entries:
            self._entries[pid].mem = mem

    def set_task_detail(self, pid: str, detail: str) -> None:
        if pid in self._entries:
            self._entries[pid].task_detail = detail

    def push_log(self, pid: str, msg: str) -> None:
        if pid in self._entries:
            self._entries[pid].log.append(msg)

    def mark_done(self, pid: str) -> None:
        if pid in self._entries:
            self._entries[pid].state = ProcessState.DONE
            self._notify()

    def mark_error(self, pid: str, msg: str = "") -> None:
        if pid in self._entries:
            self._entries[pid].state = ProcessState.ERROR
            if msg:
                self._entries[pid].log.append(f"[ERROR] {msg}")
            self._notify()

    # ── Panel API ──

    def entries(self) -> list[ProcessEntry]:
        return list(self._entries.values())

    def get(self, pid: str) -> Optional[ProcessEntry]:
        return self._entries.get(pid)

    def add_listener(self, cb: Callable[[], None]) -> None:
        if self._notifier is None:
            self._notifier = _Notifier()
        self._notifier.changed.connect(cb)

    def _notify(self) -> None:
        if self._notifier is None:
            self._notifier = _Notifier()
        self._notifier.notify_queued()

    # ── Aggregates ──

    def total_processed(self) -> int:
        return sum(e.processed for e in self._entries.values())

    def total_expected(self) -> int:
        return sum(e.total for e in self._entries.values())

    def session_elapsed(self) -> float:
        if not self._entries:
            return 0.0
        return time.monotonic() - self._session_start

    def queue_depth(self) -> int:
        depth = 0
        for e in self._entries.values():
            if e.state in (ProcessState.RUNNING, ProcessState.FROZEN) and e.total > 0:
                depth += max(0, e.total - e.processed)
        return depth

    def worker_counts(self) -> Tuple[int, int, int, int]:
        """Return (busy, done, idle, total)."""
        busy = done = idle = 0
        for e in self._entries.values():
            if e.state in (ProcessState.RUNNING, ProcessState.FROZEN):
                # idle = no progress in the last heartbeat tick AND total unknown
                if e.total == 0 and e.processed == 0:
                    idle += 1
                else:
                    busy += 1
            elif e.state == ProcessState.DONE:
                done += 1
        return busy, done, idle, len(self._entries)

    def sample_throughput(self) -> float:
        """Append a new (now, total_processed) sample and recompute the cached
        throughput. Call this exactly once per tick (1 Hz from SystemSampler).
        """
        now = time.monotonic()
        self._throughput_samples.append((now, self.total_processed()))
        cutoff = now - THROUGHPUT_WINDOW_SECS
        while self._throughput_samples and self._throughput_samples[0][0] < cutoff:
            self._throughput_samples.popleft()
        if len(self._throughput_samples) < 2:
            self._throughput_cached = 0.0
        else:
            t0, p0 = self._throughput_samples[0]
            t1, p1 = self._throughput_samples[-1]
            dt = max(0.001, t1 - t0)
            self._throughput_cached = max(0.0, (p1 - p0) / dt)
        return self._throughput_cached

    def throughput_per_sec(self) -> float:
        """Pure read of the last sampled rate (no side effects)."""
        return self._throughput_cached

    def overall_progress(self) -> int:
        """Combined 0-100 across all entries (by total/processed). 0 if unknown."""
        tot = self.total_expected()
        if tot <= 0:
            return 0
        return min(100, int(self.total_processed() / tot * 100))


class _Notifier(QObject):
    """Qt signal bridge: worker threads call notify_queued(), main thread gets changed signal."""
    changed = Signal()

    def notify_queued(self) -> None:
        QMetaObject.invokeMethod(self, "_emit_changed", Qt.QueuedConnection)

    @Slot()
    def _emit_changed(self) -> None:
        self.changed.emit()


# ── System sampler (psutil) ──────────────────────────────────────────────────

class SystemSampler(QObject):
    """1Hz psutil sampler. Emits sample(cpu_pct, ram_used_b, ram_total_b, disk_read_bps)."""

    sample = Signal(float, "qlonglong", "qlonglong", float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(SAMPLER_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._last_disk_read: int | None = None
        self._last_disk_t: float | None = None
        # Prime cpu_percent so first call returns a meaningful value
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        try:
            cpu = float(psutil.cpu_percent(interval=None))
            vm = psutil.virtual_memory()
            ram_used = int(vm.used)
            ram_total = int(vm.total)
            disk_bps = 0.0
            io = psutil.disk_io_counters()
            now = time.monotonic()
            if io is not None:
                read_bytes = int(io.read_bytes)
                if self._last_disk_read is not None and self._last_disk_t is not None:
                    dt = max(0.001, now - self._last_disk_t)
                    disk_bps = max(0.0, (read_bytes - self._last_disk_read) / dt)
                self._last_disk_read = read_bytes
                self._last_disk_t = now
            self.sample.emit(cpu, ram_used, ram_total, disk_bps)
        except Exception:
            # Never let sampler errors break the UI
            pass


# ── Formatting helpers ───────────────────────────────────────────────────────

def _fmt_bytes(n: float) -> str:
    """Compact human-readable byte size (1.42 GB, 184 MB, …)."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0:
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.2f} {unit}" if n < 10 else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def _fmt_hms(secs: float) -> str:
    """HH:MM:SS or MM:SS, depending on magnitude."""
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ── Live-dot widget ──────────────────────────────────────────────────────────

class _LiveDot(QWidget):
    """6px amber dot with pulsing halo while active."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._opacity = 1.0
        self._active = False
        self._anim = QPropertyAnimation(self, b"opacity", self)
        self._anim.setDuration(1600)
        self._anim.setStartValue(1.0)
        self._anim.setKeyValueAt(0.5, 0.35)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if active:
            self._anim.start()
            self.show()
        else:
            self._anim.stop()
            self._opacity = 1.0
            self.hide()
        self.update()

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, v: float) -> None:
        self._opacity = v
        self.update()

    opacity = Property(float, _get_opacity, _set_opacity)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        acc = QColor(str(ACCENT))
        halo = QColor(acc); halo.setAlphaF(0.22 * self._opacity)
        p.setBrush(halo)
        p.setPen(Qt.NoPen)
        p.drawEllipse(1, 1, 12, 12)
        core = QColor(acc); core.setAlphaF(self._opacity)
        p.setBrush(core)
        p.drawEllipse(4, 4, 6, 6)
        p.end()


# ── Collapsible section ──────────────────────────────────────────────────────

class _PMSection(QWidget):
    """Collapsible section with chevron header + optional right-aligned badge."""

    toggled = Signal(bool)  # emitted with new open-state

    def __init__(
        self,
        title: str,
        *,
        open_: bool = True,
        persist_key: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._persist_key = persist_key
        self._open = open_
        if persist_key is not None:
            saved = settings().value(persist_key)
            if saved is not None:
                self._open = str(saved).lower() in ("1", "true", "yes")
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*Margins.NONE)
        outer.setSpacing(Spacing.NONE)
        # Header
        self._hdr = QToolButton(self)
        self._hdr.setAutoRaise(True)
        self._hdr.setCheckable(False)
        self._hdr.setFixedHeight(Sizes.BUTTON_H)
        self._hdr.setCursor(Qt.PointingHandCursor)
        self._hdr.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._hdr.setStyleSheet(
            "QToolButton {"
            f" background: transparent; color: {SUBTEXT};"
            " border: 0; padding: 0 12px;"
            " text-align: left;"
            "}"
            f"QToolButton:hover {{ background: {BG2}; color: {TEXT}; }}"
        )
        self._hdr.clicked.connect(self._on_clicked)
        outer.addWidget(self._hdr)

        # Header inner layout (chevron + title + badge)
        hl = QHBoxLayout(self._hdr)
        hl.setContentsMargins(Spacing.MD, Spacing.NONE, Spacing.MD, Spacing.NONE)
        hl.setSpacing(Spacing.PX6)
        self._chev = QLabel()
        self._chev.setFixedSize(12, 12)
        hl.addWidget(self._chev)
        self._ttl_lbl = QLabel(self._title.upper())
        self._ttl_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; font-weight: 600; letter-spacing: 1px;"
            " background: transparent;"
        )
        hl.addWidget(self._ttl_lbl)
        hl.addStretch(1)
        self._badge_lbl = QLabel("")
        self._badge_lbl.setStyleSheet(
            f"color: {TEXT}; font-family: '{mono_font_family()}', monospace;"
            f" font-size: 10px; font-weight: 600; background: transparent;"
        )
        hl.addWidget(self._badge_lbl)

        # Body
        self._body = QWidget(self)
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(*Margins.NONE)
        self._body_lay.setSpacing(Spacing.NONE)
        outer.addWidget(self._body)

        # Bottom divider
        self._sep = QFrame(self)
        self._sep.setFrameShape(QFrame.HLine)
        self._sep.setFixedHeight(Sizes.DIVIDER)
        self._sep.setStyleSheet(f"background: {BORDER}; border: 0;")
        outer.addWidget(self._sep)

        self._refresh_chev()
        self._body.setVisible(self._open)

    def set_body_widget(self, w: QWidget) -> None:
        # Remove any existing children first
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            wdg = item.widget()
            if wdg is not None:
                wdg.setParent(None)
        self._body_lay.addWidget(w)

    def set_badge(self, text: str) -> None:
        self._badge_lbl.setText(text)

    def is_open(self) -> bool:
        return self._open

    def _on_clicked(self) -> None:
        self._open = not self._open
        self._body.setVisible(self._open)
        self._refresh_chev()
        if self._persist_key is not None:
            settings().setValue(self._persist_key, "true" if self._open else "false")
        self.toggled.emit(self._open)

    def _refresh_chev(self) -> None:
        # Chevron rotates: down when open, right when closed
        name = "chevron-down" if self._open else "chevron-right"
        # Map collapsed chevron to MDI directly (we registered chevron-down only).
        # Use the registered "chevron-down" pixmap and rotate via setRotation isn't
        # available on QLabel; just swap icon for the collapsed state.
        try:
            if self._open:
                pm = _icons.pixmap("chevron-down", 12, color=str(SUBTEXT))
            else:
                # Use a fresh qtawesome icon for chevron-right
                import qtawesome as qta
                pm = qta.icon("mdi.chevron-right", color=str(SUBTEXT)).pixmap(QSize(12, 12))
        except Exception:
            pm = None
        if pm is not None:
            self._chev.setPixmap(pm)


# ── Stat / Meter primitives ──────────────────────────────────────────────────

class _PMStat(QWidget):
    """Key/value tile for the Summary grid."""

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        self._build(label)

    def _build(self, label: str) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*Margins.NONE)
        lay.setSpacing(Spacing.PX2)
        self._k = QLabel(label.upper())
        self._k.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 9px; font-weight: 600; letter-spacing: 1px;"
            " background: transparent;"
        )
        self._v = QLabel("—")
        self._v.setStyleSheet(
            f"color: {TEXT}; font-family: '{mono_font_family()}', monospace;"
            " font-size: 14px; font-weight: 600; background: transparent;"
        )
        self._v.setTextFormat(Qt.RichText)
        lay.addWidget(self._k)
        lay.addWidget(self._v)

    def set_value(self, primary: str, unit: str = "", *, variant: str = "") -> None:
        color = str(TEXT)
        if variant == "acc":
            color = str(ACCENT)
        elif variant == "ok":
            color = str(GREEN)
        unit_html = (
            f"<span style='font-size:10px;color:{SUBTEXT};font-weight:500;margin-left:3px;'>"
            f"&nbsp;{unit}</span>"
            if unit else ""
        )
        self._v.setText(
            f"<span style='color:{color};'>{primary}</span>{unit_html}"
        )


class _PMMeter(QWidget):
    """Label + value + 4px horizontal bar."""

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        self._build(label)

    def _build(self, label: str) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*Margins.NONE)
        lay.setSpacing(Spacing.PX6)
        # Label row
        row = QHBoxLayout()
        row.setContentsMargins(*Margins.NONE)
        row.setSpacing(Spacing.NONE)
        self._k = QLabel(label.upper())
        self._k.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; font-weight: 500; letter-spacing: 1px;"
            " background: transparent;"
        )
        self._v = QLabel("—")
        self._v.setStyleSheet(
            f"color: {TEXT}; font-family: '{mono_font_family()}', monospace;"
            " font-size: 11px; font-weight: 600; background: transparent;"
        )
        self._v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self._k, 1)
        row.addWidget(self._v)
        lay.addLayout(row)
        # Bar
        self._bar = _BarFill()
        lay.addWidget(self._bar)

    def set_label(self, label: str) -> None:
        self._k.setText(label.upper())

    def set_value(self, value_text: str, pct: float) -> None:
        self._v.setText(value_text)
        self._bar.set_pct(pct)


class _BarFill(QWidget):
    """4px amber bar — paints a fill from 0..pct%."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(Sizes.BAR_H_TALL)
        self._pct = 0.0

    def set_pct(self, pct: float) -> None:
        self._pct = max(0.0, min(100.0, float(pct)))
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        h = self.height()
        # Track
        track = QColor(str(DARK_BG))
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, w, h, 2, 2)
        # Fill
        fw = int(w * (self._pct / 100.0))
        if fw > 0:
            fill = QColor(str(ACCENT))
            p.setBrush(fill)
            p.drawRoundedRect(0, 0, fw, h, 2, 2)
        p.end()


# ── Worker tile ──────────────────────────────────────────────────────────────

class _PMWorker(QFrame):
    """Compact worker tile: id + state pill + task line + mini bar + foot."""

    def __init__(self, pid: str, parent=None) -> None:
        super().__init__(parent)
        self._pid = pid
        self._state = ProcessState.RUNNING
        self._build_ui()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def _build_ui(self) -> None:
        self.setObjectName("pmWorker")
        self.setStyleSheet(
            "QFrame#pmWorker {"
            f" background: {DARK_BG}; border: 1px solid {BORDER}; border-radius: 4px;"
            "}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Spacing.PX10, Spacing.SM, Spacing.PX10, Spacing.PX9)
        lay.setSpacing(Spacing.PX6)

        # Header: id + state pill
        hd = QHBoxLayout()
        hd.setContentsMargins(*Margins.NONE)
        hd.setSpacing(Spacing.NONE)
        self._id_lbl = QLabel("W-—")
        self._id_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-family: '{mono_font_family()}', monospace;"
            " font-size: 10px; background: transparent;"
        )
        hd.addWidget(self._id_lbl, 1)
        self._state_wrap = QWidget()
        sw = QHBoxLayout(self._state_wrap)
        sw.setContentsMargins(*Margins.NONE)
        sw.setSpacing(Spacing.PX5)
        self._state_dot = QLabel()
        self._state_dot.setFixedSize(7, 7)
        self._state_lbl = QLabel("RUNNING")
        self._state_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 9px; font-weight: 600; letter-spacing: 1px;"
            " background: transparent;"
        )
        sw.addWidget(self._state_dot)
        sw.addWidget(self._state_lbl)
        hd.addWidget(self._state_wrap)
        lay.addLayout(hd)

        # Task line
        self._task_lbl = QLabel("…")
        self._task_lbl.setStyleSheet(
            f"color: {TEXT}; font-family: '{mono_font_family()}', monospace;"
            " font-size: 11px; background: transparent;"
        )
        self._task_lbl.setTextInteractionFlags(Qt.NoTextInteraction)
        lay.addWidget(self._task_lbl)

        # Mini bar
        self._bar = _BarFill()
        self._bar.setFixedHeight(Sizes.BAR_H)
        lay.addWidget(self._bar)

        # Footer: rate · mem
        ft = QHBoxLayout()
        ft.setContentsMargins(*Margins.NONE)
        ft.setSpacing(Spacing.NONE)
        self._rate_lbl = QLabel("—")
        self._rate_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-family: '{mono_font_family()}', monospace;"
            " font-size: 10px; background: transparent;"
        )
        self._mem_lbl = QLabel("0 MB")
        self._mem_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-family: '{mono_font_family()}', monospace;"
            " font-size: 10px; background: transparent;"
        )
        self._mem_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ft.addWidget(self._rate_lbl, 1)
        ft.addWidget(self._mem_lbl)
        lay.addLayout(ft)

    def _color_for_state(self, state: ProcessState) -> Tuple[str, str, float]:
        """Return (state_color, state_text, tile_opacity)."""
        if state == ProcessState.RUNNING:
            return str(ACCENT), "BUSY", 1.0
        if state == ProcessState.FROZEN:
            return str(YELLOW), "FROZEN", 1.0
        if state == ProcessState.DONE:
            return str(GREEN), "DONE", 1.0
        if state == ProcessState.ERROR:
            return str(RED), "ERROR", 1.0
        return str(SUBTEXT), "IDLE", 0.55

    def update_from(self, entry: ProcessEntry, *, worker_index: int) -> None:
        self._state = entry.state
        # Treat zero-progress RUNNING with no totals as idle visually
        visual_state = entry.state
        is_idle = (
            entry.state == ProcessState.RUNNING
            and entry.total == 0
            and entry.processed == 0
            and not entry.task_detail
        )
        if is_idle:
            state_color = str(SUBTEXT)
            state_text = "IDLE"
            tile_opacity = 0.55
        else:
            state_color, state_text, tile_opacity = self._color_for_state(visual_state)

        # ID label
        self._id_lbl.setText(f"W-{worker_index:02d}")

        # State pill
        self._state_lbl.setText(state_text)
        self._state_lbl.setStyleSheet(
            f"color: {state_color}; font-size: 9px; font-weight: 600; letter-spacing: 1px;"
            " background: transparent;"
        )
        dot_color = QColor(state_color)
        # Paint dot via stylesheet (rounded label)
        self._state_dot.setStyleSheet(
            f"background: {state_color}; border-radius: 2px;"
        )

        # Task line (fall back to entry.name when no detail)
        task = entry.task_detail or entry.name
        fm = QFontMetrics(self._task_lbl.font())
        avail = max(40, self.width() - 20)
        self._task_lbl.setText(fm.elidedText(task, Qt.ElideRight, avail))
        self._task_lbl.setToolTip(task)

        # Bar
        if entry.state == ProcessState.DONE:
            self._bar.set_pct(100.0)
        elif entry.state == ProcessState.ERROR:
            self._bar.set_pct(0.0)
        elif entry.total > 0:
            self._bar.set_pct(min(100.0, entry.processed * 100.0 / entry.total))
        else:
            # Indeterminate: show a hint bar at 30% when running
            self._bar.set_pct(0.0 if is_idle else 30.0)

        # Footer
        self._rate_lbl.setText(entry.rate or "—")
        self._mem_lbl.setText(entry.mem or "0 MB")

        # Tile opacity (idle)
        self.setWindowOpacity(tile_opacity)
        self.setGraphicsEffect(None)  # keep simple; no opacity effect noise
        self.setStyleSheet(
            "QFrame#pmWorker {"
            f" background: {DARK_BG}; border: 1px solid {BORDER}; border-radius: 4px;"
            f" {'color: ' + SUBTEXT + ';' if tile_opacity < 1.0 else ''}"
            "}"
        )

    def _on_context_menu(self, pos) -> None:
        entry = ProcessRegistry.instance().get(self._pid)
        if entry is None:
            return
        menu = QMenu(self)
        if entry.cancel_cb and entry.state in (ProcessState.RUNNING, ProcessState.FROZEN):
            act = QAction("Cancel", self)
            act.triggered.connect(lambda: entry.cancel_cb and entry.cancel_cb())
            menu.addAction(act)
        if entry.kill_cb and entry.state == ProcessState.FROZEN:
            act = QAction("Force kill", self)
            act.triggered.connect(lambda: self._force_kill(entry))
            menu.addAction(act)
        if menu.actions():
            menu.exec(self.mapToGlobal(pos))

    def _force_kill(self, entry: ProcessEntry) -> None:
        if entry.kill_cb:
            entry.kill_cb()
            ProcessRegistry.instance().mark_done(self._pid)


# ── ProcessPanel ─────────────────────────────────────────────────────────────

class ProcessPanel(QWidget):
    """Process Monitor panel — mockup-parity 4-section layout."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._workers: dict[str, _PMWorker] = {}
        self._worker_order: list[str] = []
        # Coalesce refresh() bursts: registry can fire dozens of times per
        # scan tick; we cap visible repaints at ~20 Hz.
        self._refresh_pending = False
        self._refresh_min_interval_ms = 50
        # Auto-clear (persisted)
        saved_ac = settings().value(Keys.PMON_AUTO_CLEAR)
        self._auto_clear = True if saved_ac is None else str(saved_ac).lower() in ("1", "true", "yes")
        self._auto_clear_delay_ms = 2_000
        # Latest sampler values (for refresh()'s meter recomputation)
        self._last_cpu = 0.0
        self._last_ram_used = 0
        self._last_ram_total = 1
        self._last_disk_bps = 0.0
        self._cpu_count = psutil.cpu_count(logical=True) or 1

        self._build_ui()
        self._setup_watchdog()

        # Sampler
        self._sampler = SystemSampler(self)
        self._sampler.sample.connect(self._on_sample)
        self._sampler.start()

        # Registry listener
        ProcessRegistry.instance().add_listener(self._refresh)
        self._refresh()

    # ── Build UI ──

    def _build_ui(self) -> None:
        self.setStyleSheet(f"background: {DARK_BG};")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*Margins.NONE)
        outer.setSpacing(Spacing.NONE)

        # Header
        hdr = QWidget()
        hdr.setFixedHeight(Sizes.HEADER_H_MD)
        hdr.setStyleSheet(
            f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(Spacing.PX14, Spacing.NONE, Spacing.SM, Spacing.NONE)
        hl.setSpacing(Spacing.SM)
        self._live_dot = _LiveDot()
        self._live_dot.hide()
        hl.addWidget(self._live_dot)
        title = QLabel("PROCESS MONITOR")
        title.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 11px; font-weight: 600;"
            " letter-spacing: 1.2px; background: transparent;"
        )
        hl.addWidget(title)
        hl.addStretch(1)

        # Overflow menu button (…)
        self._overflow_btn = QToolButton()
        self._overflow_btn.setAutoRaise(True)
        self._overflow_btn.setFixedSize(22, 22)
        self._overflow_btn.setCursor(Qt.PointingHandCursor)
        try:
            self._overflow_btn.setIcon(_icons.icon("dots-horizontal", color=str(SUBTEXT)))
        except Exception:
            self._overflow_btn.setText("…")
        self._overflow_btn.setToolTip("Process Monitor options")
        self._overflow_btn.clicked.connect(self._show_overflow_menu)
        hl.addWidget(self._overflow_btn)

        self._hdr_lay = hl
        outer.addWidget(hdr)

        # Scrollable section container
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(f"QScrollArea {{ background: {DARK_BG}; border: none; }}")
        self._body = QWidget()
        self._body.setStyleSheet(f"background: {DARK_BG};")
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(*Margins.NONE)
        body_lay.setSpacing(Spacing.NONE)

        # ── Summary section ──
        self._sec_summary = _PMSection(
            "Summary", open_=True, persist_key=Keys.PMON_SECTION_SUMMARY
        )
        summary_body = QWidget()
        summary_body.setStyleSheet(f"background: {DARK_BG};")
        sg = QGridLayout(summary_body)
        sg.setContentsMargins(Spacing.PX14, Spacing.PX10, Spacing.PX14, Spacing.MD)
        sg.setHorizontalSpacing(14)
        sg.setVerticalSpacing(6)
        self._stat_processed = _PMStat("Processed")
        self._stat_elapsed = _PMStat("Elapsed")
        self._stat_throughput = _PMStat("Throughput")
        self._stat_eta = _PMStat("ETA")
        sg.addWidget(self._stat_processed, 0, 0)
        sg.addWidget(self._stat_elapsed, 0, 1)
        sg.addWidget(self._stat_throughput, 1, 0)
        sg.addWidget(self._stat_eta, 1, 1)
        self._sec_summary.set_body_widget(summary_body)
        body_lay.addWidget(self._sec_summary)

        # ── Meters section ──
        self._sec_meters = _PMSection(
            "Meters", open_=True, persist_key=Keys.PMON_SECTION_METERS
        )
        meters_body = QWidget()
        meters_body.setStyleSheet(f"background: {DARK_BG};")
        ml = QVBoxLayout(meters_body)
        ml.setContentsMargins(Spacing.PX14, Spacing.MD, Spacing.PX14, Spacing.MD)
        ml.setSpacing(Spacing.PX10)
        self._meter_progress = _PMMeter("Progress")
        self._meter_cpu = _PMMeter(f"CPU · {self._cpu_count} cores")
        self._meter_ram = _PMMeter("RAM")
        self._meter_disk = _PMMeter("Disk read")
        ml.addWidget(self._meter_progress)
        ml.addWidget(self._meter_cpu)
        ml.addWidget(self._meter_ram)
        ml.addWidget(self._meter_disk)
        self._sec_meters.set_body_widget(meters_body)
        body_lay.addWidget(self._sec_meters)

        # ── Workers section ──
        self._sec_workers = _PMSection(
            "Workers", open_=True, persist_key=Keys.PMON_SECTION_WORKERS
        )
        workers_body = QWidget()
        workers_body.setStyleSheet(f"background: {DARK_BG};")
        wl = QVBoxLayout(workers_body)
        wl.setContentsMargins(Spacing.PX14, Spacing.PX6, Spacing.PX14, Spacing.PX14)
        wl.setSpacing(Spacing.SM)
        # Queue header row
        self._queue_lbl = QLabel("queue · 0")
        self._queue_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-family: '{mono_font_family()}', monospace;"
            " font-size: 10px; background: transparent; padding-bottom: 2px;"
        )
        wl.addWidget(self._queue_lbl)
        # Empty placeholder
        self._workers_empty = QLabel("No active workers")
        self._workers_empty.setAlignment(Qt.AlignCenter)
        self._workers_empty.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 11px; padding: 18px 0;"
            " background: transparent;"
        )
        wl.addWidget(self._workers_empty)
        wl.addStretch(1)
        self._workers_layout = wl
        self._sec_workers.set_body_widget(workers_body)
        body_lay.addWidget(self._sec_workers, 1)

        # ── Throughput sparkline section ──
        self._sec_spark = _PMSection(
            "Throughput · 60s", open_=True, persist_key=Keys.PMON_SECTION_SPARK
        )
        spark_body = QWidget()
        spark_body.setStyleSheet(f"background: {DARK_BG};")
        sl = QVBoxLayout(spark_body)
        sl.setContentsMargins(Spacing.PX14, Spacing.SM, Spacing.PX14, Spacing.MD)
        sl.setSpacing(Spacing.PX6)
        self._sparkline = Sparkline(capacity=SPARKLINE_CAPACITY)
        sl.addWidget(self._sparkline)
        self._sec_spark.set_body_widget(spark_body)
        body_lay.addWidget(self._sec_spark)

        body_lay.addStretch(1)
        self._scroll.setWidget(self._body)
        outer.addWidget(self._scroll, 1)

    # ── Public API used by MainWindow ──

    def add_header_button(self, btn) -> None:
        """Append an extra control (e.g. collapse button) to the header."""
        self._hdr_lay.addWidget(btn)

    # ── Watchdog & sampler hooks ──

    def _setup_watchdog(self) -> None:
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(WATCHDOG_INTERVAL_MS)
        self._watchdog.timeout.connect(self._check_frozen)
        self._watchdog.start()

    def _check_frozen(self) -> None:
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

    @Slot(float, "qlonglong", "qlonglong", float)
    def _on_sample(self, cpu: float, ram_used: int, ram_total: int, disk_bps: float) -> None:
        self._last_cpu = cpu
        self._last_ram_used = ram_used
        self._last_ram_total = ram_total
        self._last_disk_bps = disk_bps
        # Recompute meters using the latest sample
        self._refresh_meters()
        # Append a fresh throughput sample (1 Hz cadence) — the only mutator;
        # _refresh_summary then reads the cached value.
        rate = ProcessRegistry.instance().sample_throughput()
        self._sparkline.add_sample(rate)
        # Live throughput in section badge
        self._sec_spark.set_badge(f"{rate:.0f} f/s")
        # Refresh elapsed (1Hz tick keeps Summary live even when no workers update)
        self._refresh_summary()

    # ── Refresh ──

    @Slot()
    def _refresh(self) -> None:
        """Coalesce refresh bursts — flush at most every ~50 ms."""
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(self._refresh_min_interval_ms, self._do_refresh)

    def _do_refresh(self) -> None:
        self._refresh_pending = False
        self._refresh_workers()
        self._refresh_summary()
        self._refresh_meters()
        self._refresh_live_dot()

    def _refresh_live_dot(self) -> None:
        reg = ProcessRegistry.instance()
        active = any(
            e.state in (ProcessState.RUNNING, ProcessState.FROZEN)
            for e in reg.entries()
        )
        self._live_dot.set_active(active)

    def _refresh_summary(self) -> None:
        reg = ProcessRegistry.instance()
        processed = reg.total_processed()
        total = reg.total_expected()
        elapsed = reg.session_elapsed()
        rate = reg.throughput_per_sec()
        pct = reg.overall_progress()

        # Processed
        if total > 0:
            self._stat_processed.set_value(
                f"{processed:,}", unit=f"/ {total:,}"
            )
        else:
            self._stat_processed.set_value(f"{processed:,}")

        # Elapsed
        self._stat_elapsed.set_value(_fmt_hms(elapsed))

        # Throughput
        if rate > 0:
            self._stat_throughput.set_value(f"{rate:.0f}", unit="f/s", variant="acc")
        else:
            self._stat_throughput.set_value("—")

        # ETA
        if rate > 0 and total > processed:
            eta = (total - processed) / rate
            self._stat_eta.set_value(_fmt_hms(eta), unit="remaining")
        else:
            self._stat_eta.set_value("—")

        # Section badge
        self._sec_summary.set_badge(f"{pct}%" if total > 0 else "")

    def _refresh_meters(self) -> None:
        # Progress meter
        pct = ProcessRegistry.instance().overall_progress()
        self._meter_progress.set_value(f"{pct}%", float(pct))

        # CPU meter
        self._meter_cpu.set_label(f"CPU · {self._cpu_count} cores")
        self._meter_cpu.set_value(f"{self._last_cpu:.0f}%", self._last_cpu)

        # RAM meter
        ram_used = self._last_ram_used
        ram_total = self._last_ram_total or 1
        ram_pct = ram_used * 100.0 / ram_total
        self._meter_ram.set_value(
            f"{_fmt_bytes(ram_used)} / {_fmt_bytes(ram_total)}", ram_pct
        )

        # Disk read meter — peg the bar to a soft cap (200 MB/s)
        disk_mb = self._last_disk_bps / (1024 * 1024)
        disk_pct = min(100.0, disk_mb / 200.0 * 100.0)
        self._meter_disk.set_value(f"{disk_mb:.0f} MB/s", disk_pct)

    def _refresh_workers(self) -> None:
        reg = ProcessRegistry.instance()
        entries = reg.entries()
        by_pid = {e.pid: e for e in entries}
        # Remove tiles for dead pids
        for pid in list(self._workers.keys()):
            if pid not in by_pid:
                w = self._workers.pop(pid)
                if pid in self._worker_order:
                    self._worker_order.remove(pid)
                w.setParent(None)
                w.deleteLater()

        # Add missing tiles in stable order
        for e in entries:
            if e.pid not in self._workers:
                tile = _PMWorker(e.pid, self._body)
                self._workers[e.pid] = tile
                self._worker_order.append(e.pid)
                # Insert just before the trailing stretch (last item)
                insert_at = self._workers_layout.count() - 1
                self._workers_layout.insertWidget(insert_at, tile)

        # Update tiles
        for idx, pid in enumerate(self._worker_order, start=1):
            entry = by_pid.get(pid)
            if entry is None:
                continue
            self._workers[pid].update_from(entry, worker_index=idx)

        # Auto-clear: schedule removal of completed entries
        if self._auto_clear:
            for e in entries:
                if e.state in (ProcessState.DONE, ProcessState.ERROR):
                    tile = self._workers.get(e.pid)
                    if tile is not None and not getattr(tile, "_clear_scheduled", False):
                        tile._clear_scheduled = True
                        pid = e.pid
                        QTimer.singleShot(
                            self._auto_clear_delay_ms,
                            lambda p=pid: self._remove_pid(p),
                        )

        # Show / hide empty placeholder
        has_workers = bool(self._workers)
        self._workers_empty.setVisible(not has_workers)

        # Workers section badge: busy/total
        busy, _done, _idle, total = reg.worker_counts()
        self._sec_workers.set_badge(f"{busy}/{total}" if total else "")

        # Queue header
        self._queue_lbl.setText(f"queue · {reg.queue_depth():,}")

    def _remove_pid(self, pid: str) -> None:
        reg = ProcessRegistry.instance()
        entry = reg.get(pid)
        if entry and entry.state in (ProcessState.DONE, ProcessState.ERROR):
            reg.unregister(pid)
        # _refresh_workers will drop the tile on next tick

    # ── Overflow menu ──

    def _show_overflow_menu(self) -> None:
        menu = QMenu(self)
        ac = QAction("Auto-clear completed", self)
        ac.setCheckable(True)
        ac.setChecked(self._auto_clear)
        ac.toggled.connect(self._on_auto_clear_toggled)
        menu.addAction(ac)
        menu.addSeparator()
        clr = QAction("Clear done", self)
        clr.triggered.connect(self._clear_done)
        menu.addAction(clr)
        # Open below the button
        pos = self._overflow_btn.mapToGlobal(self._overflow_btn.rect().bottomRight())
        menu.exec(pos)

    def _on_auto_clear_toggled(self, checked: bool) -> None:
        self._auto_clear = checked
        settings().setValue(Keys.PMON_AUTO_CLEAR, "true" if checked else "false")
        if checked:
            self._refresh_workers()

    def _clear_done(self) -> None:
        reg = ProcessRegistry.instance()
        finished = [
            pid
            for pid, e in reg._entries.items()
            if e.state in (ProcessState.DONE, ProcessState.ERROR)
        ]
        for pid in finished:
            reg.unregister(pid)
