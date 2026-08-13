"""Browser tools — open URL via macOS, fetch page text via urllib (no Playwright)."""

from __future__ import annotations

import html
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional
from webbrowser import open as webbrowser_open

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult

USER_AGENT = "JARVIS-2.0-PersonalAI/1.0 (+local)"


class BrowserOpenUrlTool(BaseTool):
    name = "browser.open_url"
    description = "Open a URL in the default browser (macOS open / webbrowser)"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"url": {"type": "str", "required": True}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        url = str(arguments.get("url") or "").strip()
        if not url:
            return ToolResult(ok=False, error="url required")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            subprocess.Popen(
                ["open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            webbrowser_open(url)
        return ToolResult(ok=True, data=f"Opened {url}")


class BrowserSearchTool(BaseTool):
    name = "browser.search"
    description = "Open a web search results page in the browser"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"query": {"type": "str", "required": True}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="query required")
        url = "https://duckduckgo.com/?q=" + urllib.parse.quote_plus(query)
        try:
            subprocess.Popen(
                ["open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            webbrowser_open(url)
        return ToolResult(ok=True, data=f"Searching for «{query}».")


class BrowserGetPageTextTool(BaseTool):
    name = "browser.get_page_text"
    description = "Fetch a URL and return plain text excerpt (urllib; read-only)"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"url": {"type": "str", "required": True}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        url = str(arguments.get("url") or "").strip()
        if not url:
            return ToolResult(ok=False, error="url required")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            text = fetch_page_text(url, max_chars=int(arguments.get("max_chars") or 1200))
        except Exception as err:
            return ToolResult(ok=False, error=f"Fetch failed: {err}")
        if not text:
            return ToolResult(ok=False, error="No readable text extracted")
        return ToolResult(ok=True, data=text)


class BrowserFillFormTool(BaseTool):
    name = "browser.fill_form"
    description = (
        "Fill a form field via Playwright when installed; otherwise NOT IMPLEMENTED. "
        "Requires: pip install -r requirements-optional.txt && playwright install chromium"
    )
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "url": {"type": "str", "required": True},
        "selector": {"type": "str", "required": False},
        "value": {"type": "str", "required": False},
    }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        from tools.browser_playwright import playwright_available, playwright_fill

        if not playwright_available():
            return ToolResult(
                ok=False,
                error=(
                    "browser.fill_form NOT AVAILABLE — Playwright not installed. "
                    "Install: pip install -r requirements-optional.txt && playwright install chromium. "
                    "Fallback: browser.open_url / get_page_text."
                ),
                data={"received": arguments},
            )
        url = str(arguments.get("url") or "").strip()
        selector = str(arguments.get("selector") or "").strip()
        value = str(arguments.get("value") or "")
        if not url or not selector:
            return ToolResult(ok=False, error="url and selector required for Playwright fill")
        ok, msg = playwright_fill(url, selector, value)
        return ToolResult(ok=ok, data=msg if ok else None, error=None if ok else msg)


class BrowserClickTool(BaseTool):
    name = "browser.click"
    description = (
        "Click a selector via Playwright when installed; otherwise NOT IMPLEMENTED."
    )
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "url": {"type": "str", "required": True},
        "selector": {"type": "str", "required": True},
    }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        from tools.browser_playwright import playwright_available, playwright_click

        if not playwright_available():
            return ToolResult(
                ok=False,
                error=(
                    "browser.click NOT AVAILABLE — Playwright not installed. "
                    "Install optional deps — see requirements-optional.txt."
                ),
            )
        url = str(arguments.get("url") or "").strip()
        selector = str(arguments.get("selector") or "").strip()
        if not url or not selector:
            return ToolResult(ok=False, error="url and selector required")
        ok, msg = playwright_click(url, selector)
        return ToolResult(ok=ok, data=msg if ok else None, error=None if ok else msg)


def fetch_page_text(url: str, *, max_chars: int = 1200, timeout: float = 12.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(500_000)
        charset = "utf-8"
        ctype = resp.headers.get_content_charset()
        if ctype:
            charset = ctype
        html_text = raw.decode(charset, errors="replace")
    # strip scripts/styles
    cleaned = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", html_text)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "…"
    return cleaned


def browser_diagnostics() -> dict[str, Any]:
    """Report how browser tools work (honest about Playwright)."""
    from tools.browser_playwright import playwright_status

    status = playwright_status()
    if status.get("available"):
        return {
            "engine": "playwright+urllib",
            "playwright": True,
            "note": status.get("note"),
        }
    return {
        "engine": "urllib+open",
        "playwright": False,
        "note": status.get("note"),
    }
