"""macOS Calendar.app via AppleScript (Automation / Calendar permission)."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta
from typing import Any

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult


def _osascript(script: str, *, timeout: float = 25.0) -> tuple[bool, str]:
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
        return False, "Calendar AppleScript timed out"
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if result.returncode != 0:
        return False, err or out or "Calendar AppleScript failed"
    return True, out


def _denied_speech(err: str) -> str:
    low = (err or "").lower()
    if any(
        x in low
        for x in (
            "not authorized",
            "not allowed",
            "(-1743)",
            "permission",
            "denied",
            "accessibility",
        )
    ):
        return (
            "Takvim izni yok. Sistem Ayarları → Gizlilik ve Güvenlik → Otomasyon "
            "içinde Calendar'a izin verin; ilk seferde çıkan diyalogda Tamam'a basın."
        )
    return f"Takvim okunamadı: {err[:180]}"


def parse_event_fields(text: str) -> dict[str, Any]:
    """Best-effort title / start from Turkish voice: 'randevu ekle yarın 14:00 Demo'."""
    raw = (text or "").strip()
    title = raw
    for prefix in (
        "randevu ekle",
        "etkinlik ekle",
        "takvime ekle",
        "create event",
        "add event",
    ):
        if title.lower().startswith(prefix):
            title = title[len(prefix) :].strip(" :,-")
            break
    now = datetime.now()
    start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    low = raw.lower()
    if "yarın" in low or "yarin" in low:
        start = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    time_m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", raw)
    if time_m:
        hour = max(0, min(23, int(time_m.group(1))))
        minute = max(0, min(59, int(time_m.group(2))))
        start = start.replace(hour=hour, minute=minute)
        title = re.sub(r"\b\d{1,2}[:.]\d{2}\b", " ", title)
    title = re.sub(r"\b(bugün|bugun|yarın|yarin|saat)\b", " ", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip(" .,:-") or "Randevu"
    end = start + timedelta(hours=1)
    return {"title": title[:120], "start": start, "end": end}


class CalendarListTodayTool(BaseTool):
    name = "calendar.list_today"
    description = "List today's events from macOS Calendar.app"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        script = """
        set output to ""
        set todayStart to (current date)
        set hours of todayStart to 0
        set minutes of todayStart to 0
        set seconds of todayStart to 0
        set todayEnd to todayStart + (1 * days)
        tell application "Calendar"
          repeat with cal in calendars
            try
              set evts to (every event of cal whose start date ≥ todayStart and start date < todayEnd)
              repeat with e in evts
                set output to output & (summary of e) & " | " & ((start date of e) as string) & linefeed
              end repeat
            end try
          end repeat
        end tell
        return output
        """
        ok, msg = _osascript(script)
        if not ok:
            return ToolResult(ok=False, error=_denied_speech(msg))
        lines = [ln.strip() for ln in msg.splitlines() if ln.strip()]
        if not lines:
            return ToolResult(ok=True, data="No calendar events today.")
        preview = "; ".join(lines[:8])
        return ToolResult(
            ok=True,
            data=f"Today: {len(lines)} event(s): {preview}"[:400],
        )


class CalendarCreateEventTool(BaseTool):
    name = "calendar.create_event"
    description = "Create a Calendar.app event (Level 2 — Automation)"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "title": {"type": "str", "required": False},
        "text": {"type": "str", "required": False},
    }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raw = str(arguments.get("text") or arguments.get("title") or "").strip()
        fields = parse_event_fields(raw)
        title = str(arguments.get("title") or fields["title"]).strip() or fields["title"]
        start: datetime = fields["start"]
        end: datetime = fields["end"]
        # AppleScript date string: "Friday, August 14, 2026 at 14:00:00"
        start_s = start.strftime("%A, %B %d, %Y at %H:%M:%S")
        end_s = end.strftime("%A, %B %d, %Y at %H:%M:%S")
        safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
        script = f'''
        tell application "Calendar"
          set theCal to first calendar
          tell theCal
            make new event with properties {{summary:"{safe_title}", start date:date "{start_s}", end date:date "{end_s}"}}
          end tell
        end tell
        '''
        ok, msg = _osascript(script)
        if not ok:
            return ToolResult(ok=False, error=_denied_speech(msg))
        when = start.strftime("%d.%m %H:%M")
        return ToolResult(ok=True, data=f"Takvime eklendi: {title} ({when}).")
