from __future__ import annotations
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List


@dataclass
class ScanState:
    scan_id: int
    cancel_event: threading.Event = field(default_factory=threading.Event)
    events: List[Dict] = field(default_factory=list)    # ring buffer of last 200
    listeners: List[queue.Queue] = field(default_factory=list)
    done: bool = False
    thread: Optional[threading.Thread] = None

    BUFFER = 200

    def push(self, event: dict) -> None:
        self.events.append(event)
        if len(self.events) > self.BUFFER:
            self.events = self.events[-self.BUFFER:]
        for q in list(self.listeners):
            try:
                q.put_nowait(event)
            except queue.Full:
                pass


class ScanRegistry:
    """In-process map of scan_id -> ScanState. Only one active scan at a time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_id: Optional[int] = None
        self._states: Dict[int, ScanState] = {}

    def active_id(self) -> Optional[int]:
        with self._lock:
            return self._active_id

    def start(self, scan_id: int) -> ScanState:
        with self._lock:
            if self._active_id is not None:
                raise RuntimeError(f"scan {self._active_id} already running")
            state = ScanState(scan_id=scan_id)
            self._states[scan_id] = state
            self._active_id = scan_id
            return state

    def finish(self, scan_id: int) -> None:
        with self._lock:
            if scan_id in self._states:
                self._states[scan_id].done = True
            if self._active_id == scan_id:
                self._active_id = None

    def get(self, scan_id: int) -> Optional[ScanState]:
        return self._states.get(scan_id)


REGISTRY = ScanRegistry()
