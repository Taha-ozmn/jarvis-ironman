"""Iron Man HUD — WebSocket status + browser voice commands."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable, Optional

from aiohttp import web

from system.hud_stats import get_telemetry

UI_DIR = Path(__file__).resolve().parent


class JarvisUI:
    def __init__(
        self,
        port: int = 8765,
        mic_config: dict[str, Any] | None = None,
        jarvis_config: dict[str, Any] | None = None,
        *,
        open_browser: bool = True,
        desktop_mode: bool = False,
        telemetry_interval: float = 2.0,
    ) -> None:
        self.port = port
        self.mic_config = mic_config or {}
        self.jarvis_config = jarvis_config or {}
        self.open_browser = open_browser
        self.desktop_mode = desktop_mode
        self.telemetry_interval = telemetry_interval
        self.on_mic_control: Optional[Callable[[bool, bool], None]] = None
        self._mic_enabled = True
        self._clients: set[web.WebSocketResponse] = set()
        self._command_queue: queue.Queue[str] = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._telemetry_stop = threading.Event()
        self._app = web.Application()
        self._app.router.add_get("/", self._index)
        self._app.router.add_get("/ws", self._websocket)

    async def _index(self, request: web.Request) -> web.Response:
        html = (UI_DIR / "index.html").read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")

    async def _websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        await ws.send_str(json.dumps({
            "type": "config",
            "mic": {
                "require_wake_word": self.mic_config.get("require_wake_word", False),
                "min_confidence": self.mic_config.get("min_confidence", 0.55),
                "pause_while_busy": self.mic_config.get("pause_while_busy", True),
                "min_command_length": self.mic_config.get("min_command_length", 3),
                "always_listen": self.mic_config.get("always_listen", True),
                "listen_language": self.mic_config.get("listen_language", "tr-TR"),
            },
            "persona": self.jarvis_config.get("persona", "iron_man"),
            "user_name": self.jarvis_config.get("user_name", "sir"),
            "desktop": self.desktop_mode,
            "native_mic": self.desktop_mode,
            "telemetry_interval_ms": int(self.telemetry_interval * 1000),
        }))
        await ws.send_str(json.dumps({
            "type": "telemetry",
            "data": get_telemetry(self.jarvis_config.get("model", "composer-2.5")),
        }))
        await ws.send_str(json.dumps({
            "type": "mic_state",
            "enabled": self._mic_enabled,
        }))
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    self._handle_message(msg.data)
                elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                    break
        finally:
            self._clients.discard(ws)
        return ws

    def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if data.get("type") == "command":
            text = (data.get("text") or "").strip()
            if text:
                self.broadcast("thinking", text)
                self._command_queue.put(text)
            return
        if data.get("type") == "mic_control":
            enabled = bool(data.get("enabled", True))
            silent = bool(data.get("silent", False))
            self._mic_enabled = enabled
            self.send_mic_state(enabled)
            if self.on_mic_control:
                self.on_mic_control(enabled, silent)

    def send_mic_state(self, enabled: bool) -> None:
        self._mic_enabled = enabled
        self._emit({"type": "mic_state", "enabled": enabled})

    def wait_for_command(self, timeout: float = 0.3) -> Optional[str]:
        try:
            return self._command_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def broadcast(self, status: str, detail: str = "", **extra: Any) -> None:
        self._emit({"type": "status", "status": status, "detail": detail, **extra})

    def send_boot(self, line: str, progress: int) -> None:
        self._emit({"type": "boot", "line": line, "progress": progress})

    def send_narration(self, text: str) -> None:
        self._emit({"type": "narrate", "text": text})

    def send_response(self, command: str, response: str) -> None:
        self._emit({
            "type": "response",
            "command": command,
            "response": response,
            "status": "speaking",
            "detail": response,
        })

    def send_telemetry(self, data: dict[str, Any]) -> None:
        self._emit({"type": "telemetry", "data": data})

    def _emit(self, payload: dict[str, Any]) -> None:
        if not self._clients or not self._loop:
            return
        message = json.dumps(payload, ensure_ascii=False)
        for client in list(self._clients):
            try:
                asyncio.run_coroutine_threadsafe(client.send_str(message), self._loop)
            except Exception:
                self._clients.discard(client)

    def _telemetry_loop(self) -> None:
        model = self.jarvis_config.get("model", "composer-2.5")
        while not self._telemetry_stop.is_set():
            self.send_telemetry(get_telemetry(model))
            time.sleep(self.telemetry_interval)

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        telemetry_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        telemetry_thread.start()

        async def _start() -> None:
            runner = web.AppRunner(self._app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", self.port)
            await site.start()
            self._ready.set()
            if self.open_browser:
                webbrowser.open(f"http://127.0.0.1:{self.port}")

        self._loop.run_until_complete(_start())
        self._loop.run_forever()

    def wait_ready(self, timeout: float = 5.0) -> None:
        self._ready.wait(timeout=timeout)

    def stop(self) -> None:
        self._telemetry_stop.set()
