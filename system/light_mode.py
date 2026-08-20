"""Auto light mode when host is under memory/CPU pressure."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from system.host_metrics import get_host_metrics

logger = logging.getLogger(__name__)

PauseFn = Callable[[float], None]


class LightModeController:
    """Throttle expensive subsystems when the Mac is struggling."""

    def __init__(
        self,
        *,
        check_interval_sec: float = 20.0,
        pause_seconds: float = 45.0,
        on_enter: Optional[Callable[[dict[str, Any]], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
    ) -> None:
        self.check_interval_sec = max(10.0, float(check_interval_sec))
        self.pause_seconds = max(15.0, float(pause_seconds))
        self._on_enter = on_enter
        self._on_exit = on_exit
        self._active = False
        self._active_until = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._pause_hooks: list[PauseFn] = []

    @property
    def active(self) -> bool:
        with self._lock:
            if self._active and time.monotonic() > self._active_until:
                self._active = False
                if self._on_exit:
                    try:
                        self._on_exit()
                    except Exception:
                        logger.exception("light mode on_exit failed")
            return self._active

    def add_pause_hook(self, fn: PauseFn) -> None:
        self._pause_hooks.append(fn)

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="jarvis-light-mode",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def evaluate(self, metrics: dict[str, Any] | None = None) -> bool:
        """Enter/refresh light mode from metrics. Returns whether active."""
        m = metrics or get_host_metrics()
        if not m.get("light_mode"):
            return self.active
        with self._lock:
            was = self._active
            self._active = True
            self._active_until = time.monotonic() + self.pause_seconds
        for hook in self._pause_hooks:
            try:
                hook(self.pause_seconds)
            except Exception:
                logger.exception("light mode pause hook failed")
        if not was and self._on_enter:
            try:
                self._on_enter(m)
            except Exception:
                logger.exception("light mode on_enter failed")
        logger.info(
            "Light mode active — cpu=%s mem=%s swap_mb=%s",
            m.get("cpu_pct"),
            m.get("mem_pct"),
            m.get("swap_used_mb"),
        )
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.evaluate()
            except Exception:
                logger.exception("light mode evaluate failed")
            # Touch active property to expire
            _ = self.active
            self._stop.wait(self.check_interval_sec)
