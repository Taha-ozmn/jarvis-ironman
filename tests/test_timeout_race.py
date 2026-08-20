"""Soft/hard timeout race + latency stats tests."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.latency_stats import LatencyStats, normalize_intent


class LatencyStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "latency.json"
        self.stats = LatencyStats(self.path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_normalize_intent(self) -> None:
        self.assertEqual(normalize_intent("Hey Jarvis chrome aç"), "chrome aç")
        self.assertEqual(normalize_intent(""), "unknown")

    def test_record_and_prefer_tool(self) -> None:
        self.stats.record("chrome aç", "tool", 120.0, True)
        self.stats.record("chrome aç", "cursor", 8000.0, True)
        self.assertTrue(self.stats.prefer_tool("chrome aç"))
        self.assertTrue(self.path.exists())
        recent = self.stats.recent(5)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[-1]["path"], "cursor")

    def test_suggest_soft_timeout_bumps_for_slow_cursor(self) -> None:
        for ms in (25_000, 30_000, 28_000):
            self.stats.record("uzun soru", "cursor", ms, True)
        suggested = self.stats.suggest_soft_timeout("uzun soru", 20.0)
        self.assertGreater(suggested, 20.0)
        self.assertLessEqual(suggested, 40.0)


class SoftHardTimeoutRaceTests(unittest.TestCase):
    """Slow think completes after soft — must NOT speak hard timeout."""

    def _make_brain(self, soft: float = 0.6, hard: float = 3.0):
        from brain.cursor_brain import JarvisBrain

        brain = JarvisBrain(
            api_key="test",
            language="en-GB",
            reply_language="en",
            soft_timeout_sec=soft,
            hard_timeout_sec=hard,
            think_timeout=soft,
            narrate=True,
            work_updates=True,  # progress speech requires this
            background_on_timeout=False,
        )
        brain._ready.set()
        brain._agent = MagicMock()
        return brain

    def test_soft_then_success_no_hard_timeout(self) -> None:
        brain = self._make_brain(soft=0.6, hard=3.0)
        spoken: list[str] = []

        def speak(msg: str) -> None:
            spoken.append(msg)

        def slow_think(user_message, speak_fn, complexity="simple", cancel=None):
            del user_message, complexity
            time.sleep(0.85)  # after soft (>=0.5 floor), before hard
            if cancel is not None and cancel.is_set():
                return ""
            answer = "Chrome is open."
            speak_fn(answer)
            return answer

        with patch.object(brain, "ensure_started"), patch.object(
            brain, "_execute_think", side_effect=slow_think
        ):
            result = brain.think_with_narration("chrome aç", speak)

        self.assertEqual(result, "Chrome is open.")
        self.assertIn(brain._soft_timeout_message(), spoken)
        self.assertEqual(spoken.count(brain._soft_timeout_message()), 1)
        self.assertNotIn(brain._timeout_fail_message(), spoken)
        self.assertIn("Chrome is open.", spoken)

    def test_hard_timeout_only_when_still_pending(self) -> None:
        brain = self._make_brain(soft=0.6, hard=1.3)
        spoken: list[str] = []

        def speak(msg: str) -> None:
            spoken.append(msg)

        def never_finishes(user_message, speak_fn, complexity="simple", cancel=None):
            del user_message, speak_fn, complexity
            # Block until cancel, then exit without speaking
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if cancel is not None and cancel.is_set():
                    return ""
                time.sleep(0.05)
            return "late"

        with patch.object(brain, "ensure_started"), patch.object(
            brain, "_execute_think", side_effect=never_finishes
        ):
            result = brain.think_with_narration("soru", speak)

        self.assertEqual(result, brain._timeout_fail_message())
        self.assertIn(brain._soft_timeout_message(), spoken)
        self.assertIn(brain._timeout_fail_message(), spoken)
        self.assertNotIn("üzgünüm", " ".join(spoken).lower())
        self.assertNotIn("efendim", " ".join(spoken).lower())

    def test_cancelled_late_result_does_not_speak(self) -> None:
        brain = self._make_brain(soft=0.6, hard=1.0)
        spoken: list[str] = []
        late_spoke = threading.Event()

        def speak(msg: str) -> None:
            spoken.append(msg)

        def finishes_after_cancel(user_message, speak_fn, complexity="simple", cancel=None):
            del user_message, complexity
            time.sleep(1.4)  # after hard cancel
            if cancel is not None and cancel.is_set():
                return "should-not-speak"
            speak_fn("LATE ANSWER")
            late_spoke.set()
            return "LATE ANSWER"

        with patch.object(brain, "ensure_started"), patch.object(
            brain, "_execute_think", side_effect=finishes_after_cancel
        ):
            result = brain.think_with_narration("soru", speak)

        time.sleep(0.8)
        self.assertEqual(result, brain._timeout_fail_message())
        self.assertNotIn("LATE ANSWER", spoken)
        self.assertFalse(late_spoke.is_set())

    def test_timeout_messages_english_no_efendim(self) -> None:
        brain = self._make_brain()
        soft = brain._soft_timeout_message()
        self.assertTrue(soft)
        self.assertIn("sir", soft.lower())
        self.assertNotIn("efendim", soft.lower())
        fail = brain._timeout_fail_message()
        self.assertIn("sir", fail.lower())
        self.assertNotIn("efendim", fail.lower())
        self.assertNotIn("üzgünüm", fail.lower())


if __name__ == "__main__":
    unittest.main()
