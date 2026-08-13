"""Phase 7 — planner + multi-step execution + verification."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from core.app import JarvisOS
from core.command_router import CommandRouter
from core.execution_engine import ExecutionEngine, ExecutionRequest
from core.planner import Planner
from core.verification import should_verify, verify_tool_result
from security.permissions import PermissionLevel
from tools.base import StubTool, ToolResult


class PlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = Planner()

    def test_simple_skips_plan(self) -> None:
        plan = self.planner.create("what time is it")
        self.assertFalse(plan.complex)
        self.assertEqual(plan.steps, [])

    def test_complex_analyze_and_fix(self) -> None:
        plan = self.planner.create("analyze and fix the repository tests")
        self.assertTrue(plan.complex)
        names = [s.tool_name for s in plan.steps]
        self.assertTrue(
            "dev.fix_cycle" in names
            or ("dev.analyze_repo" in names and "dev.run_tests" in names),
            names,
        )

    def test_organize_plan(self) -> None:
        plan = self.planner.create("organize my projects")
        names = [s.tool_name for s in plan.steps]
        self.assertIn("project.list", names)
        self.assertIn("task.list", names)


class RouterPlanBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_plan_and_route(self) -> None:
        m = self.router.route("plan and analyze and fix the repo")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "plan.run")

    def test_backup_route(self) -> None:
        m = self.router.route("backup memory")
        self.assertEqual(m.request.tool_name, "system.backup")
        m2 = self.router.route("yedekle")
        self.assertEqual(m2.request.tool_name, "system.backup")


class PlanExecutionTests(unittest.TestCase):
    def test_execute_plan_sequential_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os_core = JarvisOS(
                {
                    "jarvis2": {
                        "db_path": "data/p7.db",
                        "max_permission_level": 3,
                        "auto_approve_dangerous": True,
                        "plan_max_retries": 1,
                    }
                },
                root=root,
            )
            calls: list[str] = []

            class CountingTool(StubTool):
                def run(self, arguments):  # type: ignore[no-untyped-def]
                    calls.append(self.name)
                    return ToolResult(ok=True, data=f"ok:{self.name}")

            os_core.tools.register(CountingTool("demo.a", "a", PermissionLevel.READ))
            os_core.tools.register(CountingTool("demo.b", "b", PermissionLevel.READ))
            from core.planner import Plan, PlanStep

            plan = Plan(
                goal="demo",
                steps=[
                    PlanStep("demo.a", {}, description="A"),
                    PlanStep("demo.b", {}, description="B"),
                ],
            )
            result = os_core.execution.execute_plan(plan)
            self.assertTrue(result.ok, result.speech)
            self.assertEqual(calls, ["demo.a", "demo.b"])
            self.assertEqual(result.completed, 2)
            # Task persisted
            self.assertIsNotNone(plan.task_id)
            os_core.close()

    def test_stop_on_confirmation_denial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os_core = JarvisOS(
                {
                    "jarvis2": {
                        "db_path": "data/p7c.db",
                        "max_permission_level": 3,
                        "auto_approve_dangerous": False,
                        "confirm_timeout": 0.2,
                    }
                },
                root=root,
            )
            os_core.tools.register(
                StubTool("danger.x", "danger", PermissionLevel.DANGEROUS)
            )
            from core.planner import Plan, PlanStep

            plan = Plan(
                goal="danger",
                steps=[
                    PlanStep("system.time", {}, description="safe"),
                    PlanStep("danger.x", {}, description="danger"),
                ],
            )
            result = os_core.execution.execute_plan(plan)
            self.assertFalse(result.ok)
            self.assertEqual(result.stopped_reason, "confirmation_required")
            self.assertEqual(result.resume_from, 1)
            os_core.close()

    def test_background_plan_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/p7b.db", "max_permission_level": 2}},
                root=root,
            )
            done = threading.Event()

            class SlowTool(StubTool):
                def run(self, arguments):  # type: ignore[no-untyped-def]
                    time.sleep(0.15)
                    return ToolResult(ok=True, data="slow")

            os_core.tools.register(SlowTool("demo.slow", "slow", PermissionLevel.READ))
            from core.planner import Plan, PlanStep

            plan = Plan(goal="bg", steps=[PlanStep("demo.slow", {})])
            msg = os_core.execution.execute_plan_background(
                plan, on_done=lambda r: done.set()
            )
            self.assertIn("background", msg.lower())
            self.assertTrue(done.wait(timeout=3))
            os_core.close()

    def test_tool_failure_never_kills_voice_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/p7v.db", "max_permission_level": 2}},
                root=root,
            )

            class Boom(StubTool):
                def run(self, arguments):  # type: ignore[no-untyped-def]
                    raise RuntimeError("explode")

            os_core.tools.register(Boom("demo.boom", "boom", PermissionLevel.READ))
            # Patch router to return boom
            speech = os_core.try_handle_command("saat kaç")  # safe path
            self.assertIsNotNone(speech)
            # Direct execute crash isolation
            result = os_core.execution.execute(ExecutionRequest("demo.boom", {}))
            self.assertFalse(result.ok)
            self.assertIn("explode", result.error or "")
            # Still healthy after crash
            self.assertTrue(os_core.health()["ok"])
            os_core.close()


class VerificationTests(unittest.TestCase):
    def test_should_verify_known_tools(self) -> None:
        self.assertTrue(should_verify("git.commit"))
        self.assertTrue(should_verify("fs.move"))
        self.assertFalse(should_verify("system.time"))

    def test_verify_fs_move(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "out.txt"
            dst.write_text("x", encoding="utf-8")
            outcome = verify_tool_result(
                "fs.move",
                {"src": "a", "dst": str(dst)},
                ToolResult(ok=True, data="moved"),
            )
            self.assertTrue(outcome.ok)


if __name__ == "__main__":
    unittest.main()
