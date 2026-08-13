"""Optional Playwright helpers — lazy import; never required at startup.

Click/fill are real when Playwright (+ browser binaries) are installed.
Without Playwright: callers must report honest NOT AVAILABLE.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

# Test hooks — inject fakes without importing real Playwright
_ClickFn = Callable[..., tuple[bool, str]]
_FillFn = Callable[..., tuple[bool, str]]
_click_impl: Optional[_ClickFn] = None
_fill_impl: Optional[_FillFn] = None


def set_playwright_impls(
    *,
    click: Optional[_ClickFn] = None,
    fill: Optional[_FillFn] = None,
) -> None:
    """Override click/fill (tests). Pass None to restore defaults."""
    global _click_impl, _fill_impl
    _click_impl = click
    _fill_impl = fill


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except Exception:
        return False


def playwright_status() -> dict[str, Any]:
    if not playwright_available():
        return {
            "available": False,
            "engine": "urllib+open",
            "note": (
                "Playwright NOT AVAILABLE. "
                "Optional: pip install -r requirements-optional.txt && playwright install chromium"
            ),
        }
    return {
        "available": True,
        "engine": "playwright",
        "note": "Playwright import OK — browser binaries may still be missing",
    }


def playwright_click(url: str, selector: str, *, timeout_ms: int = 10000) -> tuple[bool, str]:
    """Click an element. Returns (ok, message). Lazy-imports Playwright."""
    if _click_impl is not None:
        return _click_impl(url, selector, timeout_ms=timeout_ms)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as err:
        return False, f"Playwright NOT AVAILABLE: {err}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms)
            page.click(selector, timeout=timeout_ms)
            browser.close()
        return True, f"Clicked {selector} on {url}"
    except Exception as err:
        return False, f"Playwright click failed: {err}"


def playwright_fill(
    url: str,
    selector: str,
    value: str,
    *,
    timeout_ms: int = 10000,
) -> tuple[bool, str]:
    if _fill_impl is not None:
        return _fill_impl(url, selector, value, timeout_ms=timeout_ms)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as err:
        return False, f"Playwright NOT AVAILABLE: {err}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms)
            page.fill(selector, value, timeout=timeout_ms)
            browser.close()
        return True, f"Filled {selector} on {url}"
    except Exception as err:
        return False, f"Playwright fill failed: {err}"
