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
        ok, err = _open_url_checked(url)
        if not ok:
            return ToolResult(ok=False, error=err or f"Could not open «{url}».")
        lower_url = url.lower()
        if "youtube.com/results" in lower_url or "search_query=" in lower_url:
            return ToolResult(ok=True, data=f"YouTube search is open: {url}")
        if "youtube.com" in lower_url:
            return ToolResult(ok=True, data=f"YouTube is open: {url}")
        if "mail.google.com" in lower_url:
            return ToolResult(ok=True, data="Gmail is open.")
        if "outlook." in lower_url:
            return ToolResult(ok=True, data="Outlook is open.")
        return ToolResult(ok=True, data=f"Opened {url}.")


class BrowserListTabsTool(BaseTool):
    name = "browser.list_tabs"
    description = "List open Chrome/Safari tabs (title + URL) via AppleScript"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        tabs = list_browser_tabs()
        if not tabs:
            return ToolResult(
                ok=True,
                data="No open tabs found. Is Chrome or Safari running?",
            )
        lines = []
        for i, tab in enumerate(tabs, 1):
            title = tab.get("title") or "Untitled"
            url = tab.get("url") or ""
            browser = tab.get("browser") or ""
            suffix = f" ({browser})" if browser else ""
            if url:
                lines.append(f"{i}) {title} — {url}{suffix}")
            else:
                lines.append(f"{i}) {title}{suffix}")
        summary = "Open tabs: " + " ".join(lines)
        return ToolResult(ok=True, data=summary)


def list_browser_tabs(*, timeout: float = 8.0) -> list[dict[str, str]]:
    """Collect tabs from running Chrome and Safari via osascript."""
    tabs: list[dict[str, str]] = []
    for browser, script in (
        ("Chrome", _CHROME_TABS_SCRIPT),
        ("Safari", _SAFARI_TABS_SCRIPT),
    ):
        raw = _run_osascript(script, timeout=timeout)
        if not raw:
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line or "|||" not in line:
                continue
            title, _, url = line.partition("|||")
            title = title.strip() or "Untitled"
            url = url.strip()
            tabs.append({"title": title, "url": url, "browser": browser})
    return tabs


_CHROME_TABS_SCRIPT = """
tell application "System Events"
  set chromeRunning to (exists process "Google Chrome")
end tell
if chromeRunning then
  tell application "Google Chrome"
    set out to ""
    repeat with w in windows
      repeat with t in tabs of w
        set out to out & (title of t as text) & "|||" & (URL of t as text) & linefeed
      end repeat
    end repeat
    return out
  end tell
else
  return ""
end if
"""

_SAFARI_TABS_SCRIPT = """
tell application "System Events"
  set safariRunning to (exists process "Safari")
end tell
if safariRunning then
  tell application "Safari"
    set out to ""
    repeat with w in windows
      repeat with t in tabs of w
        set out to out & (name of t as text) & "|||" & (URL of t as text) & linefeed
      end repeat
    end repeat
    return out
  end tell
else
  return ""
end if
"""


def _run_osascript(script: str, *, timeout: float = 8.0) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _open_url_checked(url: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["open", url],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        try:
            webbrowser_open(url)
            return True, ""
        except Exception as err:
            return False, str(err)
    except subprocess.TimeoutExpired:
        return False, "open timed out"
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "open failed").strip()
        try:
            webbrowser_open(url)
            return True, ""
        except Exception:
            return False, err[:300]
    return True, ""


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
        ok, err = _open_url_checked(url)
        if not ok:
            return ToolResult(ok=False, error=err or "search open failed")
        return ToolResult(ok=True, data=f"I've searched for «{query}».")


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
            from tools.browser_playwright import playwright_install_hint

            return ToolResult(
                ok=False,
                error=(
                    "Playwright yüklü değil — form doldurma kullanılamıyor. "
                    f"Kurulum: {playwright_install_hint()} "
                    "Playwright NOT AVAILABLE. Fallback: browser.open_url / get_page_text."
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
            from tools.browser_playwright import playwright_install_hint

            return ToolResult(
                ok=False,
                error=(
                    "Playwright yüklü değil — tıklama kullanılamıyor. "
                    f"Kurulum: {playwright_install_hint()} "
                    "Playwright NOT AVAILABLE."
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
    chromium = bool(status.get("chromium"))
    if status.get("available") and chromium:
        return {
            "engine": "playwright+urllib",
            "playwright": True,
            "chromium": True,
            "note": status.get("note"),
        }
    if status.get("available"):
        return {
            "engine": status.get("engine") or "playwright-package-only",
            "playwright": True,
            "chromium": False,
            "note": status.get("note"),
        }
    return {
        "engine": "urllib+open",
        "playwright": False,
        "chromium": False,
        "note": status.get("note"),
    }
