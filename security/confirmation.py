"""Confirmation gate — Level-3 pending queue with HUD/voice resolve."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

ConfirmCallback = Callable[[str, str], bool]
PendingCallback = Callable[["PendingConfirmation"], None]


@dataclass
class PendingConfirmation:
    id: str
    action: str
    details: str
    level: int = 3
    created_at: float = field(default_factory=time.time)
    decision: Optional[bool] = None
    event: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "details": self.details,
            "level": self.level,
            "created_at": self.created_at,
        }


class ConfirmationGate:
    """Block on Level-3 until HUD/voice resolves, or timeout (deny)."""

    def __init__(
        self,
        *,
        auto_approve: bool = False,
        callback: Optional[ConfirmCallback] = None,
        default_timeout: float = 60.0,
    ) -> None:
        self.auto_approve = auto_approve
        self._callback = callback
        self.default_timeout = float(default_timeout)
        self._lock = threading.RLock()
        self._pending: dict[str, PendingConfirmation] = {}
        self._order: list[str] = []
        self._on_pending: Optional[PendingCallback] = None
        self._legacy_flags: dict[str, bool] = {}

    def set_callback(self, callback: ConfirmCallback) -> None:
        self._callback = callback

    def set_on_pending(self, callback: PendingCallback) -> None:
        self._on_pending = callback

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._order)

    def pending_list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._pending[i].to_dict() for i in self._order if i in self._pending]

    def latest(self) -> Optional[PendingConfirmation]:
        with self._lock:
            if not self._order:
                return None
            return self._pending.get(self._order[-1])

    def approve(self, action: str) -> None:
        """Legacy helper — approve by action name or resolve latest matching action."""
        with self._lock:
            self._legacy_flags[action] = True
            for cid in reversed(self._order):
                p = self._pending.get(cid)
                if p and p.action == action and p.decision is None:
                    self._resolve_locked(cid, True)
                    return

    def deny(self, action: str) -> None:
        with self._lock:
            self._legacy_flags[action] = False
            for cid in reversed(self._order):
                p = self._pending.get(cid)
                if p and p.action == action and p.decision is None:
                    self._resolve_locked(cid, False)
                    return

    def resolve(self, confirm_id: str, approved: bool) -> bool:
        with self._lock:
            return self._resolve_locked(confirm_id, approved)

    def resolve_latest(self, approved: bool) -> Optional[str]:
        with self._lock:
            if not self._order:
                return None
            cid = self._order[-1]
            if self._resolve_locked(cid, approved):
                return cid
            return None

    def require(
        self,
        action: str,
        details: str = "",
        *,
        level: int = 3,
        timeout: Optional[float] = None,
    ) -> bool:
        """Return True if the action may proceed."""
        if self.auto_approve:
            return True
        if self._callback is not None:
            return bool(self._callback(action, details))

        with self._lock:
            if action in self._legacy_flags:
                return self._legacy_flags.pop(action)

        # Headless / no UI hook → safe deny without blocking (tests + soft path)
        if self._on_pending is None and self._callback is None:
            return False

        pending = PendingConfirmation(
            id=uuid.uuid4().hex[:12],
            action=action,
            details=details or "",
            level=int(level),
        )
        with self._lock:
            self._pending[pending.id] = pending
            self._order.append(pending.id)

        if self._on_pending:
            try:
                self._on_pending(pending)
            except Exception:
                pass

        wait_for = self.default_timeout if timeout is None else float(timeout)
        ok = pending.event.wait(timeout=max(0.1, wait_for))
        with self._lock:
            self._pending.pop(pending.id, None)
            if pending.id in self._order:
                self._order.remove(pending.id)
        if not ok or pending.decision is None:
            return False
        return bool(pending.decision)
    def _resolve_locked(self, confirm_id: str, approved: bool) -> bool:
        pending = self._pending.get(confirm_id)
        if pending is None or pending.decision is not None:
            return False
        pending.decision = bool(approved)
        pending.event.set()
        return True
