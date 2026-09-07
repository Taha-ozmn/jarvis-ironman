"""Phase 5 — checkpoint/resume, intent schema, proactive suggestions, persona."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.app import JarvisOS
from core.command_router import CommandRouter
from core.intent_schema import sanitize_plan, validate_plan
from core.persona_engine import apply_personality_to_brain, build_persona_overlay
from core.plan_checkpoint import PlanCheckpointStore, plan_from_dict, plan_to_dict
from core.planner import Plan, PlanStep
from core.context_manager import ContextManager, SessionContext
from proactive.suggestions import SuggestionEngine


class PlanCheckpointTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        plan = Plan(
            goal="analyze repo",
            steps=[
                PlanStep("git.status", {}, description="status"),
                PlanStep("dev.run_tests", {}, description="tests"),
            ],
        )
        data = plan_to_dict(plan, resume_from=1, reason="step_failed")
        restored, idx = plan_from_dict(data)
        self.assertEqual(idx, 1)
        self.assertEqual(len(restored.steps), 2)
        self.assertEqual(restored.steps[1].tool_name, "dev.run_tests")

    def test_store_in_session(self) -> None:
        ctx = ContextManager(SessionContext())
        store = PlanCheckpointStore(ctx)
        plan = Plan(goal="x", steps=[PlanStep("task.list", {})])
        store.save(plan, 0, "failed")
        self.assertTrue(store.has_checkpoint())
        store.clear()
        self.assertFalse(store.has_checkpoint())


class IntentSchemaTests(unittest.TestCase):
    def test_rejects_unknown_tool(self) -> None:
        plan = Plan(
            goal="bad",
            steps=[PlanStep("system.shell", {"command": "rm -rf /"})],
        )
        result = validate_plan(plan)
        self.assertFalse(result.ok)

    def test_sanitize_keeps_allowed(self) -> None:
        plan = Plan(
            goal="ok",
            steps=[
                PlanStep("task.list", {}),
                PlanStep("evil.tool", {}),
            ],
        )
        clean = sanitize_plan(plan)
        self.assertEqual(len(clean.steps), 1)
        self.assertEqual(clean.steps[0].tool_name, "task.list")


class SuggestionEngineTests(unittest.TestCase):
    def test_checkpoint_priority(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {
                "jarvis": {"language": "en-GB"},
                "jarvis2": {"db_path": "data/sug.db", "max_permission_level": 2},
            },
            root=root,
        )
        try:
            plan = Plan(goal="fix tests", steps=[PlanStep("dev.run_tests", {})])
            os_core.checkpoints.save(plan, 0, "timeout")
            text = os_core.proactive_suggestion()
            self.assertIn("paused plan", text.lower())
        finally:
            os_core.db.close()
            tmp.cleanup()


class ResumeRouteTests(unittest.TestCase):
    def test_devam_et(self) -> None:
        m = CommandRouter().route("devam et")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "plan.resume")

    def test_suggestions_route(self) -> None:
        m = CommandRouter().route("what should I do today")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "proactive.suggestions")


class PersonaEngineTests(unittest.TestCase):
    def test_overlay_english(self) -> None:
        overlay = build_persona_overlay(
            {
                "name": "J.A.R.V.I.S.",
                "traits": ["calm", "witty"],
                "reply_language": "en",
                "behavior": {"second_brain": True, "wit_level": "light"},
            }
        )
        self.assertIn("British English", overlay)
        self.assertIn("second brain", overlay.lower())

    def test_apply_to_brain(self) -> None:
        class FakeBrain:
            reply_language = "tr"
            language = "tr-TR"
            max_speech_chars = 100
            progress_interval_sec = 5
            formal_address = False

            def apply_personality_overlay(self, overlay: str) -> None:
                self._personality_overlay = overlay

        brain = FakeBrain()
        apply_personality_to_brain(
            brain,
            {"reply_language": "en", "language": "en-GB", "speech": {"max_chars": 280}},
        )
        self.assertEqual(brain.reply_language, "en")


if __name__ == "__main__":
    unittest.main()
