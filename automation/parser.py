"""Natural-language → automation rule parser (TR + EN)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from automation.triggers import WEEKDAY_NAMES


@dataclass
class ParsedAutomation:
    name: str
    trigger_type: str
    trigger_spec: dict[str, Any]
    action_spec: dict[str, Any]
    enabled: bool = True


def _extract_time(text: str) -> tuple[int, int]:
    """Parse HH:MM or 'saat 9' / 'at 9' → (hour, minute). Default 09:00."""
    lower = text.lower()
    m = re.search(r"\b([01]?\d|2[0-3])[:\.]([0-5]\d)\b", lower)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(?:saat|at|@)\s*([01]?\d|2[0-3])\b", lower)
    if m:
        return int(m.group(1)), 0
    m = re.search(r"\b([01]?\d|2[0-3])\s*(?:am|pm)?\b", lower)
    # Prefer explicit morning/evening defaults over bare numbers in "every 30"
    if "morning" in lower or "sabah" in lower:
        return 9, 0
    if "evening" in lower or "akşam" in lower or "aksam" in lower:
        return 18, 0
    if m and ("at " in lower or "saat" in lower):
        hour = int(m.group(1))
        if "pm" in lower and hour < 12:
            hour += 12
        return hour, 0
    if "morning" in lower or "sabah" in lower:
        return 9, 0
    return 9, 0


def _infer_action(text: str) -> dict[str, Any]:
    lower = text.lower()
    if any(
        w in lower
        for w in (
            "briefing",
            "brifing",
            "özet",
            "ozet",
            "daily summary",
            "günlük özet",
            "gunluk ozet",
        )
    ):
        return {"type": "briefing"}
    if any(
        w in lower
        for w in (
            "task",
            "görev",
            "gorev",
            "todo",
            "remind",
            "hatırlat",
            "hatirlat",
        )
    ):
        return {"type": "remind_tasks"}
    # Custom speak message after "say" / "söyle"
    m = re.search(
        r"(?:say|söyle|soyle|announce)\s+(.+)$",
        text,
        re.I,
    )
    if m:
        return {"type": "speak", "text": m.group(1).strip()[:200]}
    return {"type": "briefing"}


def parse_automation_nl(text: str) -> Optional[ParsedAutomation]:
    """Parse common schedule / file-watch phrases. Returns None if not an automation intent."""
    raw = (text or "").strip()
    if not raw:
        return None
    lower = raw.lower()

    # File watch: "İndirilenlere PDF gelince…" / "when a pdf appears in Downloads"
    file_watch = _parse_file_watch(raw, lower)
    if file_watch is not None:
        return file_watch

    create_hints = (
        "every morning",
        "every evening",
        "every monday",
        "every tuesday",
        "every wednesday",
        "every thursday",
        "every friday",
        "every saturday",
        "every sunday",
        "every day",
        "each morning",
        "her sabah",
        "her akşam",
        "her aksam",
        "her gün",
        "her gun",
        "her pazartesi",
        "her salı",
        "her sali",
        "her çarşamba",
        "her carsamba",
        "her perşembe",
        "her persembe",
        "her cuma",
        "her cumartesi",
        "her pazar",
        "automate",
        "otomasyon",
        "schedule",
        "zamanla",
        "remind me every",
        "hatırlat her",
        "hatirlat her",
    )
    at_time = re.search(
        r"(?:at|saat)\s*([01]?\d|2[0-3])([:\.]([0-5]\d))?\b",
        lower,
    )
    looks_schedule = any(h in lower for h in create_hints) or (
        at_time is not None
        and any(
            w in lower
            for w in ("remind", "hatırlat", "hatirlat", "briefing", "brifing", "özet", "ozet")
        )
    )
    if not looks_schedule:
        return None

    hour, minute = _extract_time(raw)
    action = _infer_action(raw)

    # Weekly
    for name, dow in WEEKDAY_NAMES.items():
        if f"every {name}" in lower or f"her {name}" in lower:
            trigger = {
                "kind": "weekly",
                "weekday": dow,
                "hour": hour,
                "minute": minute,
            }
            label = f"Weekly {name} {hour:02d}:{minute:02d}"
            return ParsedAutomation(
                name=label,
                trigger_type="weekly",
                trigger_spec=trigger,
                action_spec=action,
                enabled=True,
            )

    # Interval: every N minutes
    m_int = re.search(r"every\s+(\d+)\s+min", lower) or re.search(
        r"her\s+(\d+)\s+dakika", lower
    )
    if m_int:
        every = max(1, int(m_int.group(1)))
        trigger = {"kind": "interval", "every_minutes": every}
        return ParsedAutomation(
            name=f"Every {every} min",
            trigger_type="interval",
            trigger_spec=trigger,
            action_spec=action,
            enabled=True,
        )

    # Daily / morning / evening / every day
    if any(
        h in lower
        for h in (
            "every morning",
            "every evening",
            "every day",
            "each morning",
            "her sabah",
            "her akşam",
            "her aksam",
            "her gün",
            "her gun",
            "daily",
        )
    ) or (
        at_time
        and any(w in lower for w in ("remind", "hatırlat", "hatirlat", "briefing", "özet"))
    ):
        trigger = {"kind": "daily", "hour": hour, "minute": minute}
        return ParsedAutomation(
            name=f"Daily {hour:02d}:{minute:02d}",
            trigger_type="daily",
            trigger_spec=trigger,
            action_spec=action,
            enabled=True,
        )

    return None


def _parse_file_watch(raw: str, lower: str) -> Optional[ParsedAutomation]:
    watch_hints = (
        "gelince",
        "geldiğinde",
        "geldiginde",
        "appears",
        "appear in",
        "when a ",
        "when an ",
        "indirilenlere",
        "downloads",
        "watched folder",
        "dosya gelince",
        "file appears",
        "new file in",
    )
    if not any(h in lower for h in watch_hints):
        return None
    # Must look like a watch intent, not generic chat
    if not any(
        h in lower
        for h in (
            "gelince",
            "appears",
            "appear",
            "when a",
            "when an",
            "dosya gelince",
            "new file",
            "indirilenlere",
            "downloads",
        )
    ):
        return None

    folder = "~/Downloads"
    if "desktop" in lower or "masaüstü" in lower or "masaustu" in lower:
        folder = "~/Desktop"
    if "documents" in lower or "belgeler" in lower:
        folder = "~/Documents"
    m_path = re.search(r"(?:in|için|icin|folder)\s+([~/][\w\-./]+)", raw, re.I)
    if m_path:
        folder = m_path.group(1).strip()

    pattern = "*"
    if "pdf" in lower:
        pattern = "*.pdf"
    elif "png" in lower or "image" in lower or "jpg" in lower or "jpeg" in lower:
        pattern = "*.png" if "png" in lower else "*.jpg"
    elif "zip" in lower:
        pattern = "*.zip"
    else:
        m_ext = re.search(r"\*\.(\w+)|\.(\w+)\s+file", lower)
        if m_ext:
            pattern = f"*.{m_ext.group(1) or m_ext.group(2)}"

    action = _infer_action(raw)
    if action.get("type") == "briefing" and any(
        w in lower for w in ("say", "söyle", "soyle", "announce", "haber ver", "bildir")
    ):
        # Default announce file name
        action = {"type": "speak", "text": "New file arrived: {file}"}
    elif action.get("type") == "briefing":
        action = {"type": "speak", "text": "New download detected: {file}"}

    label = f"Watch {pattern} in {folder}"
    return ParsedAutomation(
        name=label[:80],
        trigger_type="file_watch",
        trigger_spec={
            "kind": "file_watch",
            "path": folder,
            "pattern": pattern,
            "settle_seconds": 0.5,
        },
        action_spec=action,
        enabled=True,
    )
