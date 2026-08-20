"""Full autonomy permission gate + mail router + catastrophic block tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.app import JarvisOS
from core.command_router import CommandRouter
from core.execution_engine import ExecutionRequest
from security.permissions import PermissionLevel
from security.risk import is_blocked_shell
from tools.mail_tools import MailComposeTool, MailInboxSummaryTool


class MailRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_maillerim_inbox(self) -> None:
        m = self.router.route("maillerim")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "mail.inbox_summary")

    def test_gelen_kutusu(self) -> None:
        m = self.router.route("gelen kutusu")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "mail.inbox_summary")

    def test_e_posta_inbox(self) -> None:
        m = self.router.route("e-posta özet")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "mail.inbox_summary")

    def test_mail_open(self) -> None:
        m = self.router.route("mail aç")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "mail.open")

    def test_compose_with_send(self) -> None:
        m = self.router.route(
            "mail gönder to alice@example.com konu: Merhaba body: Test mesaj"
        )
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "mail.compose")
        self.assertEqual(m.request.arguments.get("to"), "alice@example.com")
        self.assertTrue(m.request.arguments.get("send"))

    def test_screen_tr_routes(self) -> None:
        cap = self.router.route("ekran görüntüsü al")
        self.assertEqual(cap.request.tool_name, "screen.capture")
        desc = self.router.route("ekranda ne var")
        self.assertEqual(desc.request.tool_name, "screen.describe")

    def test_clipboard_and_permissions_routes(self) -> None:
        self.assertEqual(
            self.router.route("panoda ne var").request.tool_name,
            "clipboard.read",
        )
        self.assertEqual(
            self.router.route("izinleri kontrol et").request.tool_name,
            "system.check_permissions",
        )


class MailToolPermissionTests(unittest.TestCase):
    def test_compose_send_is_level3(self) -> None:
        tool = MailComposeTool()
        self.assertEqual(
            tool.resolve_permission({"to": "a@b.com", "send": True}),
            PermissionLevel.DANGEROUS,
        )
        self.assertEqual(
            tool.resolve_permission({"to": "a@b.com", "send": False}),
            PermissionLevel.SYSTEM,
        )

    def test_inbox_mocked(self) -> None:
        tool = MailInboxSummaryTool()
        with patch(
            "tools.mail_tools._osascript",
            return_value=(True, "unread=2\nunread | bob@x.com | Hello\n"),
        ):
            result = tool.run({"limit": 5})
        self.assertTrue(result.ok)
        self.assertIn("unread=2", result.data)


class FullAutonomyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.os = JarvisOS(
            {
                "jarvis": {"user_name": "Taha"},
                "system": {"full_shell_access": True},
                "jarvis2": {
                    "db_path": "data/autonomy.db",
                    "max_permission_level": 3,
                    "full_autonomy": True,
                    "auto_approve_dangerous": True,
                    "auto_approve_level_0_1_2": True,
                },
            },
            root=root,
        )

    def tearDown(self) -> None:
        self.os.close()
        self._tmp.cleanup()

    def test_full_autonomy_enables_confirm_auto_approve(self) -> None:
        self.assertTrue(self.os.full_autonomy)
        self.assertTrue(self.os.confirmation.auto_approve)

    def test_level3_shell_auto_approved_and_audited(self) -> None:
        # Dangerous but not catastrophic — must skip confirm under full_autonomy
        result = self.os.execution.execute(
            ExecutionRequest(
                "system.shell",
                {"command": "rm -rf /tmp/jarvis_autonomy_probe_xyz"},
            )
        )
        self.assertNotIn("confirmation", (result.error or "").lower())
        logs = self.os.audit.recent(limit=20)
        self.assertTrue(
            any(e.action.startswith("autonomy.auto_approve.") for e in logs),
            msg=[e.action for e in logs],
        )
        self.assertTrue(result.ok or "Failed" in (result.data or "") or result.data)

    def test_catastrophic_rm_rf_root_never_auto_approved(self) -> None:
        self.assertTrue(is_blocked_shell("rm -rf /"))
        result = self.os.execution.execute(
            ExecutionRequest("system.shell", {"command": "rm -rf /"})
        )
        self.assertFalse(result.ok)
        self.assertIn("Blocked", result.error or "")
        # Must not claim success via auto-approve path
        self.assertFalse(result.ok)

    def test_disk_erase_blocked(self) -> None:
        self.assertTrue(is_blocked_shell("diskutil eraseDisk JHFS+ Untitled disk2"))
        result = self.os.execution.execute(
            ExecutionRequest(
                "system.shell",
                {"command": "diskutil eraseDisk JHFS+ Untitled disk2"},
            )
        )
        self.assertFalse(result.ok)
        self.assertIn("Blocked", result.error or "")

    def test_tools_registered(self) -> None:
        names = set(self.os.tools.list_names())
        for required in (
            "mail.open",
            "mail.inbox_summary",
            "mail.compose",
            "screen.capture",
            "screen.describe",
            "clipboard.read",
            "clipboard.write",
            "system.notify",
            "system.processes",
            "finder.reveal",
            "system.check_permissions",
            "calendar.list_today",
            "calendar.create_event",
            "github.list_issues",
            "github.list_pulls",
            "github.create_issue",
        ):
            self.assertIn(required, names)


if __name__ == "__main__":
    unittest.main()
