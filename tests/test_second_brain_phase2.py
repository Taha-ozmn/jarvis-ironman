"""Phase 2 Second Brain — memory layers, agent guards, cost meter, voice routes."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.command_router import CommandRouter
from core.cost_meter import CostMeter, estimate_complexity, estimate_cost_units
from core.execution_engine import ExecutionEngine, ExecutionRequest
from core.planner import Plan, PlanStep, Planner
from core.event_bus import EventBus
from memory.database import Database
from memory.layers import MemoryLayers
from memory.repository import MemoryRepository
from security.audit import AuditLog
from security.permissions import PermissionGate, PermissionLevel
from tools.base import BaseTool, ToolResult
from tools.registry import ToolRegistry


class MemoryLayersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "m.db")
        self.db.migrate()
        self.repo = MemoryRepository(self.db)
        self.layers = MemoryLayers(self.repo)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_profile_update_and_speech(self) -> None:
        self.layers.update_profile("name", "Taha", importance=5)
        self.repo.create("Tercihim Türkçe", category="preference", importance=4)
        speech = self.layers.profile_speech(language="tr-TR")
        self.assertIn("Taha", speech)
        self.assertNotIn("Henüz", speech)

    def test_episodic_and_retrieve(self) -> None:
        self.layers.update_profile("name", "Emre")
        self.layers.record_episodic("Bugün Jettel projesinde çalıştık uzun uzun")
        block = self.layers.retrieve_for_prompt("proje", max_chars=500)
        self.assertIn("USER PROFILE", block)
        self.assertIn("Emre", block)

    def test_forget_last(self) -> None:
        self.layers.record_episodic("Unutulacak geçici not buraya")
        count, speech = self.layers.forget("", last_n=1)
        self.assertEqual(count, 1)
        self.assertIn("unut", speech.lower())


class VoiceMemoryRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_about_me_route(self) -> None:
        m = self.router.route("Ne biliyorsun benim hakkımda?")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "memory.about_user")

    def test_forget_route(self) -> None:
        m = self.router.route("bunu unut")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "memory.forget")

    def test_forget_with_query(self) -> None:
        m = self.router.route("unut Spotify tercihim")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "memory.forget")
        self.assertIn("Spotify", m.request.arguments.get("query", ""))


class AgentGuardTests(unittest.TestCase):
    def test_planner_caps_steps(self) -> None:
        planner = Planner(max_steps=2)

        # Force a multi-hint goal that yields multiple template steps
        def many_steps(lower: str, text: str):
            return [
                PlanStep("project.list", {}),
                PlanStep("task.list", {}),
                PlanStep("git.status", {}),
                PlanStep("dev.run_tests", {}),
            ]

        planner._template_steps = many_steps  # type: ignore[method-assign]
        plan = planner.create("plan and organize and analyze and fix")
        self.assertLessEqual(len(plan.steps), 2)

    def test_execution_engine_max_steps_and_timeout(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Database(Path(tmp.name) / "e.db")
            db.migrate()
            registry = ToolRegistry()

            class SlowTool(BaseTool):
                name = "test.slow"
                description = "slow"
                permission_level = PermissionLevel.READ

                def run(self, arguments):
                    time.sleep(0.05)
                    return ToolResult(ok=True, data="ok")

            registry.register(SlowTool())
            engine = ExecutionEngine(
                registry,
                PermissionGate(PermissionLevel.SYSTEM),
                AuditLog(db),
                EventBus(),
                max_retries=0,
                max_plan_steps=2,
                plan_timeout_sec=30.0,
            )
            plan = Plan(
                goal="x",
                steps=[
                    PlanStep("test.slow", {}),
                    PlanStep("test.slow", {}),
                    PlanStep("test.slow", {}),
                    PlanStep("test.slow", {}),
                ],
            )
            # Truncation to max_plan_steps=2
            result = engine.execute_plan(plan, persist_task=False)
            self.assertEqual(result.total, 2)
            self.assertTrue(result.ok)

            # Timeout: wall clock exceeded mid-plan
            engine2 = ExecutionEngine(
                registry,
                PermissionGate(PermissionLevel.SYSTEM),
                AuditLog(db),
                EventBus(),
                max_retries=0,
                max_plan_steps=10,
                plan_timeout_sec=0.02,
            )
            plan2 = Plan(
                goal="y",
                steps=[
                    PlanStep("test.slow", {}),
                    PlanStep("test.slow", {}),
                    PlanStep("test.slow", {}),
                ],
            )
            result2 = engine2.execute_plan(plan2, persist_task=False)
            self.assertFalse(result2.ok)
            self.assertEqual(result2.stopped_reason, "plan_timeout")
        finally:
            tmp.cleanup()


class CostMeterTests(unittest.TestCase):
    def test_estimate_paths(self) -> None:
        self.assertEqual(estimate_complexity("chrome aç", brain_path="fast"), "fast")
        self.assertEqual(estimate_cost_units("fast"), 0)
        self.assertGreater(estimate_cost_units("deep"), estimate_cost_units("simple"))

    def test_meter_persists(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            meter = CostMeter(Path(tmp.name) / "cost.json")
            entry = meter.record("büyük proje yaz", brain_path="deep", request_id="r1")
            self.assertIn(entry["complexity"], ("simple", "complex", "deep"))
            self.assertGreaterEqual(meter.totals().get("units", 0), 1)
        finally:
            tmp.cleanup()


class AboutUserToolIntegrationTests(unittest.TestCase):
    def test_os_handles_about_and_forget(self) -> None:
        from core.app import JarvisOS

        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {
                "jarvis": {"user_name": "Taha", "language": "tr-TR"},
                "jarvis2": {
                    "db_path": "data/p2.db",
                    "max_permission_level": 2,
                    "max_plan_steps": 3,
                    "plan_timeout_sec": 60,
                },
            },
            root=root,
        )
        try:
            os_core.memory_layers.update_profile("name", "Taha")
            reply = os_core.try_handle_command("Ne biliyorsun benim hakkımda?")
            self.assertIsNotNone(reply)
            self.assertIn("Taha", reply or "")
            os_core.memory_layers.record_episodic("Geçici episod notu silinecek xyz")
            forget = os_core.try_handle_command("bunu unut")
            self.assertIsNotNone(forget)
            self.assertIn("unut", (forget or "").lower())
            block = os_core.recall_for_prompt("Taha proje")
            self.assertTrue(
                "LONG-TERM MEMORY" in block or "USER PROFILE" in block
            )
        finally:
            os_core.db.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
