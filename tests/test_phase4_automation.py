"""Phase 4 — automation, briefing, memory extraction tests."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from automation.engine import AutomationEngine
from automation.parser import parse_automation_nl
from automation.triggers import should_fire
from core.app import JarvisOS
from core.command_router import CommandRouter
from core.execution_engine import ExecutionRequest
from memory.extractor import extract_and_save, extract_memories, looks_like_secret
from proactive.briefing import BriefingGenerator
from proactive.notifier import NotificationPolicy, ProactiveNotifier
from security.permissions import PermissionLevel


class TriggerMatchingTests(unittest.TestCase):
    def test_daily_match(self) -> None:
        spec = {"kind": "daily", "hour": 9, "minute": 0}
        now = datetime(2026, 8, 13, 9, 0, 0)
        self.assertTrue(should_fire(spec, now))
        self.assertFalse(should_fire(spec, now, last_fired_at="2026-08-13T09:00"))
        self.assertFalse(should_fire(spec, datetime(2026, 8, 13, 9, 1, 0)))

    def test_weekly_match(self) -> None:
        # 2026-08-13 is Thursday (weekday=3)
        spec = {"kind": "weekly", "weekday": 3, "hour": 18, "minute": 30}
        self.assertTrue(should_fire(spec, datetime(2026, 8, 13, 18, 30)))
        self.assertFalse(should_fire(spec, datetime(2026, 8, 14, 18, 30)))

    def test_interval(self) -> None:
        spec = {"kind": "interval", "every_minutes": 30}
        self.assertTrue(should_fire(spec, datetime(2026, 8, 13, 10, 0)))
        self.assertFalse(should_fire(spec, datetime(2026, 8, 13, 10, 15)))


class AutomationNLParseTests(unittest.TestCase):
    def test_every_morning(self) -> None:
        p = parse_automation_nl("every morning give me a briefing")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.trigger_spec["kind"], "daily")
        self.assertEqual(p.trigger_spec["hour"], 9)
        self.assertEqual(p.action_spec["type"], "briefing")

    def test_her_pazartesi(self) -> None:
        p = parse_automation_nl("her pazartesi saat 10 görevleri hatırlat")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.trigger_spec["kind"], "weekly")
        self.assertEqual(p.trigger_spec["weekday"], 0)
        self.assertEqual(p.trigger_spec["hour"], 10)

    def test_at_time_remind(self) -> None:
        p = parse_automation_nl("at 18:00 remind me of my tasks")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.trigger_spec["hour"], 18)
        self.assertEqual(p.action_spec["type"], "remind_tasks")

    def test_non_schedule(self) -> None:
        self.assertIsNone(parse_automation_nl("open Spotify"))


class AutomationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        from memory.database import Database

        self.db = Database(Path(self._tmp.name) / "a.db")
        self.db.migrate()
        self.engine = AutomationEngine(
            self.db,
            enabled=True,
            tick_seconds=5,
            max_failures=2,
        )
        self.speeches: list[str] = []

        def handler(action, rule):
            msg = f"{rule.name}:{action.get('type')}"
            self.speeches.append(msg)
            return msg

        self.engine.set_action_handler(handler)

    def tearDown(self) -> None:
        self.engine.stop()
        self.db.close()
        self._tmp.cleanup()

    def test_crud_and_tick(self) -> None:
        rid = self.engine.create_rule(
            "Morning",
            trigger_type="daily",
            trigger_spec={"kind": "daily", "hour": 8, "minute": 15},
            action_spec={"type": "briefing"},
            enabled=True,
        )
        self.assertEqual(self.engine.rule_count(), 1)
        fired = self.engine.tick(now=datetime(2026, 8, 13, 8, 15, 0))
        self.assertEqual(len(fired), 1)
        self.assertTrue(fired[0]["ok"])
        # Same minute should not re-fire
        fired2 = self.engine.tick(now=datetime(2026, 8, 13, 8, 15, 30))
        self.assertEqual(len(fired2), 0)
        self.engine.set_enabled(rid, False)
        self.assertFalse(self.engine.get_rule(rid).enabled)
        self.engine.delete_rule(rid)
        self.assertEqual(self.engine.rule_count(), 0)

    def test_max_failures_stops_loop(self) -> None:
        def boom(action, rule):
            raise RuntimeError("fail")

        self.engine.set_action_handler(boom)
        rid = self.engine.create_rule(
            "Bad",
            trigger_type="daily",
            trigger_spec={"kind": "daily", "hour": 7, "minute": 0},
            action_spec={"type": "speak", "text": "x"},
            enabled=True,
        )
        self.engine.tick(now=datetime(2026, 8, 13, 7, 0))
        self.engine.tick(now=datetime(2026, 8, 14, 7, 0))
        rule = self.engine.get_rule(rid)
        self.assertGreaterEqual(rule.fail_count, 2)
        # Third day — skipped due to max_failures
        fired = self.engine.tick(now=datetime(2026, 8, 15, 7, 0))
        self.assertEqual(fired, [])

    def test_create_from_nl(self) -> None:
        rule = self.engine.create_from_nl("every morning briefing")
        self.assertIsNotNone(rule)
        assert rule is not None
        self.assertIn("Daily", rule.name)


class NotifierTests(unittest.TestCase):
    def test_quiet_hours_and_rate_limit(self) -> None:
        policy = NotificationPolicy(
            quiet_hours_start=22,
            quiet_hours_end=7,
            min_interval_seconds=60,
            max_per_hour=2,
        )
        n = ProactiveNotifier(policy)
        quiet = datetime(2026, 8, 13, 23, 0)
        self.assertTrue(n.in_quiet_hours(quiet))
        self.assertFalse(n.allow(now=quiet))
        day = datetime(2026, 8, 13, 10, 0)
        self.assertTrue(n.allow(now=day, force=True))


class BriefingTests(unittest.TestCase):
    def test_generate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from memory.database import Database
            from memory.repository import MemoryRepository
            from core.task_manager import TaskManager

            db = Database(Path(tmp) / "b.db")
            db.migrate()
            tasks = TaskManager(db)
            memory = MemoryRepository(db)
            tasks.create("Ship Phase 4", priority=2)
            memory.create("Prefers British accent", category="preference")
            gen = BriefingGenerator(tasks, memory, db, user_name="Taha", language="en")
            briefing = gen.generate()
            self.assertIn("Briefing", briefing.voice)
            self.assertIn("Ship Phase 4", briefing.detail)
            db.close()


class MemoryExtractionTests(unittest.TestCase):
    def test_preference_and_secret_skip(self) -> None:
        items = extract_memories("I prefer British accent")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].category, "preference")
        self.assertTrue(looks_like_secret("password: hunter2"))
        self.assertEqual(extract_memories("my password: hunter2"), [])

    def test_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from memory.database import Database
            from memory.repository import MemoryRepository

            db = Database(Path(tmp) / "m.db")
            db.migrate()
            repo = MemoryRepository(db)
            ids = extract_and_save(repo, "I'm working on jarvis-ironman")
            self.assertTrue(ids)
            hits = repo.search("jarvis")
            self.assertTrue(hits)
            db.close()


class Phase4RouterIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.os = JarvisOS(
            {
                "jarvis": {"user_name": "Taha", "language": "en-GB"},
                "jarvis2": {
                    "db_path": "data/p4.db",
                    "automation": True,
                    "max_permission_level": 2,
                    "proactive": {"enabled": True, "min_interval_seconds": 0},
                },
            },
            root=root,
        )
        self.spoken: list[str] = []
        self.os.set_speak_callback(lambda t: self.spoken.append(t))

    def tearDown(self) -> None:
        self.os.close()
        self._tmp.cleanup()

    def test_router_automation_and_briefing(self) -> None:
        router = CommandRouter()
        m = router.route("every morning briefing")
        self.assertEqual(m.request.tool_name, "automation.create")
        m2 = router.route("daily briefing")
        self.assertEqual(m2.request.tool_name, "proactive.briefing")
        m3 = router.route("list automations")
        self.assertEqual(m3.request.tool_name, "automation.list")

    def test_create_list_disable_via_os(self) -> None:
        reply = self.os.try_handle_command("every morning give me a briefing")
        self.assertIn("Automation", reply or "")
        listed = self.os.try_handle_command("list automations")
        self.assertIn("Daily", listed or "")
        rules = self.os.automation.list_rules()
        self.assertTrue(rules)
        rid = rules[0].id
        disabled = self.os.try_handle_command(f"disable automation {rid}")
        self.assertIn("disabled", (disabled or "").lower())

    def test_briefing_tool(self) -> None:
        self.os.tasks.create("Review Phase 4")
        reply = self.os.try_handle_command("briefing")
        self.assertIsNotNone(reply)
        self.assertTrue("Briefing" in (reply or "") or "open" in (reply or "").lower())

    def test_automation_delete_requires_system_permission(self) -> None:
        self.os.permissions.max_level = PermissionLevel.LOCAL
        rid = self.os.automation.create_rule(
            "X",
            trigger_spec={"kind": "daily", "hour": 9, "minute": 0},
            action_spec={"type": "briefing"},
        )
        result = self.os.execution.execute(
            ExecutionRequest("automation.delete", {"rule_id": rid})
        )
        self.assertFalse(result.ok)
        self.assertIn("Permission denied", result.error or "")

    def test_tick_fires_and_audits(self) -> None:
        rid = self.os.automation.create_rule(
            "Noon",
            trigger_spec={"kind": "daily", "hour": 12, "minute": 0},
            action_spec={"type": "speak", "text": "Hello from automation", "force": True},
        )
        fired = self.os.automation.tick(now=datetime(2026, 8, 13, 12, 0, 0))
        self.assertEqual(len(fired), 1)
        self.assertTrue(any("Hello" in s for s in self.spoken) or fired[0].get("speech"))
        logs = self.os.audit.recent(20)
        self.assertTrue(any(e.action == "automation.fire" for e in logs))
        _ = rid


if __name__ == "__main__":
    unittest.main()
