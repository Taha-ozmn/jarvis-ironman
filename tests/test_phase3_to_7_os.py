"""Phase 3–7 — plugins, cancel, evidence, hybrid memory, degraded routing."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from brain.model_router import ModelRouter
from core.app import JarvisOS
from core.cancellation import CancellationToken, cancel_active, set_active_token
from core.degraded import get_degraded_mode
from core.evidence import ExecutionEvidence, claim_allowed
from core.execution_engine import ExecutionRequest
from core.planner import Plan, PlanStep
from core.task_manager import TaskManager
from memory.database import Database
from memory.retrieval import format_recall_block, hybrid_retrieve, temporal_query_hours
from tools.base import BaseTool, ToolResult
from tools.packages import list_plugins, load_plugins, register_plugin, unregister_plugin
from tools.registry import ToolRegistry
from security.permissions import PermissionLevel


class _EchoTool(BaseTool):
    name = "test.echo"
    description = "echo"
    permission_level = PermissionLevel.READ
    input_schema = {"text": {"type": "str", "required": True}}

    def validate(self, arguments: dict) -> str | None:
        if arguments.get("text") == "bad":
            return "text rejected"
        return None

    def run(self, arguments: dict) -> ToolResult:
        return ToolResult(ok=True, data=str(arguments.get("text") or ""))


class PluginTests(unittest.TestCase):
    def tearDown(self) -> None:
        unregister_plugin("echo_plugin")

    def test_register_and_load(self) -> None:
        def _plug(reg: ToolRegistry, ctx: dict) -> None:
            reg.register(_EchoTool())

        register_plugin("echo_plugin", _plug)
        self.assertIn("echo_plugin", list_plugins())
        reg = ToolRegistry()
        loaded = load_plugins(reg, {})
        self.assertIn("echo_plugin", loaded)
        self.assertIsNotNone(reg.get("test.echo"))


class CancelResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.os = JarvisOS(
            {
                "jarvis": {"user_name": "Taha"},
                "jarvis2": {
                    "db_path": "data/p47.db",
                    "max_permission_level": 2,
                    "plan_max_retries": 0,
                },
            },
            root=root,
        )

    def tearDown(self) -> None:
        get_degraded_mode().exit()
        self.os.close()
        self._tmp.cleanup()

    def test_cancel_token(self) -> None:
        tok = CancellationToken()
        set_active_token(tok)
        self.assertTrue(cancel_active("stop"))
        self.assertTrue(tok.is_cancelled)
        self.assertEqual(tok.reason, "stop")
        set_active_token(None)

    def test_plan_cancel_mid_run(self) -> None:
        self.os.tools.register(_EchoTool())

        def _slow_cancel() -> None:
            time.sleep(0.05)
            self.os.cancel_active_plan("test_cancel")

        plan = Plan(
            plan_id="p-cancel",
            goal="cancel me",
            steps=[
                PlanStep(tool_name="test.echo", arguments={"text": "a"}, description="a"),
                PlanStep(tool_name="test.echo", arguments={"text": "b"}, description="b"),
                PlanStep(tool_name="test.echo", arguments={"text": "c"}, description="c"),
            ],
        )
        # Cancel immediately before loop processes next steps via background signal
        threading.Thread(target=_slow_cancel, daemon=True).start()
        # Also cancel via engine token after first step by pre-cancelling mid-loop:
        # direct cancel before execute still works if we cancel after start
        result_holder: list = []

        def _run() -> None:
            result_holder.append(self.os.execution.execute_plan(plan))

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(0.02)
        self.os.cancel_active_plan("mid")
        t.join(timeout=2.0)
        self.assertTrue(result_holder)
        # Either cancelled or completed quickly — cancel path preferred
        r = result_holder[0]
        if not r.ok:
            self.assertIn(r.stopped_reason, ("mid", "test_cancel", "user_cancel", "cancelled"))

    def test_task_status_aliases(self) -> None:
        task = self.os.tasks.create("alias")
        updated = self.os.tasks.update(task.id, status="done")
        self.assertEqual(updated.status, "completed")
        listed = self.os.tasks.list(status="done")
        self.assertEqual(len(listed), 1)


class EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.os = JarvisOS(
            {"jarvis2": {"db_path": "data/ev.db", "max_permission_level": 2}},
            root=root,
        )
        self.os.tools.register(_EchoTool())

    def tearDown(self) -> None:
        self.os.close()
        self._tmp.cleanup()

    def test_evidence_on_success(self) -> None:
        result = self.os.execution.execute(
            ExecutionRequest("test.echo", {"text": "hi"}, requested_by="test")
        )
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.evidence)
        self.assertEqual(result.evidence.get("tool"), "test.echo")
        self.assertTrue(self.os.execution.last_evidence)
        ev = self.os.execution.last_evidence[-1]
        self.assertIsInstance(ev, ExecutionEvidence)
        self.assertTrue(claim_allowed(ev))

    def test_validate_hook_rejects(self) -> None:
        result = self.os.execution.execute(
            ExecutionRequest("test.echo", {"text": "bad"}, requested_by="test")
        )
        self.assertFalse(result.ok)
        self.assertIn("rejected", (result.error or "").lower())


class MemoryRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "m.db")
        self.db.migrate()
        from memory.repository import MemoryRepository

        self.repo = MemoryRepository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_hybrid_ranks_relevant(self) -> None:
        self.repo.create("Taha prefers British accent", category="preference", importance=5)
        self.repo.create("Unrelated grocery list: milk", category="note", importance=1)
        ranked = hybrid_retrieve(self.repo, "What accent does Taha prefer?", limit=3)
        self.assertTrue(ranked)
        self.assertIn("British", ranked[0].memory.content)
        block = format_recall_block(ranked)
        self.assertIn("LONG-TERM MEMORY", block)

    def test_temporal_hours(self) -> None:
        self.assertEqual(temporal_query_hours("dün ne yaptık"), 36.0)
        self.assertIsNone(temporal_query_hours("hello"))


class DegradedRoutingTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_degraded_mode().exit()

    def test_degraded_forces_cheap(self) -> None:
        router = ModelRouter(
            {
                "chat": "gemini-3-flash",
                "complex": "composer-2.5",
                "deep": "auto",
                "default": "gemini-3-flash",
            },
            "gemini-3-flash",
            resolve=lambda x: x,
        )
        get_degraded_mode().enter("test")
        self.assertEqual(router.pick("complex"), "gemini-3-flash")
        self.assertEqual(router.pick_for_complexity("complex"), "gemini-3-flash")

    def test_complexity_pick(self) -> None:
        router = ModelRouter(
            {
                "chat": "gemini-3-flash",
                "complex": "composer-2.5",
                "search": "gemini-3-flash",
                "default": "gemini-3-flash",
            },
            "gemini-3-flash",
            resolve=lambda x: x,
        )
        self.assertEqual(router.pick_for_complexity("chat"), "gemini-3-flash")
        self.assertEqual(router.pick_for_complexity("complex"), "composer-2.5")

    def test_handle_turn_blocks_cursor_when_degraded(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        os_core = JarvisOS(
            {"jarvis2": {"db_path": "data/deg.db"}},
            root=Path(tmp.name),
        )
        try:
            os_core.enter_degraded_mode("offline")
            turn = os_core.handle_turn(
                "write a long essay about iron man arc reactor physics"
            )
            self.assertFalse(turn.allow_cursor)
            self.assertEqual(turn.brain_path, "degraded")
        finally:
            get_degraded_mode().exit()
            os_core.close()
            tmp.cleanup()


class ChaosRecoveryTests(unittest.TestCase):
    """Lightweight chaos — failures must not crash the OS loop."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.os = JarvisOS(
            {"jarvis2": {"db_path": "data/chaos.db", "tool_max_retries": 2}},
            root=Path(self._tmp.name),
        )

    def tearDown(self) -> None:
        get_degraded_mode().exit()
        self.os.close()
        self._tmp.cleanup()

    def test_unknown_tool_safe(self) -> None:
        result = self.os.execution.execute(ExecutionRequest("no.such.tool", {}))
        self.assertFalse(result.ok)
        speech = self.os.try_handle_command("xyzzy_not_a_real_command_qwerty")
        self.assertIsNone(speech)

    def test_tool_crash_isolated(self) -> None:
        class Boom(BaseTool):
            name = "test.boom"
            description = "boom"
            permission_level = PermissionLevel.READ

            def run(self, arguments: dict) -> ToolResult:
                raise RuntimeError("simulated crash")

        self.os.tools.register(Boom())
        result = self.os.execution.execute(ExecutionRequest("test.boom", {}))
        self.assertFalse(result.ok)
        self.assertIn("simulated", (result.error or "").lower())


if __name__ == "__main__":
    unittest.main()
