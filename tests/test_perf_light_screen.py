"""Performance / UX: system.health route, efendim strip, screen watcher."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.app import JarvisOS
from core.command_router import CommandRouter
from core.context_manager import ContextManager
from system.screen_watcher import ScreenWatcher
from voice.speech_clean import normalize_for_dedupe, strip_efendim


class SystemHealthRouteTests(unittest.TestCase):
    def test_sistem_iyi_mi_routes_local(self) -> None:
        m = CommandRouter().route("sistem iyi mi")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "system.health")

    def test_sistem_durumu_routes_local(self) -> None:
        m = CommandRouter().route("sistem durumunu kontrol et")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "system.health")

    def test_system_status_routes_local(self) -> None:
        m = CommandRouter().route("system status")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "system.health")

    def test_diagnostics_still_core(self) -> None:
        m = CommandRouter().route("self diagnostics")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "diagnostics.health")

    def test_system_health_tool_short_english(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {
                    "jarvis": {"user_name": "Taha", "language": "en-GB", "reply_language": "en"},
                    "jarvis2": {"db_path": "data/ph.db", "max_permission_level": 2},
                    "screen": {"always_watch": False},
                },
                root=Path(tmp),
            )
            from core.execution_engine import ExecutionRequest

            result = os_core.execution.execute(ExecutionRequest("system.health", {}))
            self.assertTrue(result.ok, result.error)
            text = str(result.data)
            self.assertRegex(text, r"CPU \d+%")
            self.assertRegex(text, r"RAM \d+%")
            self.assertNotIn("Cursor", text)
            self.assertNotIn("efendim", text.lower())
            self.assertNotIn("felsefe", text.lower())
            os_core.close()


class EfendimStripTests(unittest.TestCase):
    def test_strip_mid_sentence(self) -> None:
        self.assertEqual(strip_efendim("Tamamdır, efendim."), "Tamamdır.")
        self.assertEqual(strip_efendim("Efendim, bakıyorum."), "bakıyorum.")
        self.assertNotIn("efendim", strip_efendim("Sistem iyi, efendim").lower())

    def test_dedupe_norm(self) -> None:
        a = normalize_for_dedupe("Bakıyorum, efendim.")
        b = normalize_for_dedupe("Bakıyorum.")
        self.assertEqual(a, b)

    def test_speaker_strips_and_dedupes(self) -> None:
        from voice.speaker import VoiceSpeaker

        spoken: list[str] = []
        speaker = VoiceSpeaker.__new__(VoiceSpeaker)
        speaker.language = "tr-TR"
        speaker.engine = "native"
        speaker.edge_voice = "tr-TR-EmelNeural"
        speaker.native_voice = "Yelda"
        speaker.rate = "-5%"
        speaker.pitch = "-2Hz"
        speaker.volume = "+0%"
        speaker.native_rate = 165
        speaker.edge_timeout = 25
        speaker.edge_retries = 0
        speaker.cinematic = False
        speaker.native_first = True
        speaker._last_spoken = ""
        speaker._last_spoken_norm = ""
        speaker._queue = __import__("queue").Queue()
        speaker._speaking = __import__("threading").Event()
        speaker._on_busy_change = None
        speaker._loop = None
        speaker._ready = __import__("threading").Event()
        speaker._ready.set()
        speaker._edge_ok = False
        speaker._fallback_warned_at = 0.0
        speaker._last_edge_ok_at = 0.0

        # Queue only — don't start worker
        original_put = speaker._queue.put

        def _capture(item):
            if item is not None:
                spoken.append(item)
            original_put(item)

        speaker._queue.put = _capture  # type: ignore[method-assign]
        speaker.say("Tamamdır, efendim.")
        speaker.say("Tamamdır.")
        self.assertEqual(spoken, ["Tamamdır."])


class ScreenWatcherContextTests(unittest.TestCase):
    def test_watcher_updates_context(self) -> None:
        ctx = ContextManager()
        calls = {"n": 0}

        def fake_frontmost():
            calls["n"] += 1
            return {"name": "Cursor", "bundle": "com.todesktop.cursor", "title": "main.py"}

        watcher = ScreenWatcher(
            enabled=True,
            poll_interval_sec=6,
            screenshot_on_change=False,
            set_extra=ctx.set_extra,
            get_extra=ctx.get_extra,
            frontmost_fn=fake_frontmost,
            capture_fn=lambda p: (False, "skip"),
        )
        out = watcher.poll_once()
        self.assertTrue(out.get("ok"))
        stored = ctx.get_extra("current_screen_context")
        self.assertIsInstance(stored, dict)
        self.assertEqual(stored.get("app"), "Cursor")
        self.assertIn("Cursor", stored.get("summary", ""))
        self.assertEqual(calls["n"], 1)

    def test_screen_describe_uses_cache(self) -> None:
        from tools.screen_tools import ScreenDescribeTool

        tool = ScreenDescribeTool(
            context_getter=lambda: {
                "ok": True,
                "app": "Safari",
                "title": "News",
                "summary": "Ön planda Safari («News»).",
                "updated_at": __import__("time").time(),
            },
            cache_max_age_sec=30,
        )
        result = tool.run({})
        self.assertTrue(result.ok)
        self.assertIn("Safari", str(result.data))


class HostCpuMetricsTests(unittest.TestCase):
    def test_cpu_not_raw_loadavg_times_100(self) -> None:
        """HUD must use busy% / cores — not loadavg*100 as CPU%."""
        from system import host_metrics as hm

        with patch.object(hm.os, "getloadavg", return_value=(0.99, 0.5, 0.3)):
            with patch.object(hm.os, "cpu_count", return_value=8):
                # Force ps path to fail → fallback loadavg/cores
                with patch.object(
                    hm.subprocess,
                    "run",
                    side_effect=FileNotFoundError("ps"),
                ):
                    pct = hm._cpu_pct()
        # load 0.99 / 8 cores ≈ 12%, never 99%
        self.assertLessEqual(pct, 20)
        self.assertNotEqual(pct, 99)

    def test_cpu_from_ps_sum_divided_by_cores(self) -> None:
        from system import host_metrics as hm
        from unittest.mock import MagicMock

        fake = MagicMock()
        fake.stdout = "50.0\n50.0\n"  # 100% of one-core units
        with patch.object(hm.subprocess, "run", return_value=fake):
            with patch.object(hm.os, "cpu_count", return_value=4):
                pct = hm._cpu_pct()
        self.assertEqual(pct, 25)  # 100/4


if __name__ == "__main__":
    unittest.main()
