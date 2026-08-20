"""macOS Mail.app tools via AppleScript (Automation permission required)."""

from __future__ import annotations

import subprocess
from typing import Any
from urllib.parse import quote

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult


def _osascript(script: str, *, timeout: float = 20.0) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "osascript not found (macOS only)"
    except subprocess.TimeoutExpired:
        return False, "Mail AppleScript timed out"
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if result.returncode != 0:
        return False, err or out or "Mail AppleScript failed"
    return True, out


class MailOpenTool(BaseTool):
    name = "mail.open"
    description = "Open macOS Mail.app"
    permission_level = PermissionLevel.LOCAL
    input_schema: dict = {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        ok, msg = _osascript('tell application "Mail" to activate')
        if not ok:
            # Fallback: open -a
            try:
                subprocess.run(
                    ["open", "-a", "Mail"],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                return ToolResult(ok=True, data="Mail is open.")
            except Exception as err:
                return ToolResult(ok=False, error=f"{msg}; open failed: {err}")
        return ToolResult(ok=True, data="Mail is open.")


class MailInboxSummaryTool(BaseTool):
    name = "mail.inbox_summary"
    description = "Summarize recent unread / inbox messages from Mail.app"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"limit": {"type": "int", "required": False}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        limit = int(arguments.get("limit") or 5)
        limit = max(1, min(limit, 20))
        # NOTE: `read` is an AppleScript reserved command — never write
        # `read status` unquoted; use |read status| instead.
        script = f"""
        tell application "Mail"
          set output to ""
          set unreadCount to unread count of inbox
          set msgs to messages of inbox
          set n to count of msgs
          if n > {limit} then set n to {limit}
          repeat with i from 1 to n
            set m to item i of msgs
            set subj to subject of m
            set snd to sender of m
            set isRead to |read status| of m
            set flag to "read"
            if isRead is false then set flag to "unread"
            set output to output & flag & " | " & snd & " | " & subj & linefeed
          end repeat
          return "unread=" & unreadCount & linefeed & output
        end tell
        """
        ok, raw = _osascript(script, timeout=30.0)
        if not ok:
            err = (raw or "inbox read failed").strip()
            lower = err.lower()
            if "-1743" in err or "not allowed" in lower or "authorization" in lower:
                err += (
                    " Grant Automation → Mail: System Settings → Privacy & Security "
                    "→ Automation → enable Mail for Terminal/Python."
                )
            elif "-2741" in err or "syntax error" in lower:
                err = (
                    "Mail AppleScript failed (script fault). "
                    "If this persists after update, grant Automation → Mail and retry."
                )
            else:
                err += (
                    " If Mail was never authorized: System Settings → Privacy & Security "
                    "→ Automation → Mail."
                )
            return ToolResult(ok=False, error=err)
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        if not lines:
            return ToolResult(ok=True, data="Inbox looks empty.")
        header = lines[0]
        body = lines[1:]
        if not body:
            return ToolResult(ok=True, data=f"Inbox: {header}. No messages.")
        preview = "; ".join(body[:limit])
        if len(preview) > 400:
            preview = preview[:397] + "…"
        return ToolResult(ok=True, data=f"Inbox ({header}): {preview}")


class MailComposeTool(BaseTool):
    name = "mail.compose"
    description = (
        "Compose a Mail.app message. send=false opens draft (SYSTEM); "
        "send=true sends (DANGEROUS / Level 3)."
    )
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "to": {"type": "str", "required": True},
        "subject": {"type": "str", "required": False},
        "body": {"type": "str", "required": False},
        "send": {"type": "bool", "required": False},
    }

    def resolve_permission(self, arguments: dict[str, Any]) -> PermissionLevel:
        if bool(arguments.get("send")):
            return PermissionLevel.DANGEROUS
        return PermissionLevel.SYSTEM

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        to = str(arguments.get("to") or "").strip()
        if not to or "@" not in to:
            return ToolResult(ok=False, error="Valid 'to' email required")
        subject = str(arguments.get("subject") or "").replace('"', '\\"')
        body = str(arguments.get("body") or "").replace('"', '\\"')
        do_send = bool(arguments.get("send"))

        if do_send:
            script = f"""
            tell application "Mail"
              set newMessage to make new outgoing message with properties {{subject:"{subject}", content:"{body}", visible:true}}
              tell newMessage
                make new to recipient at end of to recipients with properties {{address:"{to}"}}
                send
              end tell
            end tell
            """
            ok, msg = _osascript(script, timeout=30.0)
            if not ok:
                return ToolResult(ok=False, error=msg or "Mail send failed")
            return ToolResult(ok=True, data=f"Email sent to {to}")

        # Prefer mailto: for draft — avoids full Automation for compose-only
        mailto = f"mailto:{quote(to)}?subject={quote(subject)}&body={quote(body)}"
        try:
            subprocess.run(["open", mailto], capture_output=True, timeout=10, check=False)
            return ToolResult(ok=True, data=f"Draft opened for {to}")
        except Exception as err:
            return ToolResult(ok=False, error=str(err))
