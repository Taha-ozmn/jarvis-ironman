"""Music intent, screen routing, and no-false-success verification."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.app import JarvisOS
from core.command_router import CommandRouter
from core.execution_engine import ExecutionEngine, ExecutionRequest
from core.open_target import extract_music_intent, youtube_search_url
from core.decision_music import decide_music_play, is_vague_music_query
from core.verification import should_verify, verify_tool_result
from security.audit import AuditLog
from security.confirmation import ConfirmationGate
from security.permissions import PermissionGate, PermissionLevel
from system.macos import MacOSController
from tools.base import ToolResult
from tools.media_tools import MediaPlayTool
from tools.registry import ToolRegistry
from tools.screen_tools import ScreenDescribeTool


class MusicDecisionTests(unittest.TestCase):
    def test_vague_guzel_bir_picks_track(self) -> None:
        d = decide_music_play("güzel bir")
        self.assertTrue(d.autonomous)
        self.assertIn("Teoman", d.search_query)
        self.assertTrue(is_vague_music_query("güzel bir"))

    def test_specific_artist_not_overridden(self) -> None:
        d = decide_music_play("Koray Avcı")
        self.assertFalse(d.autonomous)
        self.assertIn("Koray", d.search_query)

    def test_bare_sarki_ac_intent(self) -> None:
        intent = extract_music_intent("şarkı aç")
        self.assertIsNotNone(intent)

    def test_koray_avci_muzigi_ac(self) -> None:
        intent = extract_music_intent("Koray Avcı müziği aç")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertIn("koray", intent.query.lower())
        self.assertIn("avc", intent.query.lower())
        url = youtube_search_url(intent.query)
        self.assertIn("search_query=", url)
        self.assertIn("koray", url.lower())
        self.assertIn("avc", url.lower())
        self.assertNotEqual(url.rstrip("/"), "https://www.youtube.com")

    def test_play_english(self) -> None:
        intent = extract_music_intent("play Daft Punk")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertIn("daft", intent.query.lower())

    def test_spotify_search(self) -> None:
        intent = extract_music_intent("spotify'da Sezen Aksu aç")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.service, "spotify")
        self.assertIn("sezen", intent.query.lower())

    def test_bare_youtube_not_music(self) -> None:
        self.assertIsNone(extract_music_intent("youtube aç"))
        self.assertIsNone(extract_music_intent("youtube'dan video aç"))


class MusicRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_router_music_to_media_play(self) -> None:
        match = self.router.route("Koray Avcı müziği aç")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "media.play")
        query = match.request.arguments["query"]
        self.assertIn("koray", query.lower())
        url = youtube_search_url(query)
        self.assertIn("search_query=", url)
        self.assertRegex(url.lower(), r"koray")

    def test_sarki_dinle(self) -> None:
        match = self.router.route("Tarkan şarkısı dinle")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "media.play")


class MediaFalsePositiveTests(unittest.TestCase):
    def test_turkish_question_does_not_open_spotify(self) -> None:
        controller = MacOSController()
        result = controller.try_media(
            "Iron Man filmindeki gibi hologram ile çalışabilir miyiz?"
        )
        self.assertIsNone(result)

    def test_long_hologram_question_does_not_open_spotify(self) -> None:
        controller = MacOSController()
        result = controller.try_media(
            "Iron Man filmindeki gibi hologram ile ışık efekti yapabilir miyiz?"
        )
        self.assertIsNone(result)


class ScreenRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_ekranimi_goruyor_musun(self) -> None:
        match = self.router.route("ekranımı görüyor musun")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "screen.describe")

    def test_ekranda_ne_var(self) -> None:
        match = self.router.route("ekranda ne var")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "screen.describe")


class ScreenDescribeEnglishTests(unittest.TestCase):
    def test_can_see_message(self) -> None:
        with patch(
            "tools.screen_tools.capture_screen",
            return_value=(True, "/tmp/x.png"),
        ), patch(
            "tools.screen_tools.frontmost_app_info",
            return_value={"name": "Safari", "bundle": "com.apple.Safari", "title": "Home"},
        ), patch(
            "tools.screen_tools.ocr_image",
            return_value=None,
        ):
            result = ScreenDescribeTool().run({})
        self.assertTrue(result.ok)
        data = str(result.data)
        self.assertIn("Yes, I can see your screen", data)
        self.assertIn("Safari", data)

    def test_tcc_denied_honest(self) -> None:
        with patch(
            "tools.screen_tools.capture_screen",
            return_value=(False, "not authorized to capture"),
        ), patch(
            "tools.screen_tools.frontmost_app_info",
            return_value=None,
        ):
            result = ScreenDescribeTool().run({})
        self.assertFalse(result.ok)
        self.assertIn("Screen Recording", result.error or "")


class NoFalseSuccessTests(unittest.TestCase):
    def test_media_play_fails_when_open_fails(self) -> None:
        tool = MediaPlayTool()
        with patch(
            "tools.media_tools._open_url",
            return_value=(False, "open failed"),
        ), patch(
            "tools.media_tools._try_playwright_first_video",
            return_value=False,
        ):
            result = tool.run({"query": "Koray Avcı"})
        self.assertFalse(result.ok)
        self.assertNotIn("açıldı", (result.data or "").lower())

    def test_should_verify_open_tools(self) -> None:
        self.assertTrue(should_verify("browser.open_url"))
        self.assertTrue(should_verify("media.play"))
        self.assertTrue(should_verify("system.open_app"))

    def test_verify_rejects_empty_open_success(self) -> None:
        outcome = verify_tool_result(
            "browser.open_url",
            {"url": "https://www.youtube.com/results?search_query=x"},
            ToolResult(ok=True, data=""),
        )
        self.assertFalse(outcome.ok)

    def test_engine_verify_on_execute(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            from memory.database import Database

            db = Database(Path(tmp.name) / "t.db")
            db.migrate()
            registry = ToolRegistry()

            class FakeOpen:
                name = "browser.open_url"
                permission_level = PermissionLevel.LOCAL
                input_schema = {"url": {"type": "str", "required": True}}

                def run(self, arguments):
                    return ToolResult(ok=True, data="")  # empty → verify fail

            registry.register(FakeOpen())
            engine = ExecutionEngine(
                registry,
                PermissionGate(PermissionLevel.SYSTEM),
                AuditLog(db),
                MagicMock(),
                ConfirmationGate(auto_approve=True),
            )
            result = engine.execute(
                ExecutionRequest("browser.open_url", {"url": "https://example.com"})
            )
            self.assertFalse(result.ok)
            self.assertIn("Verification failed", result.error or "")
        finally:
            tmp.cleanup()

    def test_os_music_route_opens_search(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {
                "jarvis": {"user_name": "Taha", "language": "tr-TR"},
                "jarvis2": {"db_path": "data/m.db", "max_permission_level": 1},
            },
            root=root,
        )
        try:
            with patch("tools.media_tools._open_url", return_value=(True, "")), patch(
                "tools.media_tools._try_playwright_first_video",
                return_value=False,
            ):
                reply = os_core.try_handle_command("Koray Avcı müziği aç")
            self.assertIsNotNone(reply)
            self.assertIn("koray", (reply or "").lower())
            self.assertIn("youtube", (reply or "").lower())
            self.assertNotIn("henüz ekran", (reply or "").lower())
        finally:
            os_core.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
