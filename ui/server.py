"""Iron Man HUD — WebSocket status, command center, confirmations."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import queue
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

from aiohttp import web

from system.hud_stats import get_telemetry, make_telemetry_supplier
from core.rest_api import attach_rest_routes
from security.ui_auth import PairingTokenAuth
import voice.mobile_stt as mobile_stt
from ui import tls as hud_tls

UI_DIR = Path(__file__).resolve().parent
ICONS_DIR = UI_DIR / "icons"


def resolve_bind_host(host: str | None) -> str:
    """Map config host values to an aiohttp bind address."""
    raw = (host or "127.0.0.1").strip().lower()
    if raw in {"lan", "all", "any", "0.0.0.0"}:
        return "0.0.0.0"
    return raw or "127.0.0.1"


from ui.network import collect_ipv4_addresses as _collect_ipv4_addresses, primary_lan_ip as lan_ip

DataProvider = Callable[[], dict[str, Any]]
ConfirmHandler = Callable[[str, bool], bool]


@web.middleware
async def _security_headers_middleware(
    request: web.Request,
    handler: Callable[..., Any],
) -> web.StreamResponse:
    response = await handler(request)
    response.headers.setdefault("Permissions-Policy", "microphone=(self)")
    return response


class JarvisUI:
    def __init__(
        self,
        port: int = 8765,
        mic_config: dict[str, Any] | None = None,
        jarvis_config: dict[str, Any] | None = None,
        *,
        open_browser: bool = True,
        desktop_mode: bool = False,
        native_mic: bool = False,
        voice_identity_enabled: bool = False,
        telemetry_interval: float = 2.0,
        data_provider: Optional[DataProvider] = None,
        command_center_interval: float = 5.0,
        on_confirm: Optional[ConfirmHandler] = None,
        telemetry_supplier: Optional[Callable[[], dict[str, Any]]] = None,
        os_core: Any = None,
        command_handler: Optional[Callable[[str], Optional[str]]] = None,
        command_enqueue: Optional[Callable[[str], bool]] = None,
        host: str = "127.0.0.1",
    ) -> None:
        self.port = port
        self.bind_host = resolve_bind_host(host)
        self.mic_config = mic_config or {}
        self.jarvis_config = jarvis_config or {}
        self.open_browser = open_browser
        self.desktop_mode = desktop_mode
        self.native_mic = bool(native_mic)
        self.voice_identity_enabled = bool(voice_identity_enabled)
        self.telemetry_interval = telemetry_interval
        self.command_center_interval = max(5.0, float(command_center_interval))
        self.data_provider = data_provider
        self.on_confirm = on_confirm
        self._telemetry_supplier = telemetry_supplier
        self.os_core = os_core
        self.command_handler = command_handler
        self.command_enqueue = command_enqueue
        self.on_mic_control: Optional[Callable[[bool, bool], None]] = None
        self._mic_enabled = True
        self._listen_gate_blocked = False
        self._voice_accept_fn: Optional[Callable[[str], bool]] = None
        self._clients: set[web.WebSocketResponse] = set()
        self._mobile_clients: set[web.WebSocketResponse] = set()
        self._phone_tts_enabled = bool(
            self.jarvis_config.get("phone_tts", True)
            if isinstance(self.jarvis_config.get("phone_tts"), bool)
            else self.jarvis_config.get("phone_tts", {}).get("enabled", True)
        )
        queue_size = max(1, int(self.mic_config.get("command_queue_maxsize", 8)))
        self._command_queue: queue.Queue[str] = queue.Queue(maxsize=queue_size)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._telemetry_stop = threading.Event()
        ui_cfg = self.mic_config if isinstance(self.mic_config, dict) else {}
        tls_cfg = ui_cfg.get("tls")
        if isinstance(tls_cfg, dict):
            self._tls_enabled = bool(tls_cfg.get("enabled", True))
            self.tls_port = int(tls_cfg.get("port", self.port + 1))
        elif isinstance(tls_cfg, bool):
            self._tls_enabled = tls_cfg
            self.tls_port = int(ui_cfg.get("tls_port", self.port + 1))
        else:
            self._tls_enabled = self.bind_host == "0.0.0.0"
            self.tls_port = int(ui_cfg.get("tls_port", self.port + 1))
        if self._tls_enabled and not hud_tls.tls_available():
            self._tls_enabled = False
        pairing_state = ui_cfg.get("pairing_state_path", "data/ui_pairing.json")
        self._pairing = PairingTokenAuth(pairing_state)

        @web.middleware
        async def _pairing_middleware(
            request: web.Request,
            handler: Callable[..., Any],
        ) -> web.StreamResponse:
            public_paths = {
                "/",
                "/mobile",
                "/connect",
                "/api/connect",
                "/manifest.webmanifest",
                "/sw.js",
            }
            is_public = request.path in public_paths or request.path.startswith("/icons/")
            if is_public and (
                request.path != "/api/connect"
                or self._pairing.is_local_request(request)
            ):
                return await handler(request)
            if self._pairing.authorized(request) or self._pairing.is_local_request(request):
                return await handler(request)
            raise web.HTTPUnauthorized(
                text="JARVIS pairing token required.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        self._app = web.Application(
            middlewares=[_security_headers_middleware, _pairing_middleware]
        )
        self._app.router.add_get("/", self._index)
        self._app.router.add_get("/mobile", self._mobile)
        self._app.router.add_get("/connect", self._connect)
        self._app.router.add_get("/api/connect", self._api_connect)
        self._app.router.add_get("/api/qr.svg", self._api_qr)
        self._app.router.add_get("/manifest.webmanifest", self._manifest)
        self._app.router.add_get("/sw.js", self._service_worker)
        self._app.router.add_get("/icons/{name}", self._icon)
        self._app.router.add_post("/api/stt", self._api_stt)
        self._app.router.add_post("/api/tts", self._api_tts)
        self._app.router.add_get("/ws", self._websocket)
        self._app.router.add_get("/api/command-center", self._api_command_center)
        attach_rest_routes(
            self._app,
            os_core=os_core,
            command_fn=command_handler,
            enqueue_fn=command_enqueue,
            state_fn=self._snapshot,
        )

    async def _index(self, request: web.Request) -> web.Response:
        html = (UI_DIR / "index.html").read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")

    async def _mobile(self, request: web.Request) -> web.Response:
        html = (UI_DIR / "mobile.html").read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")

    async def _connect(self, request: web.Request) -> web.Response:
        html = (UI_DIR / "connect.html").read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")

    def _connect_payload(self) -> dict[str, Any]:
        ip = lan_ip()
        all_ips = _collect_ipv4_addresses()
        port = self.port
        tls_port = self.tls_port
        desktop_base = f"http://127.0.0.1:{port}"
        if ip:
            lan_http = f"http://{ip}:{port}"
            lan_https = f"https://{ip}:{tls_port}" if self._tls_enabled else lan_http
        else:
            lan_http = desktop_base
            lan_https = desktop_base.replace("http://", "https://") if self._tls_enabled else desktop_base
        mobile_base = lan_https if self._tls_enabled else (lan_http if ip else desktop_base)
        connect_base = lan_https if (self._tls_enabled and ip) else (lan_http if ip else desktop_base)
        pairing = quote(self._pairing.token, safe="")
        return {
            "ok": True,
            "lan_ip": ip,
            "all_ips": all_ips,
            "port": port,
            "tls_port": tls_port if self._tls_enabled else None,
            "tls_enabled": self._tls_enabled,
            "secure_context": self._tls_enabled,
            "hud_url": f"{desktop_base}/",
            "mobile_url": f"{mobile_base}/mobile?pairing={pairing}",
            "connect_url": f"{connect_base}/connect",
            "pairing": self._pairing.public_payload(),
            "phone_reachable": bool(ip and self.bind_host == "0.0.0.0"),
            "mic_note": (
                "iPhone microphone requires the HTTPS link below — trust the certificate once in Safari."
                if self._tls_enabled
                else "Use hold-to-talk; enable microphone when Safari prompts."
            ),
            "network_note": (
                "Same local network required — Wi‑Fi, iPhone USB, or Personal Hotspot all work."
            ),
        }

    async def _api_connect(self, request: web.Request) -> web.Response:
        if not self._pairing.is_local_request(request):
            raise web.HTTPUnauthorized(text="Open /connect on the Mac to pair a phone.")
        return web.json_response(self._connect_payload())

    async def _api_qr(self, request: web.Request) -> web.Response:
        """Render the stable phone-pairing URL as an SVG QR (local only).

        The QR encodes the pairing token, so it is only served to the Mac
        itself — never to a remote client. The pairing token persists across
        restarts, so the rendered QR stays identical.
        """
        if not self._pairing.is_local_request(request):
            raise web.HTTPUnauthorized(text="QR is available on the Mac only.")
        payload = self._connect_payload()
        target = str(payload.get("mobile_url") or "").strip()
        if not target:
            raise web.HTTPServiceUnavailable(text="LAN address unavailable.")
        try:
            import segno
        except ImportError:
            raise web.HTTPNotImplemented(
                text="QR unavailable — run: pip install -r requirements.txt",
            )
        buffer = io.BytesIO()
        segno.make(target, error="m").save(
            buffer,
            kind="svg",
            scale=6,
            border=2,
            dark="#0b1220",
            light="#e8f6ff",
        )
        return web.Response(
            body=buffer.getvalue(),
            content_type="image/svg+xml",
            headers={"Cache-Control": "no-store"},
        )

    async def _manifest(self, request: web.Request) -> web.Response:
        body = (UI_DIR / "manifest.webmanifest").read_text(encoding="utf-8")
        return web.Response(text=body, content_type="application/manifest+json")

    async def _service_worker(self, request: web.Request) -> web.Response:
        body = (UI_DIR / "sw.js").read_text(encoding="utf-8")
        return web.Response(text=body, content_type="application/javascript")

    async def _icon(self, request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if ".." in name or "/" in name:
            raise web.HTTPNotFound()
        path = ICONS_DIR / name
        if not path.is_file():
            raise web.HTTPNotFound()
        content_type = "image/png" if name.endswith(".png") else "application/octet-stream"
        return web.Response(body=path.read_bytes(), content_type=content_type)

    async def _api_stt(self, request: web.Request) -> web.Response:
        content_type = request.content_type or ""
        if not content_type.startswith("multipart/"):
            return web.json_response(
                {"ok": False, "error": "multipart audio required"},
                status=400,
            )
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "audio":
            return web.json_response({"ok": False, "error": "missing audio field"}, status=400)
        data = await field.read()
        filename = field.filename or "upload.webm"
        languages = self.mic_config.get(
            "listen_languages",
            [self.mic_config.get("listen_language", "tr-TR"), "en-US"],
        )
        text = await asyncio.to_thread(
            mobile_stt.transcribe_bytes,
            data,
            filename=filename,
            languages=tuple(languages),
        )
        if not text:
            return web.json_response({"ok": False, "error": "no transcript"})
        return web.json_response({"ok": True, "text": text.strip()})

    def _phone_voice(self) -> str:
        voice_cfg = self.jarvis_config.get("voice") or {}
        if isinstance(voice_cfg, dict):
            hint = voice_cfg.get("english_voice") or voice_cfg.get("voice")
            if hint:
                return str(hint)
        return str(
            self.jarvis_config.get("voice_hint")
            or self.jarvis_config.get("english_voice")
            or "en-GB-RyanNeural"
        )

    def _synthesize_phone_mp3(self, text: str) -> Optional[bytes]:
        from voice.mobile_tts import synthesize_mp3_bytes

        return synthesize_mp3_bytes(
            text,
            voice=self._phone_voice(),
            language=str(self.jarvis_config.get("language", "en-GB")),
        )

    def send_phone_speech(self, text: str) -> None:
        line = (text or "").strip()
        if not line or not self._phone_tts_enabled or not self._mobile_clients:
            return
        threading.Thread(
            target=self._phone_speech_worker,
            args=(line,),
            daemon=True,
            name="jarvis-phone-tts",
        ).start()

    def _phone_speech_worker(self, text: str) -> None:
        data = self._synthesize_phone_mp3(text)
        if not data:
            self._emit_mobile({"type": "speak_audio", "text": text, "fallback": True})
            return
        self._emit_mobile({
            "type": "speak_audio",
            "text": text,
            "format": "audio/mpeg",
            "audio_b64": base64.b64encode(data).decode("ascii"),
        })

    async def _api_tts(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        text = (body.get("text") or request.query.get("text") or "").strip()
        if not text:
            return web.json_response({"ok": False, "error": "text required"}, status=400)
        data = await asyncio.to_thread(self._synthesize_phone_mp3, text)
        if not data:
            return web.json_response({"ok": False, "error": "synthesis failed"}, status=502)
        return web.json_response({
            "ok": True,
            "text": text,
            "format": "audio/mpeg",
            "audio_b64": base64.b64encode(data).decode("ascii"),
        })

    @staticmethod
    def _is_mobile_client(request: web.Request) -> bool:
        if request.query.get("mobile") == "1":
            return True
        referer = (request.headers.get("Referer") or "").lower()
        if "/mobile" in referer:
            return True
        ua = (request.headers.get("User-Agent") or "").lower()
        return any(token in ua for token in ("iphone", "ipad", "ipod", "android"))

    async def _api_command_center(self, request: web.Request) -> web.Response:
        payload = self._snapshot()
        return web.json_response(payload)

    async def _websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        mobile = self._is_mobile_client(request)
        self._clients.add(ws)
        if mobile:
            self._mobile_clients.add(ws)
        await ws.send_str(json.dumps({
            "type": "config",
            "mobile": mobile,
            "phone_tts": self._phone_tts_enabled,
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
                "listen_languages": self.mic_config.get(
                    "listen_languages",
                    ["tr-TR", "en-US"],
                ),
            },
            "persona": self.jarvis_config.get("persona", "iron_man"),
            "user_name": self.jarvis_config.get("user_name", "sir"),
            "desktop": self.desktop_mode,
            "native_mic": self.native_mic or self.desktop_mode,
            "voice_identity": self.voice_identity_enabled,
            "telemetry_interval_ms": int(self.telemetry_interval * 1000),
            "command_center": True,
        }))
        # A client may connect after the one-time boot broadcast. Send the
        # terminal state so a stale boot overlay cannot block microphone UI.
        await ws.send_str(json.dumps({
            "type": "boot",
            "line": "JARVIS ONLINE",
            "progress": 100,
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
            self._mobile_clients.discard(ws)
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
                if self.voice_identity_enabled and data.get("source") != "text":
                    return
                # Drop STT that arrives while TTS/processing (self-listen guard)
                if self._listen_gate_blocked and self.mic_config.get("self_listen_guard", True):
                    accept = self._voice_accept_fn
                    if accept is None or not accept(text):
                        return
                self.broadcast("thinking", text)
                self._enqueue_command(text)
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

    def _enqueue_command(self, text: str) -> bool:
        try:
            self._command_queue.put_nowait(text)
            return True
        except queue.Full:
            detail = "Command queue full — command was not accepted."
            self.broadcast("listening", detail, queue_full=True)
            return False

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
        self.send_phone_speech(text)

    def send_response(self, command: str, response: str) -> None:
        self._emit({
            "type": "response",
            "command": command,
            "response": response,
            "status": "speaking",
            "detail": response,
        })
        self.send_phone_speech(response)
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

    def _emit_mobile(self, payload: dict[str, Any]) -> None:
        if not self._mobile_clients or not self._loop:
            return
        message = json.dumps(payload, ensure_ascii=False)
        for client in list(self._mobile_clients):
            try:
                asyncio.run_coroutine_threadsafe(client.send_str(message), self._loop)
            except Exception:
                self._mobile_clients.discard(client)
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
            site = web.TCPSite(runner, self.bind_host, self.port)
            await site.start()
            if self._tls_enabled:
                ssl_ctx = hud_tls.hud_ssl_context()
                tls_site = web.TCPSite(
                    runner,
                    self.bind_host,
                    self.tls_port,
                    ssl_context=ssl_ctx,
                )
                await tls_site.start()
            self._ready.set()
            if self.open_browser:
                webbrowser.open(f"http://127.0.0.1:{self.port}")

        self._loop.run_until_complete(_start())
        self._loop.run_forever()

    def wait_ready(self, timeout: float = 5.0) -> None:
        self._ready.wait(timeout=timeout)

    def stop(self) -> None:
        self._telemetry_stop.set()
