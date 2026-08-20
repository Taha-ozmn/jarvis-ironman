"""macOS TCC / privacy permission diagnostic tool."""

from __future__ import annotations

from typing import Any

from security.permissions import PermissionLevel
from system.permissions_check import format_permissions_speech, probe_macos_permissions
from tools.base import BaseTool, ToolResult


class CheckPermissionsTool(BaseTool):
    name = "system.check_permissions"
    description = (
        "Probe detectable macOS privacy permissions "
        "(Screen Recording, Accessibility/Automation, FDA, Mail). "
        "Cannot silently grant TCC — reports only. "
        "Pass open_all=true to open every Privacy pane."
    )
    permission_level = PermissionLevel.READ
    input_schema = {
        "open_all": {"type": "bool", "required": False},
    }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        open_all = bool(arguments.get("open_all"))
        report = probe_macos_permissions()
        speech = format_permissions_speech(report)

        from system.permissions_check import open_all_privacy_settings, open_privacy_settings

        if open_all:
            open_all_privacy_settings()
            speech = (
                speech.rstrip(".")
                + ". I've opened Privacy settings panes — enable Accessibility, "
                "Screen Recording, Full Disk Access, Automation (Mail/Calendar), "
                "and Microphone for Terminal or Cursor, then restart JARVIS."
            )
            return ToolResult(ok=True, data=speech)

        missing = [
            c for c in (report.get("checks") or []) if c.get("ok") is False
        ]
        opened_panes: list[str] = []
        for c in missing:
            cid = str(c.get("id") or "")
            pane = None
            if cid == "screen_recording":
                pane = "screen_recording"
            elif cid == "accessibility_automation":
                pane = "accessibility"
            elif cid == "full_disk_access":
                pane = "full_disk_access"
            elif cid == "automation_mail":
                pane = "automation"
            if pane:
                ok, _ = open_privacy_settings(pane)
                if ok:
                    opened_panes.append(pane)
        if opened_panes:
            speech = (
                speech.rstrip(".")
                + f". Opened settings for: {', '.join(opened_panes)}. "
                "Toggle them ON for the app that runs JARVIS (Terminal/Cursor), "
                "then quit and restart JARVIS."
            )
        return ToolResult(ok=True, data=speech)
