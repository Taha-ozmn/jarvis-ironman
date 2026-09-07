"""Tests for contextual timeout phrasing."""

from __future__ import annotations

import unittest

from core.timeout_responses import TimeoutResponses, classify_intent


class TimeoutResponsesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.responses = TimeoutResponses(user_name="Taha", use_name=True)

    def test_classify_open_app(self) -> None:
        self.assertEqual(classify_intent("chrome aç"), "open_app")

    def test_classify_build(self) -> None:
        self.assertEqual(classify_intent("build me a website"), "build")

    def test_soft_open_app_mentions_topic(self) -> None:
        msg = self.responses.soft("chrome aç")
        self.assertIn("chrome", msg.lower())
        self.assertNotIn("sir", msg.lower())

    def test_soft_uses_name_not_sir(self) -> None:
        msg = self.responses.soft("hello")
        self.assertIn("Taha", msg)

    def test_fail_does_not_start_retry_loop(self) -> None:
        msg = self.responses.fail("research quantum computing")
        self.assertIn("stopped", msg.lower())
        self.assertIn("saved", msg.lower())
        self.assertNotIn("shall I keep trying", msg.lower())
        self.assertNotIn("say 'continue'", msg.lower())

    def test_fail_open_app_actionable(self) -> None:
        msg = self.responses.fail("spotify aç")
        self.assertIn("spotify", msg.lower())
        self.assertIn("stopped", msg.lower())

    def test_background_no_sir(self) -> None:
        msg = self.responses.background("build full jarvis ui")
        self.assertNotIn("sir", msg.lower())
        self.assertTrue(
            "background" in msg.lower() or "report back" in msg.lower(),
        )

    def test_progress_varies_by_intent(self) -> None:
        open_msg = self.responses.progress("chrome aç", 0)
        code_msg = self.responses.progress("fix the bug in main.py", 0)
        self.assertNotEqual(open_msg, code_msg)

    def test_stable_soft_when_empty_command(self) -> None:
        a = self.responses.soft("")
        b = self.responses.soft("")
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
