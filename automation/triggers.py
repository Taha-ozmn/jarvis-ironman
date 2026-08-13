"""Time-based trigger matching — stdlib only (no cron deps)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional


WEEKDAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "pazartesi": 0,
    "salı": 1,
    "sali": 1,
    "çarşamba": 2,
    "carsamba": 2,
    "perşembe": 3,
    "persembe": 3,
    "cuma": 4,
    "cumartesi": 5,
    "pazar": 6,
}


def parse_trigger_spec(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def fire_key(now: datetime) -> str:
    """One fire slot per calendar minute."""
    return now.strftime("%Y-%m-%dT%H:%M")


def should_fire(
    trigger_spec: dict[str, Any],
    now: datetime,
    *,
    last_fired_at: Optional[str] = None,
) -> bool:
    """Return True if the rule should run at ``now`` (local time)."""
    kind = str(trigger_spec.get("kind") or "").lower()
    if not kind or kind == "manual":
        return False

    slot = fire_key(now)
    if last_fired_at and last_fired_at.startswith(slot):
        return False

    hour = int(trigger_spec.get("hour", 0))
    minute = int(trigger_spec.get("minute", 0))

    if kind == "daily":
        return now.hour == hour and now.minute == minute

    if kind == "weekly":
        weekday = int(trigger_spec.get("weekday", 0))
        return now.weekday() == weekday and now.hour == hour and now.minute == minute

    if kind == "interval":
        every = max(1, int(trigger_spec.get("every_minutes", 60)))
        # Fire once when minute aligns to interval from midnight.
        minutes_today = now.hour * 60 + now.minute
        if minutes_today % every != 0:
            return False
        return True

    if kind == "at_time":
        # One-shot style daily until disabled — same as daily
        return now.hour == hour and now.minute == minute

    return False
