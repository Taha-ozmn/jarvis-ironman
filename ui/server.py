"""Iron Man HUD — WebSocket status, command center, confirmations."""

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
from ui.hud_data import build_command_center

UI_DIR = Path(__file__).resolve().parent

DataProvider = Callable[[], dict[str, Any]]
ConfirmHandler = Callable[[str, bool], bool]


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
        data_provider: Optional[DataProvider] = None,
        command_center_interval: float = 5.0,
        on_confirm: Optional[ConfirmHandler] = None,
        health_provider: Optional[DataProvider] = None,
    ) -> None:
        self.port = port
        self.mic_config = mic_config or {}
        self.jarvis_config = jarvis_config or {}
        self.open_browser = open_browser
        self.desktop_mode = desktop_mode
        self.telemetry_interval = telemetry_interval
        self.command_center_interval = max(2.0, float(command_center_interval))
        self.data_provider = data_provider
        self.health_provider = health_provider
        self.on_confirm = on_confirm
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
        self._app.router.add_get("/api/command-center", self._api_command_center)
        self._app.router.add_get("/api/health", self._api_health)

    async def _index(self, request: web.Request) -> web.Response:
        html = (UI_DIR / "index.html").read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")

    async def _api_command_center(self, request: web.Request) -> web.Response:
        payload = self._snapshot()
        return web.json_response(payload)

    async def _api_health(self, request: web.Request) -> web.Response:
        """Lightweight production probe — 200 when ok, 503 when degraded."""
        try:
            if self.health_provider:
                payload = self.health_provider()
            elif self.data_provider:
                snap = self.data_provider()
                payload = snap.get("diagnostics") if isinstance(snap, dict) else None
                if not isinstance(payload, dict):
                    payload = {
                        "ok": bool(snap.get("available")) if isinstance(snap, dict) else False,
                        "source": "command_center",
                    }
            else:
                payload = {"ok": True, "note": "no health provider"}
        except Exception as err:
            return web.json_response({"ok": False, "error": str(err)}, status=503)
        if not isinstance(payload, dict):
            payload = {"ok": False, "error": "invalid health payload"}
        # Explicit degraded flag forces 503 even if subsystem checks passed
        healthy = bool(payload.get("ok")) and not bool(payload.get("degraded"))
        status = 200 if healthy else 503
        return web.json_response(payload, status=status)

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
            "command_center": True,
        }))
        await ws.send_str(json.dumps({
            "type": "telemetry",
            "data": get_telemetry(self.jarvis_config.get("model", "composer-2.5")),
        }))
        await ws.send_str(json.dumps({
            "type": "mic_state",
            "enabled": self._mic_enabled,
        }))
        await ws.send_str(json.dumps({
            "type": "command_center",
            "data": self._snapshot(),
        }, ensure_ascii=False))
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    self._handle_message(msg.data)
                elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                    break
        finally:
            self._clients.discard(ws)
        return ws

    def _snapshot(self) -> dict[str, Any]:
        if not self.data_provider:
            return {"available": False, "reason": "no data provider"}
        try:
            return self.data_provider()
        except Exception as err:
            return {"available": False, "reason": str(err)}

    def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        msg_type = data.get("type")
        if msg_type == "command":
            text = (data.get("text") or "").strip()
            if text:
                self.broadcast("thinking", text)
                self._command_queue.put(text)
            return
        if msg_type == "mic_control":
            enabled = bool(data.get("enabled", True))
            silent = bool(data.get("silent", False))
            self._mic_enabled = enabled
            self.send_mic_state(enabled)
            if self.on_mic_control:
                self.on_mic_control(enabled, silent)
            return
        if msg_type == "confirm_response":
            confirm_id = str(data.get("id") or "")
            approved = bool(data.get("approved", False))
            ok = False
            if self.on_confirm and confirm_id:
                try:
                    ok = bool(self.on_confirm(confirm_id, approved))
                except Exception:
                    ok = False
            self._emit({
                "type": "confirm_ack",
                "id": confirm_id,
                "approved": approved,
                "ok": ok,
            })
            self.send_command_center()
            return
        if msg_type == "refresh_command_center":
            self.send_command_center()

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
        self.send_command_center()

    def send_telemetry(self, data: dict[str, Any]) -> None:
        self._emit({"type": "telemetry", "data": data})

    def send_command_center(self, data: Optional[dict[str, Any]] = None) -> None:
        payload = data if data is not None else self._snapshot()
        self._emit({"type": "command_center", "data": payload})

    def send_permission_notice(
        self,
        *,
        level: int,
        tool: str,
        detail: str = "",
    ) -> None:
        self._emit({
            "type": "permission_notice",
            "level": level,
            "tool": tool,
            "detail": detail,
        })

    def send_confirm_request(self, payload: dict[str, Any]) -> None:
        self._emit({"type": "confirm_request", "data": payload})

    def send_plan_progress(self, payload: dict[str, Any]) -> None:
        """Stream plan step progress to HUD clients (U-01)."""
        self._emit({"type": "plan_progress", "data": payload})

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
        elapsed = 0.0
        while not self._telemetry_stop.is_set():
            self.send_telemetry(get_telemetry(model))
            elapsed += self.telemetry_interval
            if elapsed >= self.command_center_interval:
                self.send_command_center()
                elapsed = 0.0
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
