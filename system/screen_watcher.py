"""Lightweight continuous screen awareness — frontmost app poll, rare screenshots."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

ContextSetter = Callable[[str, Any], None]
ContextGetter = Callable[[str, Any], Any]


class ScreenWatcher:
    """Poll frontmost app cheaply; optional screenshot only on app/title change."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        poll_interval_sec: float = 6.0,
        screenshot_on_change: bool = True,
        screenshot_min_interval_sec: float = 45.0,
        set_extra: Optional[ContextSetter] = None,
        get_extra: Optional[ContextGetter] = None,
        frontmost_fn: Optional[Callable[[], Optional[dict[str, str]]]] = None,
        capture_fn: Optional[Callable[[Path], tuple[bool, str]]] = None,
    ) -> None:
        self.enabled = enabled
        self.poll_interval_sec = max(8.0, float(poll_interval_sec))
        self.screenshot_on_change = bool(screenshot_on_change)
        self.screenshot_min_interval_sec = max(30.0, float(screenshot_min_interval_sec))
        self._set_extra = set_extra
        self._get_extra = get_extra
        self._frontmost_fn = frontmost_fn
        self._capture_fn = capture_fn
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._last_key = ""
        self._last_shot_at = 0.0
        self._tcc_denied_logged = False
        self._paused_until = 0.0

    def start(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="jarvis-screen-watch",
                daemon=True,
            )
            self._thread.start()
            logger.info(
                "Screen watcher started (poll=%ss screenshot_on_change=%s)",
                self.poll_interval_sec,
                self.screenshot_on_change,
            )

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def pause_for(self, seconds: float) -> None:
        """Temporarily stop polling (e.g. light mode)."""
        self._paused_until = time.monotonic() + max(0.0, float(seconds))

    def poll_once(self) -> dict[str, Any]:
        """Single tick — used by tests and manual refresh."""
        return self._tick()

    def current_context(self) -> dict[str, Any]:
        if self._get_extra is None:
            return {}
        raw = self._get_extra("current_screen_context", {}) or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def _loop(self) -> None:
        while not self._stop.is_set():
            if time.monotonic() < self._paused_until:
                self._stop.wait(1.0)
                continue
            try:
                self._tick()
            except Exception:
                logger.exception("screen watcher tick failed")
            self._stop.wait(self.poll_interval_sec)

    def _tick(self) -> dict[str, Any]:
        info = self._frontmost()
        if info is None:
            # TCC / System Events denied — log once, do not spin hard
            if not self._tcc_denied_logged:
                self._tcc_denied_logged = True
                logger.warning(
                    "Screen watcher: frontmost app unavailable "
                    "(Accessibility / Automation TCC?). Pausing retries."
                )
                self.pause_for(120.0)
            ctx = {
                "ok": False,
                "error": "frontmost unavailable",
                "updated_at": time.time(),
            }
            self._publish(ctx)
            return ctx

        name = (info.get("name") or "").strip()
        title = (info.get("title") or "").strip()
        bundle = (info.get("bundle") or "").strip()
        key = f"{name}\0{title}"
        changed = key != self._last_key
        self._last_key = key

        ctx: dict[str, Any] = {
            "ok": True,
            "app": name,
            "title": title,
            "bundle": bundle,
            "changed": changed,
            "updated_at": time.time(),
            "summary": self._summary(name, title),
        }

        if (
            self.screenshot_on_change
            and changed
            and (time.monotonic() - self._last_shot_at)
            >= self.screenshot_min_interval_sec
        ):
            shot = self._maybe_screenshot()
            if shot:
                ctx["screenshot_path"] = shot
                self._last_shot_at = time.monotonic()

        self._publish(ctx)
        return ctx

    def _publish(self, ctx: dict[str, Any]) -> None:
        if self._set_extra is None:
            return
        try:
            self._set_extra("current_screen_context", ctx)
        except Exception:
            logger.exception("failed to store current_screen_context")

    def _frontmost(self) -> Optional[dict[str, str]]:
        if self._frontmost_fn is not None:
            return self._frontmost_fn()
        try:
            from tools.screen_tools import frontmost_app_info

            return frontmost_app_info()
        except Exception:
            return None

    def _maybe_screenshot(self) -> Optional[str]:
        path = Path("/tmp/jarvis-screen-watch.png")
        try:
            if self._capture_fn is not None:
                ok, msg = self._capture_fn(path)
            else:
                from tools.vision import capture_screen, is_screen_permission_error

                ok, msg = capture_screen(path)
                if not ok and is_screen_permission_error(msg):
                    if not self._tcc_denied_logged:
                        self._tcc_denied_logged = True
                        logger.warning(
                            "Screen watcher: Screen Recording TCC denied — "
                            "continuing with app title only."
                        )
                    self.screenshot_on_change = False
                    return None
            if ok:
                return str(path)
        except Exception:
            logger.exception("screen watcher screenshot failed")
        return None

    @staticmethod
    def _summary(name: str, title: str) -> str:
        if name and title:
            return f"Foreground: {name} («{title}»)."
        if name:
            return f"Foreground: {name}."
        return "Foreground app unknown."
