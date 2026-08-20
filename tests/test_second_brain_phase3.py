"""Phase 3 — verify-before-claim, agent allowlists, background analyze, barge-in."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.agent_profiles import (
    CODING_TOOLS,
    RESEARCH_TOOLS,
    coding_analyze_plan,
    filter_plan_steps,
    looks_like_coding_analyze,
    research_plan,
)
from core.command_router import CommandRouter
from core.planner import Plan, PlanStep
from core.verification import (
    claim_safe_speech,
    should_verify,
    verify_tool_result,
)
from tools.base import ToolResult


class VerifyBeforeClaimTests(unittest.TestCase):
    def test_always_verify_covers_tabs_media_git(self) -> None:
        for name in (
            "media.play",
            "browser.open_url",
            "browser.list_tabs",
            "git.commit",
            "git.push",
        ):
            self.assertTrue(should_verify(name))

    def test_media_play_requires_query_echo(self) -> None:
        bad = verify_tool_result(
            "media.play",
            {"query": "Tarkan"},
            ToolResult(ok=True, data="OK"),
        )
        self.assertFalse(bad.ok)
        good = verify_tool_result(
            "media.play",
            {"query": "Tarkan"},
            ToolResult(ok=True, data="I've searched YouTube for «Tarkan»."),
        )
        self.assertTrue(good.ok)

    def test_list_tabs_verify(self) -> None:
        empty_ok = verify_tool_result(
            "browser.list_tabs",
            {},
            ToolResult(ok=True, data="Açık sekme bulamadım. Chrome veya Safari çalışıyor mu?"),
        )
        self.assertTrue(empty_ok.ok)
        bad = verify_tool_result(
            "browser.list_tabs",
            {},
            ToolResult(ok=True, data="something weird"),
        )
        self.assertFalse(bad.ok)

    def test_open_url_requires_acildi(self) -> None:
        bad = verify_tool_result(
            "browser.open_url",
            {"url": "https://example.com"},
            ToolResult(ok=True, data="done"),
        )
        self.assertFalse(bad.ok)
        good = verify_tool_result(
            "browser.open_url",
            {"url": "https://example.com"},
            ToolResult(ok=True, data="Opened https://example.com."),
        )
        self.assertTrue(good.ok)

    def test_claim_safe_speech_no_false_success(self) -> None:
        fail = ToolResult(ok=False, error="Permission denied")
        speech = claim_safe_speech(fail)
        self.assertIn("Permission", speech)
        self.assertNotIn("açıldı", speech.lower())


class AgentAllowlistTests(unittest.TestCase):
    def test_profiles_disjoint_core(self) -> None:
        self.assertIn("research.topic", RESEARCH_TOOLS)
        self.assertIn("dev.analyze_repo", CODING_TOOLS)
        self.assertNotIn("dev.analyze_repo", RESEARCH_TOOLS)
        self.assertNotIn("research.topic", CODING_TOOLS)

    def test_filter_plan_steps(self) -> None:
        plan = Plan(
            goal="x",
            steps=[
                PlanStep("research.topic", {"query": "a"}),
                PlanStep("system.shell", {"command": "rm -rf /"}),
            ],
        )
        filtered = filter_plan_steps(plan, "research")
        self.assertEqual(len(filtered.steps), 1)
        self.assertEqual(filtered.steps[0].tool_name, "research.topic")

    def test_coding_analyze_plan_tools(self) -> None:
        plan = coding_analyze_plan()
        for step in plan.steps:
            self.assertIn(step.tool_name, CODING_TOOLS)

    def test_looks_like_coding_analyze(self) -> None:
        self.assertTrue(looks_like_coding_analyze("projeyi analiz et"))
        self.assertTrue(looks_like_coding_analyze("repoyu incele"))


class AgentRouteAndBackgroundTests(unittest.TestCase):
    def test_router_projeyi_analiz(self) -> None:
        router = CommandRouter()
        m = router.route("projeyi analiz et")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "agent.coding_analyze")
        self.assertTrue(m.request.arguments.get("background"))

    def test_os_coding_agent_ack_background(self) -> None:
        from core.app import JarvisOS

        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {
                "jarvis": {"user_name": "Taha", "language": "tr-TR"},
                "jarvis2": {
                    "db_path": "data/p3a.db",
                    "max_permission_level": 2,
                    "max_plan_steps": 4,
                },
            },
            root=root,
        )
        try:
            with patch.object(
                os_core.execution,
                "execute_plan_background",
                return_value="bg",
            ) as bg:
                reply = os_core.try_handle_command("projeyi analiz et")
            self.assertIsNotNone(reply)
            self.assertIn("background", (reply or "").lower())
            bg.assert_called_once()
            self.assertIn("agent.coding_analyze", os_core.tools.list_names())
            self.assertIn("agent.research", os_core.tools.list_names())
        finally:
            os_core.db.close()
            tmp.cleanup()


class BargeInTests(unittest.TestCase):
    def test_stop_interrupts_brain(self) -> None:
        from main import JarvisCore

        # Minimal stub — only exercise try_stop_speech path
        core = MagicMock(spec=JarvisCore)
        core._is_stop_speech_phrase = JarvisCore._is_stop_speech_phrase.__get__(core)
        core.speaker = MagicMock()
        core.brain = MagicMock()
        core.brain._interrupt_inflight = MagicMock()
        # Bind real method
        reply = JarvisCore.try_stop_speech(core, "jarvis dur")
        self.assertEqual(reply, "Standing by.")
        core.speaker.flush.assert_called_once()
        core.brain._interrupt_inflight.assert_called_once()


if __name__ == "__main__":
    unittest.main()
