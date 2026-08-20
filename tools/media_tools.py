"""Media play — decide → resolve first video → open in real browser → confirm."""

from __future__ import annotations

import re
import subprocess
from typing import Any, Optional
from urllib.parse import urljoin
from webbrowser import open as webbrowser_open

from core.decision_music import decide_music_play
from core.open_target import spotify_search_url, youtube_search_url
from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult


class MediaPlayTool(BaseTool):
    name = "media.play"
    description = (
        "Autonomous music play: decide a concrete track if the request is vague, "
        "resolve the first YouTube result, open it in the default browser, and play. "
        "Never leaves the user on a blank or half-finished search when avoidable."
    )
    permission_level = PermissionLevel.LOCAL
    input_schema = {
        "query": {"type": "str", "required": True},
        "service": {"type": "str", "required": False},
        "click_first": {"type": "bool", "required": False},
    }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        if not query or len(query) < 2:
            # Bare "şarkı aç" — still decide autonomously
            query = "şarkı"
        service = str(arguments.get("service") or "youtube").strip().lower()
        if service not in ("youtube", "spotify"):
            service = "youtube"
        click_first = bool(arguments.get("click_first", True))

        decision = decide_music_play(query)

        if service == "spotify":
            url = spotify_search_url(decision.search_query)
            ok, err = _open_url(url)
            if not ok:
                return ToolResult(ok=False, error=err or "Could not open Spotify")
            msg = f"I've searched Spotify for «{decision.display_name}»."
            if decision.autonomous:
                msg = f"{decision.rationale} {msg}"
            return ToolResult(ok=True, data=msg.strip())

        search_url = youtube_search_url(decision.search_query)
        watch_url: Optional[str] = None
        if click_first:
            watch_url = _resolve_first_watch_url(search_url)

        if watch_url:
            ok, err = _open_url(watch_url)
            if ok:
                msg = f"Playing «{decision.display_name}» on YouTube."
                if decision.autonomous:
                    msg = f"{decision.rationale} {msg}"
                return ToolResult(ok=True, data=msg.strip())
            # fall through to search if open failed

        # Playwright click in headed window as secondary path
        if click_first and _try_playwright_first_video(search_url):
            msg = f"Playing «{decision.display_name}» on YouTube."
            if decision.autonomous:
                msg = f"{decision.rationale} {msg}"
            return ToolResult(ok=True, data=msg.strip())

        ok, err = _open_url(search_url)
        if not ok:
            return ToolResult(ok=False, error=err or "Could not open YouTube")
        msg = (
            f"I opened YouTube results for «{decision.display_name}» — "
            "couldn't auto-start the first video. Pick one, or name an artist."
        )
        if decision.autonomous:
            msg = f"{decision.rationale} {msg}"
        return ToolResult(ok=True, data=msg.strip())


def _open_url(url: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["open", url],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        try:
            opened = webbrowser_open(url)
            return (True, "") if opened or opened is None else (False, "webbrowser open failed")
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


def _resolve_first_watch_url(search_url: str) -> Optional[str]:
    """Headless: find first /watch?v= URL, then caller opens it in the REAL browser."""
    try:
        from tools.browser_playwright import playwright_available

        if not playwright_available():
            return None
    except Exception:
        return None
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    selectors = (
        "ytd-video-renderer a#video-title",
        "a#video-title-link",
        "a#video-title",
        "ytd-video-renderer a[href*='/watch']",
    )
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(search_url, timeout=25000, wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                for sel in selectors:
                    try:
                        loc = page.locator(sel).first
                        href = loc.get_attribute("href", timeout=4000)
                        if href and "/watch" in href:
                            if href.startswith("http"):
                                return href.split("&")[0]
                            return urljoin("https://www.youtube.com", href.split("&")[0])
                    except Exception:
                        continue
                # Regex fallback from page content
                html = page.content()
                m = re.search(r'href="(/watch\?v=[\w-]+)', html)
                if m:
                    return "https://www.youtube.com" + m.group(1)
            finally:
                browser.close()
    except Exception:
        return None
    return None


def _try_playwright_first_video(search_url: str) -> bool:
    """Headed fallback — prefer resolving watch URL + `open` instead."""
    try:
        from tools.browser_playwright import playwright_available

        if not playwright_available():
            return False
    except Exception:
        return False
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    selectors = (
        "ytd-video-renderer a#video-title",
        "a#video-title",
        "ytd-video-renderer a[href*='watch']",
    )
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
            for sel in selectors:
                try:
                    page.click(sel, timeout=5000)
                    page.wait_for_timeout(1500)
                    return True
                except Exception:
                    continue
            return False
    except Exception:
        return False
