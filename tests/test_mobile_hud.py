"""Mobile HUD assets and server-side STT."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import FormData, web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

ROOT = Path(__file__).resolve().parent.parent
UI_DIR = ROOT / "ui"


class MobileAssetTests(unittest.TestCase):
    def test_mobile_shell_present(self) -> None:
        html = (UI_DIR / "mobile.html").read_text(encoding="utf-8")
        self.assertIn("J.A.R.V.I.S. Mobile", html)
        self.assertIn("HOLD", html)
        self.assertIn("speechSynthesis", html)
        self.assertIn("speak_audio", html)
        self.assertIn("playPhoneAudio", html)
        self.assertIn("scheduleRecognitionRestart", html)
        self.assertIn("ENABLE MICROPHONE", html)
        self.assertIn("isSecureContext", html)

    def test_pwa_files(self) -> None:
        self.assertTrue((UI_DIR / "manifest.webmanifest").is_file())
        self.assertTrue((UI_DIR / "sw.js").is_file())
        self.assertTrue((UI_DIR / "icons" / "icon-192.png").is_file())
        self.assertTrue((UI_DIR / "connect.html").is_file())


class HudTlsTests(unittest.TestCase):
    def test_tls_module_roundtrip(self) -> None:
        from ui import tls as hud_tls

        test_dir = ROOT / "data" / "test_hud_tls"
        with patch.object(hud_tls, "CERT_DIR", test_dir), patch.object(
            hud_tls, "CERT_FILE", test_dir / "jarvis-hud.crt"
        ), patch.object(hud_tls, "KEY_FILE", test_dir / "jarvis-hud.key"), patch.object(
            hud_tls, "META_FILE", test_dir / "san.json"
        ):
            if not hud_tls.tls_available():
                self.skipTest("openssl not available")
            cert, key = hud_tls.ensure_hud_tls_cert(force=True)
            self.assertTrue(cert.is_file())
            self.assertTrue(key.is_file())
            ctx = hud_tls.hud_ssl_context()
            self.assertIsNotNone(ctx)


class ConnectRouteTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        import socket

        def lan_ip() -> str | None:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.connect(("8.8.8.8", 80))
                    return sock.getsockname()[0]
            except OSError:
                return None

        app = web.Application()
        port = 8765

        def connect_payload() -> dict:
            ip = lan_ip()
            base = f"http://{ip}:{port}" if ip else f"http://127.0.0.1:{port}"
            return {
                "ok": True,
                "lan_ip": ip,
                "port": port,
                "hud_url": f"{base}/",
                "mobile_url": f"{base}/mobile",
                "connect_url": f"{base}/connect",
                "phone_reachable": bool(ip),
            }

        async def connect_page(_request: web.Request) -> web.Response:
            html = (UI_DIR / "connect.html").read_text(encoding="utf-8")
            return web.Response(text=html, content_type="text/html")

        async def api_connect(_request: web.Request) -> web.Response:
            return web.json_response(connect_payload())

        app.router.add_get("/connect", connect_page)
        app.router.add_get("/api/connect", api_connect)
        return app

    @unittest_run_loop
    async def test_connect_page(self) -> None:
        resp = await self.client.get("/connect")
        self.assertEqual(resp.status, 200)
        body = await resp.text()
        self.assertIn("Phone Link", body)

    @unittest_run_loop
    async def test_api_connect(self) -> None:
        resp = await self.client.get("/api/connect")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertTrue(payload["ok"])
        self.assertIn("/mobile", payload["mobile_url"])
        self.assertEqual(payload["port"], 8765)


class MobileTtsTest(unittest.TestCase):
    def test_synthesize_returns_bytes(self) -> None:
        from voice import mobile_tts

        fake = b"\x00" * 128
        with patch.object(mobile_tts, "asyncio") as mock_asyncio:
            mock_asyncio.run.return_value = fake
            out = mobile_tts.synthesize_mp3_bytes("Standing by, Taha.")
        self.assertEqual(out, fake)

    def test_empty_text_returns_none(self) -> None:
        from voice.mobile_tts import synthesize_mp3_bytes

        self.assertIsNone(synthesize_mp3_bytes("   "))


class MobileSttTest(unittest.TestCase):
    def test_rejects_tiny_payload(self) -> None:
        from voice.mobile_stt import transcribe_bytes

        self.assertIsNone(transcribe_bytes(b"tiny"))


class SttRouteTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        import voice.mobile_stt as mobile_stt

        app = web.Application()
        mic_config = {"listen_languages": ["tr-TR", "en-US"]}

        async def api_stt(request: web.Request) -> web.Response:
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
            languages = mic_config.get("listen_languages", ["tr-TR", "en-US"])
            text = await asyncio.to_thread(
                mobile_stt.transcribe_bytes,
                data,
                filename=filename,
                languages=tuple(languages),
            )
            if not text:
                return web.json_response({"ok": False, "error": "no transcript"})
            return web.json_response({"ok": True, "text": text.strip()})

        app.router.add_post("/api/stt", api_stt)
        return app

    @unittest_run_loop
    async def test_stt_missing_audio(self) -> None:
        resp = await self.client.post("/api/stt")
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_stt_transcribe(self) -> None:
        with patch("voice.mobile_stt.transcribe_bytes", return_value="open safari"):
            form = FormData()
            form.add_field(
                "audio",
                b"fake-audio-bytes-here-" + b"x" * 200,
                filename="test.webm",
                content_type="audio/webm",
            )
            resp = await self.client.post("/api/stt", data=form)
            self.assertEqual(resp.status, 200)
            payload = await resp.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["text"], "open safari")


if __name__ == "__main__":
    unittest.main()
