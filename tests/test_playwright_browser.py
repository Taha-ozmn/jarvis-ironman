"""Playwright click/fill — mocked when optional package absent."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tools.browser_playwright import (
    playwright_available,
    playwright_click,
    playwright_fill,
    playwright_status,
    set_playwright_impls,
)
from tools.browser_tools import BrowserClickTool, BrowserFillFormTool, browser_diagnostics


class PlaywrightBrowserTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_playwright_impls(click=None, fill=None)

    def test_status_honest_without_package(self) -> None:
        with patch("tools.browser_playwright.playwright_available", return_value=False):
            info = playwright_status()
        self.assertFalse(info["available"])
        self.assertIn("NOT AVAILABLE", info["note"])

    def test_tools_refuse_without_playwright(self) -> None:
        with patch("tools.browser_playwright.playwright_available", return_value=False):
            fill = BrowserFillFormTool().run(
                {"url": "https://example.com", "selector": "#q", "value": "hi"}
            )
            click = BrowserClickTool().run(
                {"url": "https://example.com", "selector": "#go"}
            )
        self.assertFalse(fill.ok)
        self.assertIn("NOT AVAILABLE", fill.error or "")
        self.assertFalse(click.ok)
        self.assertIn("NOT AVAILABLE", click.error or "")

    def test_click_fill_via_injected_impl(self) -> None:
        calls: list[tuple] = []

        def fake_click(url: str, selector: str, *, timeout_ms: int = 10000) -> tuple[bool, str]:
            calls.append(("click", url, selector, timeout_ms))
            return True, f"Clicked {selector}"

        def fake_fill(
            url: str, selector: str, value: str, *, timeout_ms: int = 10000
        ) -> tuple[bool, str]:
            calls.append(("fill", url, selector, value, timeout_ms))
            return True, f"Filled {selector}"

        set_playwright_impls(click=fake_click, fill=fake_fill)
        with patch("tools.browser_playwright.playwright_available", return_value=True):
            click = BrowserClickTool().run(
                {"url": "https://example.com", "selector": "#btn"}
            )
            fill = BrowserFillFormTool().run(
                {
                    "url": "https://example.com",
                    "selector": "#email",
                    "value": "a@b.c",
                }
            )
        self.assertTrue(click.ok, click.error)
        self.assertTrue(fill.ok, fill.error)
        self.assertEqual(calls[0][0], "click")
        self.assertEqual(calls[1][0], "fill")

    def test_diagnostics_structure(self) -> None:
        info = browser_diagnostics()
        self.assertIn("playwright", info)
        self.assertIn("engine", info)
        self.assertIn("note", info)

    def test_direct_helpers_respect_impl(self) -> None:
        set_playwright_impls(
            click=lambda u, s, timeout_ms=10000: (True, "ok-click"),
            fill=lambda u, s, v, timeout_ms=10000: (True, "ok-fill"),
        )
        self.assertEqual(playwright_click("https://x", "#a")[1], "ok-click")
        self.assertEqual(playwright_fill("https://x", "#a", "v")[1], "ok-fill")


if __name__ == "__main__":
    unittest.main()
