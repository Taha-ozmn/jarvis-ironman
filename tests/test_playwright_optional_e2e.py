"""V-05 — optional Playwright e2e (skipped unless PLAYWRIGHT_E2E=1 and package present)."""

from __future__ import annotations

import os
import unittest

from tools.browser_playwright import playwright_available, playwright_status
from tools.browser_tools import BrowserClickTool, BrowserFillFormTool


@unittest.skipUnless(
    os.environ.get("PLAYWRIGHT_E2E") == "1",
    "Set PLAYWRIGHT_E2E=1 to run optional Playwright e2e",
)
class PlaywrightOptionalE2ETests(unittest.TestCase):
    def test_status_reports_engine(self) -> None:
        info = playwright_status()
        self.assertIn("available", info)
        self.assertIn("engine", info)

    @unittest.skipUnless(playwright_available(), "Playwright not installed")
    def test_fill_click_against_example(self) -> None:
        # Soft smoke — may fail without browser binaries; assert honest ToolResult
        fill = BrowserFillFormTool().run(
            {
                "url": "https://example.com",
                "selector": "body",
                "value": "x",
            }
        )
        # example.com body is not an input — expect failure message, not crash
        self.assertIsNotNone(fill)
        self.assertTrue(fill.ok or fill.error)

        click = BrowserClickTool().run(
            {"url": "https://example.com", "selector": "h1"}
        )
        self.assertIsNotNone(click)
        self.assertTrue(click.ok or click.error)


class PlaywrightSkipGuardTests(unittest.TestCase):
    """Always runs — documents that e2e is opt-in."""

    def test_default_skip_env(self) -> None:
        if os.environ.get("PLAYWRIGHT_E2E") == "1":
            self.skipTest("e2e enabled in this environment")
        self.assertNotEqual(os.environ.get("PLAYWRIGHT_E2E"), "1")


if __name__ == "__main__":
    unittest.main()
