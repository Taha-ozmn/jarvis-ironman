"""Fast-path routing — weather and quick lookup must not hit Cursor brain."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.app import JarvisOS
from core.command_router import CommandRouter
from core.context_manager import ContextManager
from core.open_target import (
    extract_open_target,
    extract_site_url,
    has_open_verb,
    normalize_open_target,
)
from memory.extractor import is_name_preference_command, parse_name_preference
from memory.preference import apply_language_preference, parse_language_preference
from system.hud_stats import format_hud_model, get_telemetry, _memory_used
from voice.speech_clean import speak_safe_tr


class BrowserTabsRouteTests(unittest.TestCase):
    """«açık sekme» must list tabs — never open_app with target «ık»."""

    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_acik_sekme_not_open_app(self) -> None:
        self.assertIsNone(extract_open_target("açık sekme"))
        self.assertFalse(has_open_verb("açık sekme"))
        match = self.router.route("iki tane açık sekme var Ne var onlarda")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "browser.list_tabs")

    def test_diger_sekmelerde(self) -> None:
        match = self.router.route("diğer sekmelerde ne açık")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "browser.list_tabs")

    def test_sekmelerde_ne_var(self) -> None:
        match = self.router.route("sekmelerde ne var")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "browser.list_tabs")

    def test_chrome_ac_still_works(self) -> None:
        self.assertTrue(has_open_verb("chrome aç"))
        match = self.router.route("chrome aç")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "system.open_app")
        self.assertEqual(match.request.arguments["name"].lower(), "chrome")

    def test_acsana_open_verb(self) -> None:
        self.assertEqual(extract_open_target("spotify açsana"), "spotify")

    def test_speak_safe_strips_english_open_error(self) -> None:
        self.assertEqual(speak_safe_tr("Could not open ık"), "«ık» açılamadı.")
        self.assertNotIn("Could not", speak_safe_tr("Could not open chrome"))


class WeatherFastPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_router_hava_durumu(self) -> None:
        match = self.router.route("hava durumu")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "weather.current")

    def test_router_hava_nasil(self) -> None:
        match = self.router.route("bugün hava nasıl")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "weather.current")

    def test_os_handles_weather_without_brain(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {
                "jarvis": {"user_name": "sir", "language": "tr-TR"},
                "jarvis2": {"db_path": "data/fast.db", "max_permission_level": 1},
            },
            root=root,
        )
        try:
            with patch(
                "tools.weather_tools.fetch_weather",
                return_value="Istanbul: Sunny, 28°C, humidity 55%.",
            ):
                reply = os_core.try_handle_command("hava durumu")
            self.assertIsNotNone(reply)
            self.assertIn("28", reply or "")
            self.assertIn("Istanbul", reply or "")
        finally:
            os_core.close()
            tmp.cleanup()

    def test_os_weather_with_city(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {"jarvis2": {"db_path": "data/fast2.db", "max_permission_level": 1}},
            root=root,
        )
        try:
            with patch("tools.weather_tools.fetch_weather") as mock_fetch:
                mock_fetch.return_value = "Ankara: Cloudy, 22°C."
                reply = os_core.try_handle_command("Ankara hava durumu")
            self.assertIsNotNone(reply)
            mock_fetch.assert_called_once()
            call_loc = mock_fetch.call_args[0][0]
            self.assertIn("Ankara", call_loc)
        finally:
            os_core.close()
            tmp.cleanup()


class PreferenceFastPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_parse_turkish_name_and_address(self) -> None:
        parsed = parse_name_preference("Benim ismim Taha bana Taha diye hitap et")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], "Taha")

    def test_router_catches_tr_preference(self) -> None:
        cmd = "Benim ismim Taha bana Taha diye hitap et"
        self.assertTrue(is_name_preference_command(cmd))
        match = self.router.route(cmd)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "preference.apply")

    def test_os_handles_preference_without_brain(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {
                "jarvis": {"user_name": "sir", "language": "tr-TR"},
                "jarvis2": {"db_path": "data/pref.db", "max_permission_level": 1},
            },
            root=root,
        )
        try:
            reply = os_core.try_handle_command("Benim ismim Taha bana Taha diye hitap et")
            self.assertIsNotNone(reply)
            self.assertIn("Taha", reply or "")
            self.assertEqual(os_core.context.current.user_name, "Taha")
        finally:
            os_core.close()
            tmp.cleanup()


class HudModelLabelTests(unittest.TestCase):
    def test_format_cursor_provider(self) -> None:
        label = format_hud_model(
            {"llm_provider": "cursor", "model": "composer-2.5"},
            brain_model="composer-2.5",
            brain_ready=True,
        )
        self.assertIn("Cursor", label)
        self.assertIn("composer-2.5", label)

    def test_telemetry_uses_provider_label(self) -> None:
        payload = get_telemetry(
            {"llm_provider": "cursor", "model": "composer-2.5"},
            brain_model="composer-2.5",
            brain_ready=True,
        )
        self.assertIn("Cursor", payload["model"])
        self.assertEqual(payload["cursor"], "BRIDGE OK")
        self.assertEqual(payload["neural"], "ONLINE")


class OpenTargetTests(unittest.TestCase):
    def test_chrome_acar_misin(self) -> None:
        target = extract_open_target("chrome açar mısın")
        self.assertEqual(target.lower(), "chrome")

    def test_cift_gp_alias(self) -> None:
        self.assertEqual(normalize_open_target("çift gp"), "chrome")

    def test_router_chrome_tr(self) -> None:
        match = CommandRouter().route("chrome'u açar mısın")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "system.open_app")
        self.assertEqual(match.request.arguments["name"].lower(), "chrome")

    def test_chrome_ac_lutfen(self) -> None:
        target = extract_open_target("Chrome aç lütfen")
        self.assertEqual(target.lower(), "chrome")
        match = CommandRouter().route("Chrome aç lütfen")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "system.open_app")
        self.assertEqual(match.request.arguments["name"].lower(), "chrome")

    def test_lutfen_chrome_ac(self) -> None:
        match = CommandRouter().route("lütfen chrome aç")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "system.open_app")
        self.assertEqual(match.request.arguments["name"].lower(), "chrome")

    def test_terminal_ac_is_open_not_shell(self) -> None:
        match = CommandRouter().route("terminal aç")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "system.open_app")
        self.assertEqual(match.request.arguments["name"].lower(), "terminal")

    def test_spotify_kapat(self) -> None:
        match = CommandRouter().route("spotify kapat")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "system.close_app")
        self.assertEqual(match.request.arguments["name"].lower(), "spotify")

    def test_google_ara_query(self) -> None:
        match = CommandRouter().route("google ara python")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "system.web_search")
        self.assertEqual(match.request.arguments["query"].lower(), "python")


class YouTubeRoutingTests(unittest.TestCase):
    """YouTube must open via browser.open_url — never Cursor chat."""

    YT_URL = "https://www.youtube.com"

    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_extract_site_youtube_ac(self) -> None:
        self.assertEqual(extract_site_url("youtube aç"), self.YT_URL)
        self.assertEqual(extract_site_url("youtube'dan video aç"), self.YT_URL)
        self.assertEqual(extract_site_url("o zaman youtube aç"), self.YT_URL)
        self.assertEqual(extract_open_target("youtube aç"), "youtube")

    def test_router_youtube_ac(self) -> None:
        match = self.router.route("youtube aç")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "browser.open_url")
        self.assertEqual(match.request.arguments["url"], self.YT_URL)

    def test_router_youtube_dan_video(self) -> None:
        match = self.router.route("youtube'dan video aç")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "browser.open_url")
        self.assertEqual(match.request.arguments["url"], self.YT_URL)

    def test_router_o_zaman_youtube_ac(self) -> None:
        match = self.router.route("o zaman youtube aç")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "browser.open_url")
        self.assertEqual(match.request.arguments["url"], self.YT_URL)

    def test_followup_after_chrome_video(self) -> None:
        ctx = ContextManager()
        ctx.record_open_action(kind="open_app", name="chrome")
        resolved = ctx.resolve_followup("orada video aç")
        self.assertEqual(resolved.lower(), "youtube aç")
        match = self.router.route(resolved)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "browser.open_url")
        self.assertEqual(match.request.arguments["url"], self.YT_URL)

    def test_followup_o_zaman_youtube_after_chrome(self) -> None:
        ctx = ContextManager()
        ctx.record_open_action(kind="open_app", name="chrome")
        resolved = ctx.resolve_followup("o zaman youtube aç")
        match = self.router.route(resolved)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "browser.open_url")
        self.assertEqual(match.request.arguments["url"], self.YT_URL)

    def test_os_handles_youtube_without_brain(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {
                "jarvis": {"user_name": "Taha", "language": "tr-TR"},
                "jarvis2": {"db_path": "data/yt.db", "max_permission_level": 1},
            },
            root=root,
        )
        try:
            with patch(
                "tools.browser_tools.subprocess.run",
            ) as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                reply = os_core.try_handle_command("youtube aç")
            self.assertIsNotNone(reply)
            self.assertIn("youtube", (reply or "").lower())
            mock_run.assert_called()
            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], "open")
            self.assertIn("youtube.com", args[1])
        finally:
            os_core.close()
            tmp.cleanup()


class LanguageFastPathTests(unittest.TestCase):
    def test_parse_turkish_switch_ignored_for_tts(self) -> None:
        self.assertIsNone(parse_language_preference("Türkçe konuşur musun benimle"))

    def test_english_switch_locks_ryan(self) -> None:
        from memory.preference import (
            LOCKED_REPLY_LOCALE,
            wants_english_replies,
        )

        self.assertTrue(wants_english_replies("speak english"))
        self.assertEqual(parse_language_preference("speak english"), LOCKED_REPLY_LOCALE)
        ack = apply_language_preference("speak english please")
        self.assertEqual(ack, "Understood — I'll reply in English from now on.")
        self.assertNotIn("efendim", ack.lower())

    def test_turkish_request_does_not_force_tr_replies(self) -> None:
        from memory.preference import ENGLISH_REPLY_LOCK_ACK

        class FakeBrain:
            language = "en-GB"
            reply_language = "en"
            user_name = "Taha"
            address = "Taha"

            def set_language(self, lang: str) -> None:
                self.language = "en-GB"
                self.reply_language = "en"
                self.address = self.user_name or "sir"

        class FakeSpeaker:
            language = "en-GB"
            voice = "en-GB-RyanNeural"

        brain = FakeBrain()
        speaker = FakeSpeaker()
        cfg = {
            "jarvis": {"voice": "en-GB-RyanNeural"},
            "voice": {"english_voice": "en-GB-RyanNeural"},
        }
        ack = apply_language_preference(
            "Türkçe konuş", brain=brain, config=cfg, speaker=speaker
        )
        self.assertEqual(ack, ENGLISH_REPLY_LOCK_ACK)
        self.assertEqual(brain.reply_language, "en")
        self.assertEqual(speaker.language, "en-GB")
        self.assertTrue(str(speaker.voice).startswith("en-"))

    def test_apply_language_no_agent(self) -> None:
        class FakeBrain:
            language = "en-GB"
            reply_language = "en"
            user_name = "Taha"
            address = "Taha"

            def set_language(self, lang: str) -> None:
                self.language = "en-GB"
                self.reply_language = "en"
                self.address = self.user_name or "sir"

        class FakeSpeaker:
            language = "en-GB"
            voice = "en-GB-RyanNeural"

        brain = FakeBrain()
        speaker = FakeSpeaker()
        cfg = {
            "jarvis": {"voice": "en-GB-RyanNeural"},
            "voice": {
                "english_voice": "en-GB-RyanNeural",
            },
        }
        ack = apply_language_preference(
            "speak english", brain=brain, config=cfg, speaker=speaker
        )
        self.assertIsNotNone(ack)
        self.assertEqual(brain.reply_language, "en")
        self.assertEqual(speaker.language, "en-GB")
        self.assertTrue(str(speaker.voice).startswith("en-"))
        self.assertEqual(cfg["jarvis"]["language"], "en-GB")
        self.assertNotIn("efendim", (ack or "").lower())

    def test_turkish_stt_does_not_set_emel(self) -> None:
        from memory.preference import looks_turkish
        from voice.speaker import DEFAULT_ENGLISH_VOICE, resolve_edge_voice

        self.assertTrue(looks_turkish("Chrome aç"))
        voice = resolve_edge_voice("en-GB", english_voice=DEFAULT_ENGLISH_VOICE)
        self.assertEqual(voice, DEFAULT_ENGLISH_VOICE)
        self.assertFalse(voice.startswith("tr-"))


class HudMemoryTests(unittest.TestCase):
    def test_memory_not_zero_on_macos(self) -> None:
        mem = _memory_used()
        self.assertGreater(mem, 0)
        self.assertLessEqual(mem, 99)


class BrainTimeoutTests(unittest.TestCase):
    def test_timeout_messages_english_no_efendim(self) -> None:
        from brain.cursor_brain import JarvisBrain

        brain = JarvisBrain(api_key="test", language="en-GB", reply_language="en")
        soft = brain._soft_timeout_message()
        self.assertTrue(soft)
        self.assertNotIn("efendim", soft.lower())
        self.assertNotIn("hâlâ", soft.lower())
        fail = brain._timeout_fail_message()
        self.assertNotIn("efendim", fail.lower())
        self.assertNotIn("efendim", brain._background_timeout_message().lower())


class NarratorNoEfendimTests(unittest.TestCase):
    def test_acks_and_greetings_have_no_efendim(self) -> None:
        from voice.narrator import JarvisNarrator

        n = JarvisNarrator()
        for s in n.GENERIC_ACKS + n.WORK_UPDATES:
            self.assertNotIn("efendim", s.lower())
        for hour_fn in (n.time_greeting,):
            self.assertNotIn("efendim", hour_fn().lower())


class ProcessCommandOpenAppTests(unittest.TestCase):
    def test_chrome_ac_returns_tool_result(self) -> None:
        """process_command must execute open_app, not fall through to chat."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        from core.app import JarvisOS

        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {
                "jarvis": {"user_name": "Taha", "language": "tr-TR"},
                "jarvis2": {"db_path": "data/open.db", "max_permission_level": 3},
            },
            root=root,
        )
        try:
            with patch.object(
                os_core.macos,
                "_open_app",
                return_value="Google Chrome is open.",
            ) as mock_open:
                reply = os_core.try_handle_command("chrome aç")
            self.assertIsNotNone(reply)
            self.assertIn("open", (reply or "").lower())
            self.assertNotIn("efendim", (reply or "").lower())
            mock_open.assert_called()
        finally:
            os_core.close()
            tmp.cleanup()

    def test_router_chrome_ac_simple(self) -> None:
        match = CommandRouter().route("chrome aç")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "system.open_app")
        self.assertEqual(match.request.arguments["name"].lower(), "chrome")


if __name__ == "__main__":
    unittest.main()
