"""Phase 8+ follow-on — plan timeline, browser/dev verify, speech throttle, decision facade."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.app import JarvisOS
from core.decision import BrainPath, decide_turn, path_after_local
from core.complexity import TaskComplexity
from core.planner import Plan, PlanStep
from core.verification import should_verify, verify_tool_result
from tools.base import BaseTool, ToolResult
from security.permissions import PermissionLevel
from ui.hud_data import build_command_center


class _EchoTool(BaseTool):
    name = "test.echo"
    description = "echo"
    permission_level = PermissionLevel.READ
    input_schema = {"text": {"type": "str", "required": True}}

    def run(self, arguments: dict) -> ToolResult:
        return ToolResult(ok=True, data=str(arguments.get("text") or ""))


class PlanTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.os = JarvisOS(
            {"jarvis2": {"db_path": "data/tl.db", "plan_max_retries": 0}},
            root=Path(self._tmp.name),
        )
        self.os.tools.register(_EchoTool())

    def tearDown(self) -> None:
        self.os.close()
        self._tmp.cleanup()

    def test_timeline_populated(self) -> None:
        plan = Plan(
            goal="echo",
            steps=[PlanStep(tool_name="test.echo", arguments={"text": "x"})],
        )
        self.os.execution.execute_plan(plan)
        self.assertGreaterEqual(len(self.os.execution.plan_timeline), 2)
        cc = build_command_center(self.os)
        self.assertTrue(cc.get("plan_timeline"))
        phases = {e.get("phase") for e in self.os.execution.plan_timeline}
        self.assertIn("started", phases)
        self.assertIn("completed", phases)


class VerifyBrowserDevTests(unittest.TestCase):
    def test_should_verify(self) -> None:
        for name in (
            "browser.open_url",
            "browser.search",
            "browser.get_page_text",
            "dev.run_command",
        ):
            self.assertTrue(should_verify(name), name)

    def test_browser_open(self) -> None:
        outcome = verify_tool_result(
            "browser.open_url",
            {"url": "https://example.com"},
            ToolResult(ok=True, data="Opened https://example.com"),
        )
        self.assertTrue(outcome.ok)

    def test_browser_page_text_short(self) -> None:
        outcome = verify_tool_result(
            "browser.get_page_text",
            {"url": "https://example.com"},
            ToolResult(ok=True, data="hi"),
        )
        self.assertFalse(outcome.ok)

    def test_dev_command(self) -> None:
        outcome = verify_tool_result(
            "dev.run_command",
            {"command": "echo hi"},
            ToolResult(ok=True, data="hi"),
        )
        self.assertTrue(outcome.ok)


class PlanSpeechThrottleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.os = JarvisOS(
            {
                "jarvis2": {
                    "db_path": "data/sp.db",
                    "plan_speech_min_interval": 30,
                }
            },
            root=Path(self._tmp.name),
        )
        self.spoken: list[str] = []
        self.os.set_speak_callback(lambda t: self.spoken.append(t))

    def tearDown(self) -> None:
        self.os.close()
        self._tmp.cleanup()

    def test_throttle_skips_second(self) -> None:
        class R:
            ok = True
            completed = 2
            total = 2
            stopped_reason = ""
            speech = "long speech that should be replaced"

        self.os._speak_plan_result(R())
        self.os._speak_plan_result(R())
        self.assertEqual(len(self.spoken), 1)
        self.assertIn("Plan complete", self.spoken[0])


class DecisionFacadeTests(unittest.TestCase):
    def test_decide_blocks_simple(self) -> None:
        d = decide_turn("saat kaç")
        self.assertFalse(d.allow_cursor)
        self.assertEqual(d.complexity, TaskComplexity.SIMPLE)

    def test_decide_degraded(self) -> None:
        d = decide_turn("fix authentication bug", degraded=True)
        self.assertFalse(d.allow_cursor)
        self.assertEqual(d.preferred_path, BrainPath.DEGRADED)

    def test_path_after_local(self) -> None:
        self.assertEqual(path_after_local(tool_hit=True), BrainPath.FAST)
        d = decide_turn("explain quantum computing")
        self.assertEqual(
            path_after_local(tool_hit=False, decision=d),
            BrainPath.DEEP,
        )


if __name__ == "__main__":
    unittest.main()
