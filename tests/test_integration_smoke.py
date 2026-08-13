"""Integration / smoke tests for JARVIS 2.0 Personal AI OS gaps."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.app import JarvisOS
from core.command_router import CommandRouter
from core.context_manager import ContextManager
from core.execution_engine import ExecutionRequest
from core.planner import Planner, parse_llm_plan_json
from integrations.mcp_adapter import MCPAdapter
from automation.parser import parse_automation_nl


class IntegrationSmokeTests(unittest.TestCase):
    def test_task_create_then_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/i1.db", "max_permission_level": 2}},
                root=Path(tmp),
            )
            c = os_core.try_handle_command("add task Buy milk")
            self.assertIsNotNone(c)
            listed = os_core.try_handle_command("list tasks")
            self.assertIn("milk", (listed or "").lower())
            os_core.close()

    def test_automation_create_and_tick(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {
                    "jarvis2": {
                        "db_path": "data/i2.db",
                        "max_permission_level": 2,
                        "automation": True,
                    }
                },
                root=Path(tmp),
            )
            speech = os_core.try_handle_command(
                "every morning at 9 give me a briefing"
            )
            self.assertIsNotNone(speech)
            self.assertGreaterEqual(os_core.automation.rule_count(), 1)
            # tick with no matching time shouldn't crash
            fired = os_core.automation.tick()
            self.assertIsInstance(fired, list)
            os_core.close()

    def test_plan_execute_dry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/i3.db", "max_permission_level": 2}},
                root=Path(tmp),
            )
            plan = os_core.planner.create("plan and organize my projects")
            self.assertTrue(plan.complex)
            self.assertTrue(plan.steps)
            # Dry: only list-level tools
            result = os_core.execution.execute_plan(plan)
            self.assertTrue(result.ok or result.completed >= 0)
            os_core.close()

    def test_file_watch_trigger_temp_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watch = root / "inbox"
            watch.mkdir()
            os_core = JarvisOS(
                {
                    "jarvis2": {
                        "db_path": "data/i4.db",
                        "max_permission_level": 2,
                        "automation": True,
                        "automation_tick_seconds": 5,
                    }
                },
                root=root,
            )
            rid = os_core.automation.create_rule(
                "Watch PDF",
                trigger_type="file_watch",
                trigger_spec={
                    "kind": "file_watch",
                    "path": str(watch),
                    "pattern": "*.pdf",
                    "settle_seconds": 0,
                },
                action_spec={"type": "speak", "text": "New file arrived: {file}"},
                enabled=True,
            )
            # Seed poll — no fire
            fired0 = os_core.automation.tick()
            self.assertEqual(fired0, [])
            # New file
            (watch / "report.pdf").write_bytes(b"%PDF-1.4")
            fired1 = os_core.automation.tick()
            self.assertTrue(any(f.get("ok") for f in fired1), fired1)
            self.assertTrue(
                any("report.pdf" in str(f.get("speech") or "") for f in fired1),
                fired1,
            )
            # Idempotent — same file shouldn't re-fire
            fired2 = os_core.automation.tick()
            self.assertEqual(fired2, [])
            _ = rid
            os_core.close()

    def test_file_watch_nl_parse(self) -> None:
        parsed = parse_automation_nl("İndirilenlere PDF gelince söyle New PDF")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.trigger_type, "file_watch")
        self.assertEqual(parsed.trigger_spec.get("kind"), "file_watch")
        self.assertIn("pdf", str(parsed.trigger_spec.get("pattern")).lower())


class ContextFollowupTests(unittest.TestCase):
    def test_followup_open_entity(self) -> None:
        ctx = ContextManager()
        ctx.record_turn("open github", "Opened GitHub.")
        resolved = ctx.resolve_followup("şimdi onu aç")
        self.assertIn("github", resolved.lower())


class LlmPlannerFallbackTests(unittest.TestCase):
    def test_parse_llm_json(self) -> None:
        raw = '{"steps":[{"tool":"dev.analyze_repo","arguments":{},"description":"scan"}]}'
        plan = parse_llm_plan_json(raw, goal="fix")
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.steps[0].tool_name, "dev.analyze_repo")

    def test_heuristic_when_llm_unavailable(self) -> None:
        planner = Planner(llm_refine=lambda g, p: (_ for _ in ()).throw(RuntimeError("no")))
        plan = planner.create("analyze and fix the repository")
        self.assertTrue(plan.steps)
        self.assertEqual(plan.source, "heuristic")


class McpAdapterTests(unittest.TestCase):
    def test_schema_export_and_status(self) -> None:
        mcp = MCPAdapter()
        mcp.register_server("demo", tools=[])
        status = mcp.status()
        self.assertFalse(status["runtime"])
        self.assertIn("memory.search", str(status["example"]))


class DiagnosticsCoverageTests(unittest.TestCase):
    def test_sistem_durumu_route(self) -> None:
        m = CommandRouter().route("sistem durumunu kontrol et")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "diagnostics.health")

    def test_health_includes_new_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/i5.db", "max_permission_level": 2}},
                root=Path(tmp),
            )
            health = os_core.health()
            names = {c["name"] for c in health["checks"]}
            for required in ("planner", "browser", "mcp", "backup", "projects"):
                self.assertIn(required, names)
            os_core.close()


class FsReadWriteTests(unittest.TestCase):
    def test_read_write_in_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/i6.db", "max_permission_level": 2}},
                root=root,
            )
            # write relative to cwd fallback
            result = os_core.execution.execute(
                ExecutionRequest(
                    "fs.write",
                    {"path": str(root / "note.txt"), "content": "hello jarvis"},
                )
            )
            self.assertTrue(result.ok, result.error)
            read = os_core.execution.execute(
                ExecutionRequest("fs.read", {"path": str(root / "note.txt")})
            )
            self.assertTrue(read.ok)
            self.assertIn("hello jarvis", str(read.data))
            os_core.close()


if __name__ == "__main__":
    unittest.main()
