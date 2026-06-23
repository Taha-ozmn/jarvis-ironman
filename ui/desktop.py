"""Native desktop window for the JARVIS HUD (pywebview / WKWebView on macOS)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import JarvisCore


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

    def on_closed() -> None:
        try:
            core.shutdown()
        except Exception:
            pass

    window.events.closed += on_closed
    webview.start(gui="cocoa", debug=False)
