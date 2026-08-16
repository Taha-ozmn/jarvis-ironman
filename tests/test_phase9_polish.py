"""U-03 / V-04 / production — confirm payload, playwright verify, health fields."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from core.app import JarvisOS
from core.degraded import get_degraded_mode
from core.verification import should_verify, verify_tool_result
from security.confirmation import ConfirmationGate
from tools.base import ToolResult


class ConfirmPayloadTests(unittest.TestCase):
    def test_to_dict_includes_timeout(self) -> None:
        gate = ConfirmationGate(default_timeout=12)
        seen: list = []

        def on_pending(p) -> None:
            seen.append(p.to_dict())
            gate.resolve(p.id, False)

        gate.set_on_pending(on_pending)
        t = threading.Thread(target=lambda: gate.require("wipe", "tmp", timeout=12))
        t.start()
        t.join(timeout=2)
        self.assertTrue(seen)
        self.assertIn("timeout", seen[0])
        self.assertEqual(seen[0]["timeout"], 12.0)
        self.assertIn("remaining", seen[0])


class PlaywrightVerifyTests(unittest.TestCase):
    def test_should_verify_playwright_tools(self) -> None:
        self.assertTrue(should_verify("browser.fill_form"))
        self.assertTrue(should_verify("browser.click"))

    def test_verify_fill_ok(self) -> None:
        outcome = verify_tool_result(
            "browser.fill_form",
            {"url": "https://example.com", "selector": "#email", "value": "a"},
            ToolResult(ok=True, data="Filled #email on https://example.com"),
        )
        self.assertTrue(outcome.ok)

    def test_verify_click_empty_fails(self) -> None:
        outcome = verify_tool_result(
            "browser.click",
            {"url": "https://example.com", "selector": "#go"},
            ToolResult(ok=True, data=""),
        )
        self.assertFalse(outcome.ok)


class ProductionHealthTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_degraded_mode().exit()

    def test_health_includes_ready_and_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/prod.db"}},
                root=Path(tmp),
            )
            try:
                health = os_core.health()
                self.assertTrue(health["ok"], health)
                self.assertTrue(health.get("ready"))
                self.assertFalse(health.get("degraded"))
                names = {c["name"] for c in health["checks"]}
                self.assertIn("execution", names)
                self.assertIn("degraded_mode", names)
            finally:
                os_core.close()

    def test_degraded_marks_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/prod2.db"}},
                root=Path(tmp),
            )
            try:
                os_core.enter_degraded_mode("test")
                health = os_core.health()
                self.assertTrue(health.get("degraded"))
                self.assertFalse(health["ok"])
            finally:
                get_degraded_mode().exit()
                os_core.close()


if __name__ == "__main__":
    unittest.main()
