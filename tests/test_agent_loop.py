"""Agent loop cap + catastrophic block still holds under full autonomy."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.agent_loop import run_agent_loop
from core.planner import Plan, PlanStep
from voice.narrator import JarvisNarrator


class AgentLoopTests(unittest.TestCase):
    def test_empty_goal(self) -> None:
        os_core = MagicMock()
        self.assertIn("boş", run_agent_loop(os_core, "  "))

    def test_no_steps_honest(self) -> None:
        os_core = MagicMock()
        os_core.planner.create.return_value = Plan(goal="x", steps=[])
        os_core.deep_max_iterations = 3
        msg = run_agent_loop(os_core, "selam")
        self.assertIn("tek adımlık", msg)

    def test_retries_then_stops(self) -> None:
        os_core = MagicMock()
        plan = Plan(goal="fix", steps=[PlanStep("diagnostics.health", {})])
        os_core.planner.create.return_value = plan
        os_core.deep_max_iterations = 2
        fail = MagicMock(ok=False, speech="hata", stopped_reason="verify failed")
        os_core.execution.execute_plan.return_value = fail
        msg = run_agent_loop(os_core, "projeyi düzelt", max_iterations=2)
        self.assertEqual(os_core.execution.execute_plan.call_count, 2)
        self.assertTrue("tur" in msg.lower() or "hata" in msg.lower())

    def test_success_first_iter(self) -> None:
        os_core = MagicMock()
        plan = Plan(goal="ok", steps=[PlanStep("diagnostics.health", {})])
        os_core.planner.create.return_value = plan
        os_core.execution.execute_plan.return_value = MagicMock(
            ok=True, speech="Tamam."
        )
        msg = run_agent_loop(os_core, "sağlık", max_iterations=4)
        self.assertEqual(msg, "Tamam.")
        self.assertEqual(os_core.execution.execute_plan.call_count, 1)


class StreamPreviewHonestyTests(unittest.TestCase):
    def test_first_sentence_not_word_by_word(self) -> None:
        preview = JarvisNarrator.first_sentence(
            "Sistemler hazır. İkinci cümle burada duruyor."
        )
        self.assertEqual(preview, "Sistemler hazır.")
        self.assertTrue(
            JarvisNarrator.should_speak_more(
                preview,
                "Sistemler hazır. İkinci cümle daha uzun bir açıklama içeriyor.",
            )
        )


class PermissionsSpeechTests(unittest.TestCase):
    def test_screen_missing_explains_tcc(self) -> None:
        from system.permissions_check import format_permissions_speech

        msg = format_permissions_speech(
            {
                "passed": 0,
                "total_probeable": 1,
                "checks": [
                    {
                        "id": "screen_recording",
                        "label": "Screen Recording",
                        "ok": False,
                    }
                ],
            }
        )
        self.assertIn("EKSİK", msg)
        self.assertIn("Ekran Kaydı", msg)
        self.assertIn("Terminal", msg)


if __name__ == "__main__":
    unittest.main()
