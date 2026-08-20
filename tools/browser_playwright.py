"""Optional Playwright helpers — lazy import; never required at startup with connection recovery.

Click/fill are real when Playwright (+ browser binaries) are installed.
Without Playwright: callers must report honest NOT AVAILABLE.
"""

from __future__ import annotations

import platform
import random
import re
import time
from typing import Any, Callable, Optional

from core.connection_recovery import connection_recovery, ConnectionType

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


def _macos_major() -> Optional[int]:
    if platform.system() != "Darwin":
        return None
    ver = platform.mac_ver()[0] or ""
    m = re.match(r"^(\d+)", ver)
    return int(m.group(1)) if m else None


def playwright_install_hint() -> str:
    """Turkish-aware install hint (Monterey needs Playwright <1.62)."""
    base = "pip install -r requirements-optional.txt && playwright install chromium"
    major = _macos_major()
    if major is not None and major < 13:
        return (
            f"{base}. "
            "macOS 12 (Monterey): Playwright 1.62+ chromium desteklemez; "
            "requirements-optional.txt pin'i (<1.62, örn. 1.61.0) kullanın."
        )
    return f"{base}."


def _chromium_executable_ok() -> tuple[bool, str]:
    """Resolve chromium path without navigating pages (diagnostics only)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as err:
        return False, str(err)
    try:
        with sync_playwright() as p:
            path = p.chromium.executable_path
        if path:
            return True, path
        return False, "chromium executable_path boş"
    except Exception as err:
        return False, str(err)


def _format_pw_error(err: BaseException) -> str:
    text = str(err)
    low = text.lower()
    if "does not support" in low and "mac12" in low:
        return (
            "Chromium bu macOS 12 (Monterey) + Playwright sürümünde desteklenmiyor. "
            "Playwright <1.62 kurun (requirements-optional.txt) veya macOS 13+ yükseltin. "
            f"Detay: {text}"
        )
    if "executable doesn't exist" in low or "browserType.launch" in low:
        return (
            "Playwright yüklü ama chromium binary eksik/bozuk. "
            f"Kurulum: {playwright_install_hint()} Detay: {text}"
        )
    return text


def _execute_playwright_operation(operation_name: str, operation: Callable[[], Any]) -> Any:
    """Execute a Playwright operation with connection recovery."""
    connection_id = f"playwright_{operation_name}"
    return connection_recovery.execute_with_recovery(
        connection_id,
        operation,
        connection_type=ConnectionType.PLAYWRIGHT_BROWSER,
        on_failure=lambda e: None  # Handle in the operation itself
    )


def playwright_status() -> dict[str, Any]:
    if not playwright_available():
        return {
            "available": False,
            "chromium": False,
            "engine": "urllib+open",
            "note": (
                "Playwright yüklü değil. Click/fill kullanılamaz. "
                f"Kurulum: {playwright_install_hint()} "
                "Playwright NOT AVAILABLE."
            ),
        }
    ok, detail = _chromium_executable_ok()
    if not ok:
        return {
            "available": True,
            "chromium": False,
            "engine": "playwright-package-only",
            "note": (
                "Playwright paketi var ama chromium kullanılamıyor. "
                f"Kurulum: {playwright_install_hint()} "
                f"Detay: {detail}"
            ),
        }
    return {
        "available": True,
        "chromium": True,
        "engine": "playwright",
        "note": "Playwright + chromium hazır (click/fill kullanılabilir).",
    }


def playwright_click(url: str, selector: str, *, timeout_ms: int = 10000) -> tuple[bool, str]:
    """Click an element. Returns (ok, message). Lazy-imports Playwright with connection recovery."""
    if _click_impl is not None:
        return _click_impl(url, selector, timeout_ms=timeout_ms)

    def _click_operation():
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
            return False, f"Playwright click failed: {_format_pw_error(err)}"

    try:
        result = _execute_playwright_operation("click", _click_operation)
        # Handle the tuple result from the operation
        if isinstance(result, tuple) and len(result) == 2:
            return result
        else:
            # If the operation didn't return a tuple as expected, fall back to direct execution
            return _click_operation()
    except Exception as e:
        return False, f"Playwright click failed after retries: {e}"


def playwright_fill(
    url: str,
    selector: str,
    value: str,
    *,
    timeout_ms: int = 10000,
) -> tuple[bool, str]:
    """Fill an element. Returns (ok, message). Lazy-imports Playwright with connection recovery."""
    if _fill_impl is not None:
        return _fill_impl(url, selector, value, timeout_ms=timeout_ms)

    def _fill_operation():
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
            return False, f"Playwright fill failed: {_format_pw_error(err)}"

    try:
        result = _execute_playwright_operation("fill", _fill_operation)
        # Handle the tuple result from the operation
        if isinstance(result, tuple) and len(result) == 2:
            return result
        else:
            # If the operation didn't return a tuple as expected, fall back to direct execution
            return _fill_operation()
    except Exception as e:
        return False, f"Playwright fill failed after retries: {e}"