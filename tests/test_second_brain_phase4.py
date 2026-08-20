"""Phase 4 — JarvisState, session memory opt-out, request_id audit, latency."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.command_router import CommandRouter
from core.context_manager import ContextManager, SessionContext
from core.jarvis_state import JarvisState
from core.request_context import clear_request_id, get_request_id, set_request_id
from memory.database import Database
from security.audit import AuditLog
from security.confirmation import ConfirmationGate
from security.permissions import PermissionLevel


class JarvisStateTests(unittest.TestCase):
    def test_snapshot_fields(self) -> None:
        ctx = ContextManager(SessionContext(user_name="Taha", language="tr-TR"))
        ctx.update(active_project_id=7)
        ctx.set_extra("active_project_key", "jarvis")
        ctx.set_extra("active_task_id", 3)
        gate = ConfirmationGate(auto_approve=False)
        state = JarvisState(ctx, confirmation=gate)
        snap = state.snapshot(request_id="abc")
        self.assertEqual(snap.active_project_id, 7)
        self.assertEqual(snap.active_project_key, "jarvis")
        self.assertEqual(snap.active_task_id, 3)
        self.assertTrue(snap.memory_capture)
        self.assertEqual(snap.request_id, "abc")
        state.set_memory_capture(False)
        self.assertFalse(state.memory_capture)


class SessionCaptureRouteTests(unittest.TestCase):
    def test_router_skip_memory(self) -> None:
        r = CommandRouter()
        m = r.route("bu konuşmayı hatırlama")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "memory.session_capture")
        self.assertFalse(m.request.arguments.get("enabled"))

    def test_os_skips_ingest(self) -> None:
        from core.app import JarvisOS

        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {
                "jarvis": {"user_name": "Taha", "language": "tr-TR"},
                "jarvis2": {"db_path": "data/p4.db", "max_permission_level": 2},
            },
            root=root,
        )
        try:
            reply = os_core.try_handle_command("bu konuşmayı hatırlama")
            self.assertIsNotNone(reply)
            self.assertIn("kaydetmeyeceğim", (reply or "").lower())
            self.assertFalse(os_core.state.memory_capture)
            ids = os_core.ingest_conversation(
                "Benim favori rengim mavi ve bunu asla unutma lütfen",
                "Tamam",
            )
            self.assertEqual(ids, [])
            # Re-enable
            os_core.try_handle_command("hatırlamaya devam")
            self.assertTrue(os_core.state.memory_capture)
        finally:
            os_core.db.close()
            tmp.cleanup()


class RequestIdAuditTests(unittest.TestCase):
    def test_audit_embeds_request_id(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Database(Path(tmp.name) / "a.db")
            db.migrate()
            audit = AuditLog(db)
            set_request_id("req-phase4")
            audit.write(action="tool.system.time", level=0, success=True, details={"x": 1})
            entry = audit.recent(1)[0]
            details = json.loads(entry.details)
            self.assertEqual(details.get("request_id"), "req-phase4")
            clear_request_id()
            self.assertIsNone(get_request_id())
        finally:
            tmp.cleanup()


class SecurityGateDocTests(unittest.TestCase):
    def test_full_autonomy_false_requires_confirm(self) -> None:
        from core.app import JarvisOS

        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {
                "jarvis": {"language": "tr-TR"},
                "jarvis2": {
                    "db_path": "data/sec.db",
                    "max_permission_level": 3,
                    "full_autonomy": False,
                    "auto_approve_dangerous": False,
                },
            },
            root=root,
        )
        try:
            profile = os_core.security_profile()
            self.assertFalse(profile["full_autonomy"])
            self.assertFalse(profile["auto_approve_dangerous"])
            self.assertIn("confirmation", profile["note"].lower())
            # Level-3 shell should request confirmation, not auto-run
            reply = os_core.try_handle_command("run sudo echo gated")
            self.assertIsNotNone(reply)
            self.assertIn("confirmation", (reply or "").lower())
        finally:
            os_core.db.close()
            tmp.cleanup()


class FastBrainNoAckAssumptionTests(unittest.TestCase):
    """Local tool path must not depend on Cursor readiness."""

    def test_health_is_fast_path(self) -> None:
        from core.brain_router import BrainPath, BrainRouter

        d = BrainRouter().decide("sistem durumu")
        self.assertEqual(d.path, BrainPath.FAST)


if __name__ == "__main__":
    unittest.main()
