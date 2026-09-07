"""Hard gate: ignore STT while TTS is busy or in post-TTS cooldown.

Prevents JARVIS from hearing its own voice and entering a self-talk loop.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Protocol


class SpeakBusyProvider(Protocol):
    @property
    def is_busy(self) -> bool: ...

    @property
    def is_speaking(self) -> bool: ...


ListenGateListener = Callable[[bool], None]


class SelfListenGuard:
    """Single source of truth for mute-during-speak / post-TTS cooldown."""

    def __init__(
        self,
        speaker: SpeakBusyProvider,
        *,
        enabled: bool = True,
        cooldown_ms: int = 220,
        block_while_processing: bool = True,
    ) -> None:
        self.speaker = speaker
        self.enabled = bool(enabled)
        self.cooldown_ms = max(0, int(cooldown_ms))
        self.block_while_processing = bool(block_while_processing)
        self._lock = threading.RLock()
        self._processing = False
        self._cooldown_until = 0.0
        self._listeners: list[ListenGateListener] = []
        self._last_blocked: Optional[bool] = None

    def add_listener(self, callback: ListenGateListener) -> None:
        self._listeners.append(callback)
        try:
            callback(self.blocked)
        except Exception:
            pass

    def set_processing(self, active: bool) -> None:
        with self._lock:
            self._processing = bool(active)
        self._notify()

    def arm_cooldown(self) -> None:
        """Start post-TTS cooldown (call after speaker.wait_until_idle)."""
        with self._lock:
            self._cooldown_until = time.monotonic() + (self.cooldown_ms / 1000.0)
        self._notify()

    def clear_cooldown(self) -> None:
        with self._lock:
            self._cooldown_until = 0.0
        self._notify()

    @property
    def blocked(self) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            if self.block_while_processing and self._processing:
                return True
            if time.monotonic() < self._cooldown_until:
                return True
        try:
            if self.speaker.is_busy:
                return True
        except Exception:
            pass
        return False

    def should_accept_transcript(self, text: str = "") -> bool:
        """Return False while speaking/processing/cooldown (hard gate)."""
        del text
        return not self.blocked

    def refresh(self) -> None:
        """Re-evaluate and notify listeners (e.g. after speaker busy change)."""
        self._notify()

    def wait_until_accepting(self, timeout: float = 35.0) -> None:
        """Block until TTS idle, then apply cooldown."""
        wait = getattr(self.speaker, "wait_until_idle", None)
        if callable(wait):
            wait(timeout=timeout)
        self.arm_cooldown()
        deadline = time.monotonic() + max(0.0, self.cooldown_ms / 1000.0) + 0.05
        while time.monotonic() < deadline:
            if not self.blocked:
                break
            time.sleep(0.02)
        self._notify()

    def _notify(self) -> None:
        state = self.blocked
        if state == self._last_blocked:
            return
        self._last_blocked = state
        for cb in list(self._listeners):
            try:
                cb(state)
            except Exception:
                pass
