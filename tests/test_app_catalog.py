"""Tests for universal app discovery and open routing."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from core.command_router import CommandRouter
from system.app_catalog import AppCatalog, InstalledApp, _match_score, get_app_catalog
from system.macos import MacOSController
from tools.macos_tools import ListAppsTool, OpenAppTool


class AppCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = AppCatalog()
        self.catalog._apps = [
            InstalledApp("Terminal", Path("/Applications/Utilities/Terminal.app")),
            InstalledApp("Google Chrome", Path("/Applications/Google Chrome.app")),
            InstalledApp("Activity Monitor", Path("/Applications/Utilities/Activity Monitor.app")),
            InstalledApp("WhatsApp", Path("/Applications/WhatsApp.app")),
        ]
        self.catalog._by_name_lower = {a.name.lower(): a for a in self.catalog._apps}
        self.catalog._loaded_at = 999999.0

    def test_exact_resolve(self) -> None:
        hit = self.catalog.resolve("Terminal")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.name, "Terminal")

    def test_alias_resolve(self) -> None:
        hit = self.catalog.resolve("chrome", aliases=MacOSController.APP_ALIASES)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.name, "Google Chrome")

    def test_fuzzy_resolve_whatsapp(self) -> None:
        hit = self.catalog.resolve("whatsapp")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.name, "WhatsApp")

    def test_suggest_near_miss(self) -> None:
        names = self.catalog.suggest("activ", limit=3)
        self.assertIn("Activity Monitor", names)

    def test_match_score_prefix(self) -> None:
        self.assertGreater(_match_score("term", "terminal"), 80.0)


class OpenAppIntegrationTests(unittest.TestCase):
    def test_open_app_resolves_unknown_via_catalog(self) -> None:
        macos = MacOSController()
        fake = InstalledApp("Preview", Path("/Applications/Preview.app"))
        with patch.object(macos._app_catalog, "resolve", return_value=fake):
            with patch("subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = ""
                run.return_value.stderr = ""
                msg = macos._open_app("preview")
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("Preview is open", msg)

    def test_open_app_tool_suggestions_on_failure(self) -> None:
        macos = MacOSController()
        tool = OpenAppTool(macos)
        with patch.object(macos, "_open_app", return_value=None):
            with patch.object(macos._app_catalog, "suggest", return_value=["Terminal", "TextEdit"]):
                result = tool.run({"name": "nopeapp"})
        self.assertFalse(result.ok)
        assert result.error is not None
        self.assertIn("Terminal", result.error)

    def test_list_apps_tool(self) -> None:
        macos = MacOSController()
        tool = ListAppsTool(macos)
        with patch.object(
            macos._app_catalog,
            "list_names",
            return_value=["Terminal", "Finder"],
        ):
            result = tool.run({"limit": 10})
        self.assertTrue(result.ok)
        data = str(result.data)
        self.assertIn("Terminal", data)

    def test_router_bare_whatsapp_not_in_hints(self) -> None:
        router = CommandRouter()
        fake = InstalledApp("WhatsApp", Path("/Applications/WhatsApp.app"))
        with patch("core.command_router.resolve_app_query", return_value=fake):
            match = router.route("whatsapp")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "system.open_app")
        self.assertEqual(match.request.arguments.get("name"), "WhatsApp")

    def test_router_open_verb_resolves_catalog(self) -> None:
        router = CommandRouter()
        fake = InstalledApp("Activity Monitor", Path("/Applications/Utilities/Activity Monitor.app"))
        with patch("core.command_router.resolve_app_query", return_value=fake):
            match = router.route("activity monitor aç")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "system.open_app")
        self.assertEqual(match.request.arguments.get("name"), "activity monitor")

    def test_merged_stt_codeac(self) -> None:
        from core.open_target import extract_merged_open_target

        self.assertEqual(extract_merged_open_target("visual Studio codeac"), "vscode")
        self.assertEqual(extract_merged_open_target("codeac"), "vscode")
        router = CommandRouter()
        match = router.route("visual Studio codeac")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "system.open_app")
        self.assertEqual(match.request.arguments.get("name"), "Visual Studio Code")

    def test_codeac_not_xcode(self) -> None:
        router = CommandRouter()
        match = router.route("codeac")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.arguments.get("name"), "Visual Studio Code")


class CatalogSingletonTests(unittest.TestCase):
    def test_get_app_catalog_singleton(self) -> None:
        a = get_app_catalog()
        b = get_app_catalog()
        self.assertIs(a, b)


if __name__ == "__main__":
    unittest.main()
