"""Universal decision engine tests."""

from __future__ import annotations

import unittest

from core.decision_engine import DecisionContext, DecisionEngine
from core.mode_selector import AgentMode


class DecisionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DecisionEngine()

    def test_vague_open_chooses_chrome(self) -> None:
        d = self.engine.decide("bir uygulama aç")
        self.assertTrue(d.autonomous)
        self.assertIn("chrome", d.rewritten.lower())

    def test_vague_open_application_english(self) -> None:
        d = self.engine.decide("open an application")
        self.assertTrue(d.autonomous)
        self.assertIn("chrome", d.rewritten.lower())

    def test_vague_open_app_english(self) -> None:
        d = self.engine.decide("open application")
        self.assertTrue(d.autonomous)
        self.assertIn("chrome", d.rewritten.lower())

    def test_vague_research_uses_topic(self) -> None:
        ctx = DecisionContext(active_topic="Jettel push notification")
        d = self.engine.decide("bunu araştır", ctx)
        self.assertTrue(d.autonomous)
        self.assertIn("Jettel", d.rewritten)

    def test_vague_research_asks_when_no_context(self) -> None:
        d = self.engine.decide("araştır")
        self.assertTrue(d.needs_clarification)

    def test_music_overrides_query(self) -> None:
        d = self.engine.decide("güzel bir şarkı aç")
        self.assertIn("query", d.tool_overrides)
        self.assertIn("Teoman", d.tool_overrides["query"])

    def test_open_it_uses_entity(self) -> None:
        ctx = DecisionContext(last_entity="spotify")
        d = self.engine.decide("onu aç", ctx)
        self.assertTrue(d.autonomous)
        self.assertIn("spotify", d.rewritten.lower())

    def test_chat_followup_stays_chat(self) -> None:
        d = self.engine.decide("peki ya")
        self.assertEqual(d.mode, AgentMode.CHAT)


if __name__ == "__main__":
    unittest.main()
