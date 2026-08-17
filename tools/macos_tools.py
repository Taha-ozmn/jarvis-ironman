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


class OpenAppTool(BaseTool):
    name = "system.open_app"
    description = "Open a macOS application by name"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"name": {"type": "str", "required": True}}

    def __init__(self, controller: Any) -> None:
        self._c = controller

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        from core.open_target import normalize_open_target
        from core.recovery import log_failure, user_safe_speech

        name = str(arguments.get("name") or "").strip()
        if not name:
            return ToolResult(ok=False, error="App name required")
        cleaned = normalize_open_target(name) or name
        if cleaned.lower() in ("ık", "ik", "açık", "acik"):
            speech = user_safe_speech(
                "Could not open",
                target="",
                language="en-GB",
            )
            # Clarify rather than pretending we opened something
            speech = (
                "I heard an open request but not which app. "
                "Say something like «open Chrome» or «Spotify aç»."
            )
            return ToolResult(ok=False, error=speech)
        resolved = self._c._resolve_app_name(cleaned) or cleaned
        msg = self._c._open_app(resolved)
        if not msg:
            log_failure("system.open_app", f"open failed for {resolved!r}")
            speech = user_safe_speech(
                f"Could not open {resolved}",
                target=resolved,
                language="en-GB",
            )
            return ToolResult(ok=False, error=speech)
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
    description = "Open a Google search in the browser"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"query": {"type": "str", "required": True}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="Query required")
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
        if not getattr(self._c, "full_shell_access", False):
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
