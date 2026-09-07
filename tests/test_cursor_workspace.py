import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.command_router import CommandRouter
from system.macos import MacOSController
from tools.macos_tools import OpenCursorWorkspaceTool


class CursorWorkspaceRoutingTests(unittest.TestCase):
    def setUp(self):
        self.router = CommandRouter()

    def test_new_repo_phrase_routes_to_cursor_workspace(self):
        match = self.router.route("Masaüstünde oluşturduğum dosyayı Cursor'da yeni repo olarak aç")
        self.assertIsNotNone(match)
        self.assertEqual(match.request.tool_name, "cursor.open_workspace")
        self.assertTrue(match.request.arguments["initialize_git"])
        self.assertEqual(match.request.arguments["path"], "")

    def test_misheard_cursor_and_repo_still_route_to_workspace(self):
        match = self.router.route(
            "masaüstündeki zikir dosyasını jours orada yeni rapi olarak"
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.request.tool_name, "cursor.open_workspace")
        self.assertTrue(match.request.arguments["initialize_git"])
        self.assertEqual(match.request.arguments["path"], "zikir")

    def test_english_workspace_phrase_routes_to_cursor_workspace(self):
        match = self.router.route("open the new repository in Cursor")
        self.assertIsNotNone(match)
        self.assertEqual(match.request.tool_name, "cursor.open_workspace")
        self.assertTrue(match.request.arguments["initialize_git"])

    def test_plain_cursor_open_remains_app_open(self):
        match = self.router.route("Cursor aç")
        self.assertIsNotNone(match)
        self.assertEqual(match.request.tool_name, "system.open_app")


class CursorWorkspaceToolTests(unittest.TestCase):
    def test_tool_initializes_git_and_delegates_to_controller(self):
        controller = Mock()
        controller.open_cursor_workspace.return_value = "Opened demo in Cursor as a new Git repository."
        tool = OpenCursorWorkspaceTool(controller)

        result = tool.run({"path": "/tmp/demo", "initialize_git": True})

        self.assertTrue(result.ok)
        controller.open_cursor_workspace.assert_called_once_with(
            "/tmp/demo",
            initialize_git=True,
        )

    def test_controller_reports_missing_workspace(self):
        controller = MacOSController()
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            result = controller.open_cursor_workspace(str(missing))
        self.assertIn("couldn't find", result)


if __name__ == "__main__":
    unittest.main()
