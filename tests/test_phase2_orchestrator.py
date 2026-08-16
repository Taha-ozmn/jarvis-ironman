"""Phase 2 — complexity gate, handle_turn, request_id."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.app import JarvisOS
from core.complexity import (
    TaskComplexity,
    allows_cursor,
    classify_task_complexity,
    local_fallback_speech,
)
from core.request_context import (
    clear_request_id,
    get_request_id,
    set_brain_path,
    set_request_id,
)
from security.audit import AuditLog
from memory.database import Database


class ComplexityTests(unittest.TestCase):
    def test_chat_never_cursor(self) -> None:
        for phrase in ("merhaba", "hello", "thanks", "dinliyor musun"):
            c = classify_task_complexity(phrase)
            self.assertEqual(c, TaskComplexity.CHAT, phrase)
            self.assertFalse(allows_cursor(c), phrase)

    def test_simple_actions_never_cursor(self) -> None:
        for phrase in ("saat kaç", "open Spotify", "chrome aç", "volume up"):
            c = classify_task_complexity(phrase)
            self.assertEqual(c, TaskComplexity.SIMPLE, phrase)
            self.assertFalse(allows_cursor(c), phrase)

    def test_complex_allows_cursor(self) -> None:
        c = classify_task_complexity("bu projede authentication bug'ını fix et")
        self.assertEqual(c, TaskComplexity.COMPLEX)
        self.assertTrue(allows_cursor(c))

    def test_autonomous_plan(self) -> None:
        c = classify_task_complexity("plan and organize my week")
        self.assertEqual(c, TaskComplexity.AUTONOMOUS)
        self.assertTrue(allows_cursor(c))

    def test_medium_research(self) -> None:
        c = classify_task_complexity("JARVIS nedir kısaca anlat")
        self.assertEqual(c, TaskComplexity.MEDIUM)
        self.assertTrue(allows_cursor(c))


class RequestContextTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_request_id()

    def test_set_get_clear(self) -> None:
        rid = set_request_id("abc123def456")
        self.assertEqual(rid, "abc123def456")
        self.assertEqual(get_request_id(), "abc123def456")
        clear_request_id()
        self.assertIsNone(get_request_id())

    def test_audit_embeds_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "a.db")
            db.migrate()
            audit = AuditLog(db)
            set_request_id("req_test_01")
            set_brain_path("fast")
            audit.write(action="probe", level=0, success=True, details={"x": 1})
            entry = audit.recent(1)[0]
            details = json.loads(entry.details)
            self.assertEqual(details["request_id"], "req_test_01")
            self.assertEqual(details["brain_path"], "fast")
            clear_request_id()


class HandleTurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.os = JarvisOS(
            {
                "jarvis": {"user_name": "Taha", "language": "en-GB"},
                "system": {"full_shell_access": True},
                "jarvis2": {
                    "db_path": "data/p2.db",
                    "max_permission_level": 2,
                    "tool_max_retries": 1,
                },
            },
            root=root,
        )

    def tearDown(self) -> None:
        self.os.close()
        self._tmp.cleanup()
        clear_request_id()

    def test_time_is_fast_no_cursor(self) -> None:
        turn = self.os.handle_turn("saat kaç")
        self.assertTrue(turn.handled)
        self.assertFalse(turn.allow_cursor)
        self.assertEqual(turn.brain_path, "fast")
        self.assertTrue((turn.speech or "").startswith("It's "))
        self.assertEqual(turn.complexity, TaskComplexity.SIMPLE)

    def test_chat_blocked_without_meta(self) -> None:
        turn = self.os.handle_turn("xyzzy_unknown_chat_only")
        # Unknown short-ish may be MEDIUM; force chat-like greeting miss path
        turn = self.os.handle_turn(
            "merhaba",
            meta_fn=lambda _c: None,
            quick_fn=lambda _c: None,
        )
        self.assertFalse(turn.allow_cursor)
        self.assertEqual(turn.complexity, TaskComplexity.CHAT)
        self.assertIsNotNone(turn.speech)
        self.assertEqual(turn.brain_path, "blocked")

    def test_chat_with_meta(self) -> None:
        turn = self.os.handle_turn(
            "merhaba",
            meta_fn=lambda _c: "Good evening.",
        )
        self.assertEqual(turn.speech, "Good evening.")
        self.assertFalse(turn.allow_cursor)
        self.assertEqual(turn.brain_path, "meta")

    def test_simple_miss_clarifies_not_cursor(self) -> None:
        turn = self.os.handle_turn(
            "open NonexistentAppXYZ123",
            legacy_fn=lambda _c: None,
        )
        self.assertEqual(turn.complexity, TaskComplexity.SIMPLE)
        self.assertFalse(turn.allow_cursor)
        # Either tool failure speech or gate fallback — never deep
        self.assertNotEqual(turn.brain_path, "deep")
        self.assertIsNotNone(turn.speech)

    def test_complex_allows_deep_fallback(self) -> None:
        turn = self.os.handle_turn(
            "refactor the authentication module and add tests",
            meta_fn=lambda _c: None,
            legacy_fn=lambda _c: None,
        )
        self.assertTrue(turn.allow_cursor)
        self.assertIsNone(turn.speech)
        self.assertEqual(turn.brain_path, "deep")
        self.assertEqual(turn.complexity, TaskComplexity.COMPLEX)

    def test_legacy_callback_used(self) -> None:
        turn = self.os.handle_turn(
            "open SomethingOdd",
            legacy_fn=lambda _c: "Opened via legacy.",
        )
        # May match tool first; if tool fails/opens, still not cursor
        if turn.brain_path == "legacy":
            self.assertEqual(turn.speech, "Opened via legacy.")
        self.assertFalse(turn.allow_cursor)

    def test_turn_audit_has_request_id(self) -> None:
        turn = self.os.handle_turn("what time is it")
        logs = self.os.audit.recent(5)
        classified = [e for e in logs if e.action == "turn.classified"]
        self.assertTrue(classified)
        details = json.loads(classified[0].details)
        self.assertEqual(details["request_id"], turn.request_id)


class LocalFallbackTests(unittest.TestCase):
    def test_fallback_copy(self) -> None:
        self.assertIn("Hello", local_fallback_speech(TaskComplexity.CHAT))
        self.assertIn("locally", local_fallback_speech(TaskComplexity.SIMPLE, "open x"))


if __name__ == "__main__":
    unittest.main()
