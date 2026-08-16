"""Cancellation token for long-running plans / tool loops (Phase 4)."""

from __future__ import annotations

import threading
from typing import Optional


class CancellationToken:
    """Cooperative cancel — check ``is_cancelled`` between steps."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason: str = ""

    def cancel(self, reason: str = "user_cancel") -> None:
        self._reason = reason or "user_cancel"
        self._event.set()

    def reset(self) -> None:
        self._event.clear()
        self._reason = ""

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def throw_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise CancelledError(self._reason or "cancelled")


class CancelledError(Exception):
    """Raised when a cooperative cancel is observed mid-plan."""


# Process-wide active token for voice "dur" → plan cancel
_active_lock = threading.Lock()
_active_token: Optional[CancellationToken] = None


def set_active_token(token: Optional[CancellationToken]) -> None:
    global _active_token
    with _active_lock:
        _active_token = token


def get_active_token() -> Optional[CancellationToken]:
    with _active_lock:
        return _active_token


def cancel_active(reason: str = "user_cancel") -> bool:
    """Cancel the active plan token if any. Returns True if a token was cancelled."""
    token = get_active_token()
    if token is None or token.is_cancelled:
        return False
    token.cancel(reason)
    return True
