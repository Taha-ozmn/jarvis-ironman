"""Phase 5 — confirmation UX + HUD command center data."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from core.app import JarvisOS
from core.execution_engine import ExecutionRequest
from security.confirm_voice import classify_confirmation
from security.confirmation import ConfirmationGate
from security.permissions import PermissionLevel
from ui.hud_data import build_command_center


class ConfirmVoiceTests(unittest.TestCase):
    def test_yes_no(self) -> None:
        self.assertEqual(classify_confirmation("evet"), "yes")
        self.assertEqual(classify_confirmation("yes"), "yes")
        self.assertEqual(classify_confirmation("hayır"), "no")
        self.assertEqual(classify_confirmation("cancel"), "no")
        self.assertIsNone(classify_confirmation("open Spotify"))


class ConfirmationGateTests(unittest.TestCase):
    def test_headless_denies_without_hang(self) -> None:
        gate = ConfirmationGate(default_timeout=30)
        self.assertFalse(gate.require("danger.wipe", "x", level=3))

    def test_interactive_approve_from_other_thread(self) -> None:
        gate = ConfirmationGate(default_timeout=5)
        seen = []

        def on_pending(pending) -> None:
            seen.append(pending.id)

            def _approve() -> None:
                gate.resolve(pending.id, True)

            threading.Timer(0.05, _approve).start()

        gate.set_on_pending(on_pending)
        self.assertTrue(gate.require("system.shell", "rm -rf /tmp/x", level=3))
        self.assertTrue(seen)

    def test_resolve_latest_deny(self) -> None:
        gate = ConfirmationGate(default_timeout=5)
        results = []

        def on_pending(pending) -> None:
            threading.Timer(0.05, lambda: gate.resolve_latest(False)).start()

        gate.set_on_pending(on_pending)

        def worker() -> None:
            results.append(gate.require("danger", "x"))

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=2)
        self.assertEqual(results, [False])


class HudDataTests(unittest.TestCase):
    def test_command_center_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {
                    "jarvis": {"user_name": "Taha"},
                    "jarvis2": {
                        "db_path": "data/hud.db",
                        "automation": True,
                        "max_permission_level": 3,
                    },
                },
                root=Path(tmp),
            )
            os_core.tasks.create("HUD task")
            os_core.memory.create("prefers tea", category="preference")
            os_core.automation.create_rule(
                "Daily",
                trigger_spec={"kind": "daily", "hour": 9, "minute": 0},
                action_spec={"type": "briefing"},
                enabled=True,
            )
            snap = build_command_center(os_core)
            self.assertTrue(snap["available"])
            self.assertGreaterEqual(snap["summary"]["open_tasks"], 1)
            self.assertGreaterEqual(snap["summary"]["active_automations"], 1)
            self.assertTrue(any(t.get("title") == "HUD task" for t in snap["tasks"]))
            self.assertTrue(snap["diagnostics"].get("ok"))
            os_core.close()

    def test_level3_waits_for_hud_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {
                    "jarvis2": {
                        "db_path": "data/c.db",
                        "max_permission_level": 3,
                        "confirm_timeout": 3,
                        "auto_approve_dangerous": False,
                    }
                },
                root=Path(tmp),
            )
            notices = []

            def on_pending(pending) -> None:
                notices.append(pending.to_dict())
                threading.Timer(
                    0.05,
                    lambda: os_core.confirmation.resolve(pending.id, True),
                ).start()

            os_core.set_ui_hooks(on_confirm_pending=on_pending)
            from tools.base import StubTool

            os_core.tools.register(
                StubTool("danger.wipe", "wipe", PermissionLevel.DANGEROUS)
            )
            result = os_core.execution.execute(ExecutionRequest("danger.wipe", {}))
            # Stub returns ok=False but should pass confirmation
            self.assertTrue(notices)
            self.assertIn("stub", (result.error or "").lower())
            os_core.close()


if __name__ == "__main__":
    unittest.main()
