"""Unit tests for JarvisOS soft-init + diagnostics."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.app import JarvisOS, try_create_os
from core.execution_engine import ExecutionEngine, ExecutionRequest
from security.permissions import PermissionLevel


class JarvisOSTests(unittest.TestCase):
    def test_os_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            os_core = JarvisOS(
                {
                    "jarvis": {"user_name": "Taha", "language": "tr-TR"},
                    "jarvis2": {
                        "enabled": True,
                        "db_path": "data/test.db",
                        "max_permission_level": 2,
                    },
                },
                root=root,
            )
            health = os_core.health()
            self.assertTrue(health["ok"], health)
            self.assertGreaterEqual(health["passed"], 7)
            os_core.close()

    def test_try_create_disabled(self) -> None:
        result = try_create_os({"jarvis2": {"enabled": False}})
        self.assertIsNone(result)

    def test_execution_permission_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os_core = JarvisOS(
                {
                    "jarvis2": {
                        "db_path": "data/t.db",
                        "max_permission_level": 0,
                    }
                },
                root=root,
            )
            engine: ExecutionEngine = os_core.execution
            result = engine.execute(
                ExecutionRequest("system.shell", {"command": "echo hi"})
            )
            self.assertFalse(result.ok)
            self.assertIn("Permission denied", result.error or "")
            os_core.close()

    def test_dangerous_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os_core = JarvisOS(
                {
                    "jarvis2": {
                        "db_path": "data/t.db",
                        "max_permission_level": 3,
                        "auto_approve_dangerous": False,
                    }
                },
                root=root,
            )
            from tools.base import StubTool

            os_core.tools.register(
                StubTool("danger.wipe", "danger", PermissionLevel.DANGEROUS)
            )
            result = os_core.execution.execute(ExecutionRequest("danger.wipe", {}))
            self.assertFalse(result.ok)
            self.assertIn("confirmation", (result.error or "").lower())
            os_core.close()


if __name__ == "__main__":
    unittest.main()
