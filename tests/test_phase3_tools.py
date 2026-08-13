"""Phase 3 — command router + real tool wiring tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.app import JarvisOS
from core.command_router import CommandRouter
from core.execution_engine import ExecutionRequest
from security.permissions import PermissionLevel
from security.risk import is_dangerous_shell


class CommandRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_open_app(self) -> None:
        m = self.router.route("open Spotify")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "system.open_app")
        self.assertEqual(m.request.arguments["name"].lower(), "spotify")

    def test_time(self) -> None:
        m = self.router.route("saat kaç")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "system.time")

    def test_memory_save(self) -> None:
        m = self.router.route("remember that Taha prefers British accent")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "memory.save")
        self.assertIn("British", m.request.arguments["content"])

    def test_task_create_and_list(self) -> None:
        m = self.router.route("add task Buy milk")
        self.assertEqual(m.request.tool_name, "task.create")
        m2 = self.router.route("list tasks")
        self.assertEqual(m2.request.tool_name, "task.list")

    def test_task_complete(self) -> None:
        m = self.router.route("complete task 3")
        self.assertEqual(m.request.tool_name, "task.complete")
        self.assertEqual(m.request.arguments["task_id"], 3)

    def test_shell(self) -> None:
        m = self.router.route("run echo hello")
        self.assertEqual(m.request.tool_name, "system.shell")
        self.assertEqual(m.request.arguments["command"], "echo hello")

    def test_fallthrough_chat(self) -> None:
        self.assertIsNone(self.router.route("tell me a joke about iron man"))


class RiskTests(unittest.TestCase):
    def test_dangerous_shell(self) -> None:
        self.assertTrue(is_dangerous_shell("sudo rm -rf /"))
        self.assertTrue(is_dangerous_shell("rm -rf ~/Projects"))
        self.assertFalse(is_dangerous_shell("echo hello"))


class Phase3IntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.os = JarvisOS(
            {
                "jarvis": {"user_name": "Taha"},
                "system": {"full_shell_access": True},
                "jarvis2": {
                    "db_path": "data/p3.db",
                    "max_permission_level": 2,
                    "auto_approve_dangerous": False,
                },
            },
            root=root,
        )

    def tearDown(self) -> None:
        self.os.close()
        self._tmp.cleanup()

    def test_real_memory_and_task_tools(self) -> None:
        reply = self.os.try_handle_command("remember that favourite drink is tea")
        self.assertIsNotNone(reply)
        self.assertIn("Noted", reply or "")
        found = self.os.try_handle_command("search memory drink")
        self.assertIn("tea", (found or "").lower())
        created = self.os.try_handle_command("add task Phase 3 verify")
        self.assertIn("created", (created or "").lower())
        listed = self.os.try_handle_command("list tasks")
        self.assertIn("Phase 3", listed or "")

    def test_time_tool(self) -> None:
        reply = self.os.try_handle_command("what time is it")
        self.assertIsNotNone(reply)
        self.assertTrue((reply or "").startswith("It's "))

    def test_shell_safe_and_audited(self) -> None:
        reply = self.os.try_handle_command("run echo jarvis-p3")
        self.assertIsNotNone(reply)
        self.assertIn("jarvis-p3", reply or "")
        logs = self.os.audit.recent(limit=5)
        self.assertTrue(any(e.action == "tool.system.shell" for e in logs))

    def test_dangerous_shell_denied_without_level3(self) -> None:
        reply = self.os.try_handle_command("run sudo rm -rf /tmp/nope")
        self.assertIn("Permission denied", reply or "")

    def test_dangerous_shell_needs_confirm_at_level3(self) -> None:
        self.os.permissions.max_level = PermissionLevel.DANGEROUS
        reply = self.os.try_handle_command("run sudo echo x")
        self.assertIn("confirmation", (reply or "").lower())

    def test_fs_list_home(self) -> None:
        reply = self.os.try_handle_command("list files")
        self.assertIsNotNone(reply)
        self.assertTrue(
            "Contents" in (reply or "") or "empty" in (reply or "").lower()
        )

    def test_memory_recall_relevant(self) -> None:
        self.os.memory.create("Taha prefers British accent", category="preference")
        self.os.memory.create("Project jarvis-ironman on Desktop", category="project")
        block = self.os.recall_for_prompt("What accent does Taha prefer?")
        self.assertIn("LONG-TERM MEMORY", block)
        self.assertIn("British", block)
        # Unrelated query should not dump everything if no keyword hits
        empty = self.os.recall_for_prompt("xyzzy unrelated quux")
        self.assertEqual(empty, "")

    def test_open_app_tool_registered(self) -> None:
        tool = self.os.tools.get("system.open_app")
        self.assertIsNotNone(tool)
        # Don't actually launch GUI apps in CI — just ensure execute path works with empty fail
        result = self.os.execution.execute(
            ExecutionRequest("system.open_app", {"name": ""})
        )
        self.assertFalse(result.ok)

    def test_browser_fill_form_not_implemented(self) -> None:
        result = self.os.execution.execute(
            ExecutionRequest(
                "browser.fill_form",
                {"url": "https://example.com", "selector": "#x", "value": "y"},
            )
        )
        self.assertFalse(result.ok)
        err = (result.error or "").lower()
        self.assertTrue("playwright" in err or "not implemented" in err, result.error)

    def test_browser_open_url_registered(self) -> None:
        self.assertIn("browser.open_url", self.os.tools.list_names())
        self.assertIn("browser.get_page_text", self.os.tools.list_names())


if __name__ == "__main__":
    unittest.main()
