"""Degraded / offline mode — local tools stay up when Cursor is down (Phase 6)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class DegradedState:
    active: bool = False
    reason: str = ""
    cursor_available: bool = True


class DegradedMode:
    """Process-wide degraded flag — Fast tools never depend on this being off."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = DegradedState()

    def enter(self, reason: str = "model_unavailable") -> None:
        with self._lock:
            self._state = DegradedState(
                active=True,
                reason=reason,
                cursor_available=False,
            )

    def exit(self) -> None:
        with self._lock:
            self._state = DegradedState(active=False, reason="", cursor_available=True)

    def snapshot(self) -> DegradedState:
        with self._lock:
            return DegradedState(
                active=self._state.active,
                reason=self._state.reason,
                cursor_available=self._state.cursor_available,
            )

    @property
    def active(self) -> bool:
        return self.snapshot().active

    def allow_cursor(self) -> bool:
        return self.snapshot().cursor_available


_GLOBAL = DegradedMode()


def get_degraded_mode() -> DegradedMode:
    return _GLOBAL
