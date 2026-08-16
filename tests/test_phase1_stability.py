"""Phase 1 Stability — open resolve, recovery speech, retries, action miss."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.loader import ensure_jarvis2_defaults
from core.app import JarvisOS
from core.command_router import CommandRouter
from core.execution_engine import ExecutionEngine, ExecutionRequest
from core.event_bus import EventBus
from core.open_target import (
    extract_open_target,
    has_open_verb,
    looks_like_action,
    normalize_open_target,
)
from core.recovery import (
    ErrorClass,
    backoff_seconds,
    classify_error,
    user_safe_speech,
)
from security.audit import AuditLog
from security.confirmation import ConfirmationGate
from security.permissions import PermissionGate, PermissionLevel
from system.macos import MacOSController
from tools.macos_tools import OpenAppTool
from tools.registry import ToolRegistry
from voice.speech_clean import speak_safe


class OpenTargetTests(unittest.TestCase):
    def test_acik_is_not_open_verb(self) -> None:
        self.assertFalse(has_open_verb("açık sekme"))
        self.assertIsNone(extract_open_target("açık sekme neler"))

    def test_chrome_ac_and_acsana(self) -> None:
        self.assertEqual(extract_open_target("chrome aç"), "chrome")
        self.assertEqual(extract_open_target("Chrome'u açsana"), "Chrome")
        self.assertEqual(normalize_open_target("krom"), "chrome")

    def test_open_spotify(self) -> None:
        self.assertEqual(extract_open_target("open Spotify"), "Spotify")
        self.assertEqual(extract_open_target("spotify aç"), "spotify")

    def test_garbage_ik_not_extracted_from_acik(self) -> None:
        # Legacy bug: «açık» → target «ık»
        self.assertNotEqual(
            (extract_open_target("açık sekme") or "").lower(),
            "ık",
        )

    def test_looks_like_action(self) -> None:
        self.assertTrue(looks_like_action("Spotify aç"))
        self.assertFalse(looks_like_action("tell me a joke"))


class RecoverySpeechTests(unittest.TestCase):
    def test_could_not_open_rewritten(self) -> None:
        speech = user_safe_speech("Could not open Chrome", target="Chrome")
        self.assertNotIn("Could not open", speech)
        self.assertIn("Chrome", speech)

    def test_speak_safe_strips_english_open_error(self) -> None:
        out = speak_safe("Could not open ık")
        self.assertNotIn("Could not open", out)

    def test_classify_timeout(self) -> None:
        self.assertEqual(classify_error("command timed out"), ErrorClass.TIMEOUT)

    def test_backoff_grows(self) -> None:
        self.assertEqual(backoff_seconds(0), 0.25)
        self.assertEqual(backoff_seconds(1), 0.5)
        self.assertEqual(backoff_seconds(2), 1.0)


class OpenAppToolTests(unittest.TestCase):
    def test_resolve_chrome_alias(self) -> None:
        c = MacOSController()
        self.assertEqual(c._resolve_app_name("krom"), "Google Chrome")
        self.assertEqual(c._resolve_app_name("chrome"), "Google Chrome")

    def test_open_app_does_not_claim_success_on_failure(self) -> None:
        c = MacOSController()

        def _fail(_name: str, **_kwargs):
            return None

        c._open_app = _fail  # type: ignore[method-assign]
        tool = OpenAppTool(c)
        result = tool.run({"name": "NonexistentAppXYZ"})
        self.assertFalse(result.ok)
        self.assertNotIn("Could not open", result.error or "")
        self.assertTrue(result.error)

    def test_open_app_clarifies_garbage_target(self) -> None:
        tool = OpenAppTool(MacOSController())
        result = tool.run({"name": "ık"})
        self.assertFalse(result.ok)
        self.assertIn("which app", (result.error or "").lower())


class ExecutionRetryTests(unittest.TestCase):
    def test_single_tool_retries_then_safe_speech(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        from memory.database import Database

        db = Database(Path(tmp.name) / "t.db")
        db.migrate()
        registry = ToolRegistry()
        calls = {"n": 0}

        class Flaky(OpenAppTool):
            def run(self, arguments):  # type: ignore[override]
                calls["n"] += 1
                return super().run(arguments)

        controller = MacOSController()
        with patch.object(controller, "_open_app", return_value=None):
            registry.register(Flaky(controller))
            engine = ExecutionEngine(
                registry,
                PermissionGate(PermissionLevel.SYSTEM),
                AuditLog(db),
                EventBus(),
                ConfirmationGate(auto_approve=False),
                tool_max_retries=3,
            )
            # Avoid sleeping in unit tests
            with patch("core.execution_engine.sleep_backoff"):
                result = engine.execute(
                    ExecutionRequest("system.open_app", {"name": "Spotify"})
                )
        self.assertFalse(result.ok)
        self.assertEqual(calls["n"], 3)
        self.assertNotIn("Could not open", result.error or "")


class RouterOpenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_open_spotify(self) -> None:
        m = self.router.route("open Spotify")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "system.open_app")

    def test_acik_sekme_not_open_app(self) -> None:
        m = self.router.route("açık sekme")
        if m is not None:
            self.assertNotEqual(m.request.tool_name, "system.open_app")

    def test_chrome_acsana(self) -> None:
        m = self.router.route("chrome açsana")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "system.open_app")
        name = (m.request.arguments.get("name") or "").lower()
        self.assertIn("chrome", name)
        self.assertNotEqual(name, "ık")


class WorkspaceConfigTests(unittest.TestCase):
    def test_stale_workspace_falls_back_to_repo(self) -> None:
        cfg = ensure_jarvis2_defaults(
            {
                "jarvis": {
                    "workspace": "/Users/mac/Desktop/does-not-exist-jarvis",
                }
            }
        )
        ws = Path(cfg["jarvis"]["workspace"])
        self.assertTrue(ws.exists())
        self.assertTrue((ws / "main.py").exists() or (ws / "config.yaml").exists())


class JarvisOSOpenSpeechTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.os = JarvisOS(
            {
                "jarvis": {"user_name": "Taha", "language": "en-GB"},
                "system": {"full_shell_access": True},
                "jarvis2": {
                    "db_path": "data/p1.db",
                    "max_permission_level": 2,
                    "tool_max_retries": 2,
                },
            },
            root=root,
        )

    def tearDown(self) -> None:
        self.os.close()
        self._tmp.cleanup()

    def test_failed_open_does_not_say_could_not_open(self) -> None:
        with patch.object(self.os.macos, "_open_app", return_value=None):
            with patch("core.execution_engine.sleep_backoff"):
                reply = self.os.try_handle_command("open Spotify")
        self.assertIsNotNone(reply)
        self.assertNotIn("Could not open", reply or "")


if __name__ == "__main__":
    unittest.main()
