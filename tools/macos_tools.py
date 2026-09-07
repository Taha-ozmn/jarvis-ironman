"""macOS tools wrapping system.macos.MacOSController."""

from __future__ import annotations

import datetime
import subprocess
from typing import Any, Optional
from urllib.parse import quote_plus
import webbrowser

from security.permissions import PermissionLevel
from security.risk import is_blocked_shell, is_dangerous_shell
from tools.base import BaseTool, ToolResult


class ListAppsTool(BaseTool):
    name = "system.list_apps"
    description = "List installed macOS applications (from /Applications scan)"
    permission_level = PermissionLevel.READ
    input_schema = {"limit": {"type": "int", "required": False}}

    def __init__(self, controller: Any) -> None:
        self._c = controller

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        limit = int(arguments.get("limit") or 40)
        limit = max(5, min(limit, 200))
        names = self._c._app_catalog.list_names(limit=limit)
        if not names:
            return ToolResult(ok=False, error="No applications found.")
        return ToolResult(
            ok=True,
            data=f"Installed apps ({len(names)}): " + ", ".join(names),
        )


class OpenAppTool(BaseTool):
    name = "system.open_app"
    description = "Open a macOS application by name"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"name": {"type": "str", "required": True}}

    def __init__(self, controller: Any) -> None:
        self._c = controller
        self._max_retries = 3
        self._base_delay = 0.5  # seconds

    def _retry_with_backoff(self, func, *args, **kwargs):
        """Execute function with exponential backoff retry."""
        import time
        last_exception = None

        for attempt in range(self._max_retries):
            try:
                result = func(*args, **kwargs)
                if result is not None:  # Success if not None
                    return result
                # If result is None, treat as failure to retry
                raise Exception("Operation returned None")
            except Exception as e:
                last_exception = e
                if attempt < self._max_retries - 1:  # Don't sleep on last attempt
                    delay = self._base_delay * (2 ** attempt)  # Exponential backoff
                    time.sleep(delay)

        # All retries exhausted
        raise last_exception

    def _open_with_fallbacks(self, name: str) -> Optional[str]:
        """Try to open app with multiple fallback strategies."""
        # Strategy 1: Try resolved name with retries
        try:
            resolved_name = self._c._resolve_app_name(name) or name
            return self._retry_with_backoff(self._c._open_app, resolved_name)
        except Exception:
            pass  # Continue to fallbacks

        # Strategy 2: Try direct app search in /Applications
        try:
            import subprocess
            from pathlib import Path

            apps_dir = Path("/Applications")
            if apps_dir.exists():
                # Look for exact match first
                for app in apps_dir.iterdir():
                    if app.is_dir() and app.suffix == ".app":
                        if app.stem.lower() == name.lower():
                            result = subprocess.run(
                                ["open", "-a", str(app)],
                                capture_output=True,
                                text=True,
                                timeout=10
                            )
                            if result.returncode == 0:
                                return f"{app.stem} is open."

                # Look for partial match
                for app in apps_dir.iterdir():
                    if app.is_dir() and app.suffix == ".app":
                        if name.lower() in app.stem.lower():
                            result = subprocess.run(
                                ["open", "-a", str(app)],
                                capture_output=True,
                                text=True,
                                timeout=10
                            )
                            if result.returncode == 0:
                                return f"{app.stem} is open."
        except Exception:
            pass  # Continue to fallbacks

        # Strategy 3: Try Spotlight search
        try:
            mdfind_result = self._c._app_catalog.spotlight_find(name)
            if mdfind_result is not None:
                result = subprocess.run(
                    ["open", str(mdfind_result.path)],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    return f"{mdfind_result.name} is open."
        except Exception:
            pass  # Continue to fallbacks

        # Strategy 4: Try as URL if it looks like one
        try:
            if name.startswith(("http://", "https://")) or (
                "." in name and
                " " not in name and
                not name.startswith("/") and
                len(name.split(".")) >= 2
            ):
                url = name if name.startswith("http") else f"https://{name}"
                import webbrowser
                webbrowser.open(url)
                return f"Opening {url}."
        except Exception:
            pass  # Continue to fallbacks

        return None

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments.get("name") or "").strip()
        if not name:
            return ToolResult(ok=False, error="App name required")

        try:
            msg = self._open_with_fallbacks(name)
            if msg:
                return ToolResult(ok=True, data=msg)
            else:
                suggestions = self._c._app_catalog.suggest(name, limit=3)
                hint = (
                    f" Suggestions: {', '.join(suggestions)}."
                    if suggestions else ""
                )
                error_msg = (
                    f"I couldn't open «{name}». "
                    f"Please check the application name.{hint}"
                )
                return ToolResult(ok=False, error=error_msg)
        except Exception as e:
            import traceback
            print(f"OpenAppTool error for '{name}': {e}")
            traceback.print_exc()

            suggestions = self._c._app_catalog.suggest(name, limit=3)
            hint = f" Suggestions: {', '.join(suggestions)}." if suggestions else ""
            error_msg = f"I couldn't open «{name}». Please check the application name.{hint}"
            return ToolResult(ok=False, error=error_msg)


class OpenCursorWorkspaceTool(BaseTool):
    name = "cursor.open_workspace"
    description = "Open a local folder in Cursor, optionally as a new Git repository"
    permission_level = PermissionLevel.LOCAL
    input_schema = {
        "path": {"type": "str", "required": False},
        "initialize_git": {"type": "bool", "required": False},
    }

    def __init__(self, controller: Any) -> None:
        self._c = controller

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        path = str(arguments.get("path") or "").strip()
        initialize_git = bool(arguments.get("initialize_git", False))
        try:
            result = self._c.open_cursor_workspace(
                path,
                initialize_git=initialize_git,
            )
        except Exception as err:
            return ToolResult(ok=False, error=f"Cursor workspace open failed: {err}")
        if result.startswith("Opened "):
            return ToolResult(ok=True, data=result)
        return ToolResult(ok=False, error=result)


class CloseAppTool(BaseTool):
    name = "system.close_app"
    description = "Quit a macOS application by name"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"name": {"type": "str", "required": True}}

    def __init__(self, controller: Any) -> None:
        self._c = controller

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments.get("name") or "").strip()
        if not name:
            return ToolResult(ok=False, error="App name required")
        msg = self._c._close_app(name)
        return ToolResult(ok=True, data=msg)


class TimeTool(BaseTool):
    name = "system.time"
    description = "Current local time"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        now = datetime.datetime.now()
        return ToolResult(ok=True, data=f"It's {now.strftime('%H:%M')}.")


class DateTool(BaseTool):
    name = "system.date"
    description = "Current local date"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        now = datetime.datetime.now()
        return ToolResult(ok=True, data=f"Today is {now.strftime('%A, %d %B %Y')}.")


class VolumeTool(BaseTool):
    name = "system.volume"
    description = "Adjust system volume: up, down, or mute"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"action": {"type": "str", "required": True}}

    def __init__(self, controller: Any) -> None:
        self._c = controller

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = str(arguments.get("action") or "").lower().strip()
        if action in ("up", "increase", "aç", "yükselt"):
            self._c._osascript(
                "set volume output volume (output volume of (get volume settings) + 15)"
            )
            return ToolResult(ok=True, data="Volume increased.")
        if action in ("down", "decrease", "kıs", "azalt"):
            self._c._osascript(
                "set volume output volume (output volume of (get volume settings) - 15)"
            )
            return ToolResult(ok=True, data="Volume decreased.")
        if action in ("mute", "sessiz"):
            self._c._osascript("set volume with output muted")
            return ToolResult(ok=True, data="Audio muted.")
        return ToolResult(ok=False, error="action must be up, down, or mute")


class WebSearchTool(BaseTool):
    name = "system.web_search"
    description = "Quick web lookup (DuckDuckGo snippets) or open browser fallback"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"query": {"type": "str", "required": True}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="Query required")
        try:
            from tools.research_tools import collect_research_snippets, extractive_summary

            snippets = collect_research_snippets(query, limit=2)
            if snippets:
                summary = extractive_summary(query, snippets, max_chars=220)
                return ToolResult(ok=True, data=summary)
        except Exception:
            pass
        webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
        return ToolResult(ok=True, data=f"Searching Google for «{query}».")


class ShellTool(BaseTool):
    name = "system.shell"
    description = "Run a shell command (SYSTEM; dangerous patterns need Level 3 confirm)"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {"command": {"type": "str", "required": True}}

    def __init__(self, controller: Any) -> None:
        self._c = controller

    def resolve_permission(self, arguments: dict[str, Any]) -> PermissionLevel:
        cmd = str(arguments.get("command") or "")
        if is_dangerous_shell(cmd):
            return PermissionLevel.DANGEROUS
        return PermissionLevel.SYSTEM

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        cmd = str(arguments.get("command") or "").strip()
        if not cmd:
            return ToolResult(ok=False, error="Command required")
        if is_blocked_shell(cmd):
            return ToolResult(
                ok=False,
                error="Blocked: this command is too destructive (e.g. rm -rf /).",
            )
        if not getattr(self._c, "full_shell_access", True):
            return ToolResult(ok=False, error="Shell access is disabled in configuration.")
        try:
            from pathlib import Path

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(Path.home()),
            )
            output = (result.stdout or result.stderr or "").strip()
            if not output:
                output = "Command completed with no output."
            if len(output) > 200:
                output = output[:200] + "…"
            ok = result.returncode == 0
            speech = f"Done. {output}" if ok else f"Failed. {output}"
            return ToolResult(ok=ok, data=speech, error=None if ok else output)
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error="The command timed out.")
        except Exception as err:
            return ToolResult(ok=False, error=f"Command failed: {err}")


class ClipboardReadTool(BaseTool):
    name = "clipboard.read"
    description = "Read the macOS clipboard (pbpaste)"
    permission_level = PermissionLevel.LOCAL
    input_schema: dict = {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        try:
            result = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            text = (result.stdout or "").strip()
            if not text:
                return ToolResult(ok=True, data="Clipboard is empty.")
            if len(text) > 400:
                text = text[:397] + "…"
            return ToolResult(ok=True, data=f"Clipboard: {text}")
        except Exception as err:
            return ToolResult(ok=False, error=str(err))


class ClipboardWriteTool(BaseTool):
    name = "clipboard.write"
    description = "Write text to the macOS clipboard (pbcopy)"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"text": {"type": "str", "required": True}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        text = str(arguments.get("text") or "")
        if not text:
            return ToolResult(ok=False, error="text required")
        try:
            subprocess.run(
                ["pbcopy"],
                input=text,
                text=True,
                capture_output=True,
                timeout=5,
                check=True,
            )
            return ToolResult(ok=True, data="Copied to clipboard.")
        except Exception as err:
            return ToolResult(ok=False, error=str(err))


class NotifyTool(BaseTool):
    name = "system.notify"
    description = "Show a macOS notification (osascript display notification)"
    permission_level = PermissionLevel.LOCAL
    input_schema = {
        "title": {"type": "str", "required": False},
        "message": {"type": "str", "required": True},
    }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        title = str(arguments.get("title") or "JARVIS").replace('"', '\\"')
        message = str(arguments.get("message") or "").replace('"', '\\"')
        if not message.strip():
            return ToolResult(ok=False, error="message required")
        script = f'display notification "{message}" with title "{title}"'
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=8,
                check=False,
            )
            return ToolResult(ok=True, data="Notification sent.")
        except Exception as err:
            return ToolResult(ok=False, error=str(err))


class ProcessListTool(BaseTool):
    name = "system.processes"
    description = "List top CPU processes (safe read-only snapshot)"
    permission_level = PermissionLevel.READ
    input_schema = {"limit": {"type": "int", "required": False}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        limit = int(arguments.get("limit") or 8)
        limit = max(1, min(limit, 20))
        try:
            result = subprocess.run(
                ["ps", "-axo", "pid,%cpu,comm"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            lines = (result.stdout or "").strip().splitlines()
            # skip header; sort by cpu numerically
            rows: list[tuple[float, str]] = []
            for ln in lines[1:]:
                parts = ln.split(None, 2)
                if len(parts) < 3:
                    continue
                try:
                    cpu = float(parts[1])
                except ValueError:
                    continue
                rows.append((cpu, f"{parts[0]} {parts[1]}% {parts[2]}"))
            rows.sort(key=lambda r: r[0], reverse=True)
            top = [r[1] for r in rows[:limit]]
            if not top:
                return ToolResult(ok=True, data="Process list is empty.")
            return ToolResult(ok=True, data="Top processes: " + "; ".join(top))
        except Exception as err:
            return ToolResult(ok=False, error=str(err))


class FinderRevealTool(BaseTool):
    name = "finder.reveal"
    description = "Reveal a path in Finder (open -R) or open Finder home"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"path": {"type": "str", "required": False}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        from pathlib import Path

        raw = str(arguments.get("path") or "").strip()
        if not raw:
            try:
                subprocess.run(["open", "-a", "Finder"], capture_output=True, timeout=8)
                return ToolResult(ok=True, data="Finder is open.")
            except Exception as err:
                return ToolResult(ok=False, error=str(err))
        path = Path(raw).expanduser()
        if not path.exists():
            return ToolResult(ok=False, error=f"Path not found: {path}")
        try:
            subprocess.run(
                ["open", "-R", str(path)],
                capture_output=True,
                timeout=8,
                check=False,
            )
            return ToolResult(ok=True, data=f"Revealed in Finder: {path}")
        except Exception as err:
            return ToolResult(ok=False, error=str(err))
