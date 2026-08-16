"""Native desktop window for the JARVIS HUD (pywebview / WKWebView on macOS).

U-04: same HUD confirm UI as browser mode; window is focused when Level-3
authorization is required so Enter/Esc and buttons remain reachable.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from main import JarvisCore

logger = logging.getLogger(__name__)


class DesktopConfirmBridge:
    """Focus / flash the native window when a confirm dialog opens."""

    def __init__(self) -> None:
        self._window: Any = None
        self._lock = threading.Lock()

    def bind(self, window: Any) -> None:
        with self._lock:
            self._window = window

    def on_confirm_request(self, payload: Optional[dict] = None) -> None:
        del payload
        with self._lock:
            window = self._window
        if window is None:
            return
        try:
            # Bring HUD forward so AUTHORIZE / DENY (and Enter/Esc) work
            if hasattr(window, "restore"):
                window.restore()
            if hasattr(window, "show"):
                window.show()
            if hasattr(window, "evaluate_js"):
                window.evaluate_js(
                    "try{window.focus();document.getElementById('confirm-approve')"
                    "&&document.getElementById('confirm-approve').focus()}catch(e){}"
                )
        except Exception:
            logger.exception("desktop confirm focus failed")


def run_desktop_window(
    core: JarvisCore,
    *,
    port: int,
    title: str = "J.A.R.V.I.S. — Stark OS",
    width: int = 1280,
    height: int = 820,
) -> None:
    import webview

    url = f"http://127.0.0.1:{port}"
    bridge = DesktopConfirmBridge()

    # Wire UI confirm → native focus (parity with browser HUD)
    if getattr(core, "ui", None) is not None:
        core.ui.on_desktop_confirm = bridge.on_confirm_request

    def _jarvis_loop() -> None:
        try:
            core.boot()
            core.handle_desktop_voice_loop()
        except KeyboardInterrupt:
            pass
        finally:
            core.shutdown()

    worker = threading.Thread(target=_jarvis_loop, name="jarvis-core", daemon=True)
    worker.start()

    window = webview.create_window(
        title,
        url,
        width=width,
        height=height,
        min_size=(960, 640),
        resizable=True,
        fullscreen=False,
        background_color="#020810",
        text_select=True,
    )
    bridge.bind(window)

    def on_closed() -> None:
        try:
            core.shutdown()
        except Exception:
            pass

    window.events.closed += on_closed
    webview.start(gui="cocoa", debug=False)
