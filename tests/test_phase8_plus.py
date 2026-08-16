"""Phase 8+ — HUD plan progress, verify fs/git, Cursor trim, health, packs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.app import JarvisOS
from core.complexity import TaskComplexity, allows_cursor, classify_task_complexity
from core.execution_engine import ExecutionRequest
from core.planner import Plan, PlanStep
from core.verification import should_verify, verify_tool_result
from tools.base import BaseTool, ToolResult
from security.permissions import PermissionLevel
from automation.packs import load_automation_packs
from ui.server import JarvisUI
from ui.hud_data import build_command_center


class _EchoTool(BaseTool):
    name = "test.echo"
    description = "echo"
    permission_level = PermissionLevel.READ
    input_schema = {"text": {"type": "str", "required": True}}

    def run(self, arguments: dict) -> ToolResult:
        return ToolResult(ok=True, data=str(arguments.get("text") or ""))


class CursorTrimTests(unittest.TestCase):
    def test_fillers_are_chat(self) -> None:
        for phrase in ("ok", "tamam", "yes", "hmm", "ne"):
            c = classify_task_complexity(phrase)
            self.assertEqual(c, TaskComplexity.CHAT, phrase)
            self.assertFalse(allows_cursor(c), phrase)

    def test_local_phrases_are_simple(self) -> None:
        for phrase in ("list tasks", "stop", "dur", "mute", "görevler"):
            c = classify_task_complexity(phrase)
            self.assertEqual(c, TaskComplexity.SIMPLE, phrase)
            self.assertFalse(allows_cursor(c), phrase)


class VerifyFsGitTests(unittest.TestCase):
    def test_should_verify_extended(self) -> None:
        for name in ("fs.write", "fs.create", "git.add", "git.push"):
            self.assertTrue(should_verify(name), name)

    def test_verify_fs_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.txt"
            path.write_text("hi", encoding="utf-8")
            outcome = verify_tool_result(
                "fs.write",
                {"path": str(path), "content": "hi"},
                ToolResult(ok=True, data="Wrote out.txt"),
            )
            self.assertTrue(outcome.ok)

    def test_verify_fs_write_missing(self) -> None:
        outcome = verify_tool_result(
            "fs.write",
            {"path": "/tmp/jarvis_no_such_file_xyz_99.txt", "content": "x"},
            ToolResult(ok=True, data="Wrote"),
        )
        self.assertFalse(outcome.ok)


class PlanProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.os = JarvisOS(
            {"jarvis2": {"db_path": "data/planprog.db", "plan_max_retries": 0}},
            root=Path(self._tmp.name),
        )
        self.os.tools.register(_EchoTool())
        self.events: list = []
        self.os.bus.subscribe("plan.progress", lambda e: self.events.append(e))

    def tearDown(self) -> None:
        self.os.close()
        self._tmp.cleanup()

    def test_plan_emits_progress(self) -> None:
        plan = Plan(
            goal="echo twice",
            steps=[
                PlanStep(tool_name="test.echo", arguments={"text": "a"}),
                PlanStep(tool_name="test.echo", arguments={"text": "b"}),
            ],
        )
        result = self.os.execution.execute_plan(plan)
        self.assertTrue(result.ok)
        self.assertTrue(self.events)
        self.assertIsNotNone(self.os.execution.last_plan_progress)
        self.assertEqual(self.os.execution.last_plan_progress.get("phase"), "completed")
        cc = build_command_center(self.os)
        self.assertIsNotNone(cc.get("plan_progress"))


class HealthEndpointTests(unittest.TestCase):
    def test_api_health_route_registered(self) -> None:
        ui = JarvisUI(port=0, health_provider=lambda: {"ok": True, "passed": 1})
        resources = [r.resource.canonical for r in ui._app.router.routes()]
        self.assertTrue(any("/api/health" in str(r) for r in resources))


class AutomationPackTests(unittest.TestCase):
    def test_load_pack_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packs = root / "packs"
            packs.mkdir()
            (packs / "demo.yaml").write_text(
                "name: Pack Demo\nenabled: false\n"
                "trigger:\n  type: manual\n"
                "action:\n  type: speak\n  text: hi\n",
                encoding="utf-8",
            )
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/packs.db", "automation": True}},
                root=root,
            )
            try:
                loaded = load_automation_packs(os_core.automation, packs)
                self.assertIn("Pack Demo", loaded)
                again = load_automation_packs(os_core.automation, packs)
                self.assertEqual(again, [])
                names = [r.name for r in os_core.automation.list_rules()]
                self.assertEqual(names.count("Pack Demo"), 1)
            finally:
                os_core.close()


if __name__ == "__main__":
    unittest.main()
