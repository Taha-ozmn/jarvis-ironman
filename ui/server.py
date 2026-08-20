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

from system.hud_stats import get_telemetry, make_telemetry_supplier
from core.rest_api import attach_rest_routes

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
        telemetry_supplier: Optional[Callable[[], dict[str, Any]]] = None,
        os_core: Any = None,
        command_handler: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self.port = port
        self.mic_config = mic_config or {}
        self.jarvis_config = jarvis_config or {}
        self.open_browser = open_browser
        self.desktop_mode = desktop_mode
        self.telemetry_interval = telemetry_interval
        self.command_center_interval = max(5.0, float(command_center_interval))
        self.data_provider = data_provider
        self.on_confirm = on_confirm
        self._telemetry_supplier = telemetry_supplier
        self.os_core = os_core
        self.command_handler = command_handler
        self.on_mic_control: Optional[Callable[[bool, bool], None]] = None
        self._mic_enabled = True
        self._listen_gate_blocked = False
        self._voice_accept_fn: Optional[Callable[[str], bool]] = None
        self._clients: set[web.WebSocketResponse] = set()
        self._command_queue: queue.Queue[str] = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._telemetry_stop = threading.Event()
        self._app = web.Application()
        self._app.router.add_get("/", self._index)
        self._app.router.add_get("/ws", self._websocket)
        self._app.router.add_get("/api/command-center", self._api_command_center)
        attach_rest_routes(
            self._app,
            os_core=os_core,
            command_fn=command_handler,
            state_fn=self._snapshot,
        )

    async def _index(self, request: web.Request) -> web.Response:
        html = (UI_DIR / "index.html").read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")

    async def _api_command_center(self, request: web.Request) -> web.Response:
        payload = self._snapshot()
        return web.json_response(payload)

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
                "self_listen_guard": self.mic_config.get("self_listen_guard", True),
                "post_tts_cooldown_ms": self.mic_config.get("post_tts_cooldown_ms", 220),
                "min_command_length": self.mic_config.get("min_command_length", 4),
                "utterance_debounce_ms": self.mic_config.get("utterance_debounce_ms", 1400),
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
            "data": self._build_telemetry(),
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
                # Drop STT that arrives while TTS/processing (self-listen guard)
                if self._listen_gate_blocked and self.mic_config.get("self_listen_guard", True):
                    accept = self._voice_accept_fn
                    if accept is None or not accept(text):
                        return
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

    def send_listen_gate(self, blocked: bool) -> None:
        """Hard mute browser/native STT while TTS is speaking."""
        self._listen_gate_blocked = bool(blocked)
        self._emit({
            "type": "listen_gate",
            "blocked": self._listen_gate_blocked,
            "self_listen_guard": self.mic_config.get("self_listen_guard", True),
        })

    def flush_pending_commands(self) -> None:
        """Discard queued STT transcripts (echo from own TTS)."""
        while True:
            try:
                self._command_queue.get_nowait()
            except queue.Empty:
                break

    def set_voice_accept_fn(self, fn: Optional[Callable[[str], bool]]) -> None:
        self._voice_accept_fn = fn

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
        # Throttle CC rebuild — full diagnostics are expensive
        now = time.monotonic()
        last = getattr(self, "_last_cc_push", 0.0)
        if now - last >= max(8.0, self.command_center_interval * 0.8):
            self._last_cc_push = now
            self.send_command_center()

    def _build_telemetry(self) -> dict[str, Any]:
        if self._telemetry_supplier is not None:
            try:
                return self._telemetry_supplier()
            except Exception:
                pass
        return get_telemetry(self.jarvis_config)

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
        elapsed = 0.0
        while not self._telemetry_stop.is_set():
            self.send_telemetry(self._build_telemetry())
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
