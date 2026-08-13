"""Proactive notifications — rate limits + quiet hours (no spam)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class NotificationPolicy:
    quiet_hours_start: int = 22  # inclusive local hour
    quiet_hours_end: int = 7  # exclusive
    min_interval_seconds: int = 1800
    max_per_hour: int = 3

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> "NotificationPolicy":
        cfg = cfg or {}
        return cls(
            quiet_hours_start=int(cfg.get("quiet_hours_start", 22)),
            quiet_hours_end=int(cfg.get("quiet_hours_end", 7)),
            min_interval_seconds=int(cfg.get("min_interval_seconds", 1800)),
            max_per_hour=int(cfg.get("max_per_hour", 3)),
        )


class ProactiveNotifier:
    """Gate proactive speak/notify attempts."""

    def __init__(self, policy: Optional[NotificationPolicy] = None) -> None:
        self.policy = policy or NotificationPolicy()
        self._lock = threading.Lock()
        self._last_sent_at: float = 0.0
        self._hour_bucket: str = ""
        self._hour_count: int = 0

    def in_quiet_hours(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now().astimezone()
        start = self.policy.quiet_hours_start
        end = self.policy.quiet_hours_end
        hour = now.hour
        if start == end:
            return False
        if start > end:
            # e.g. 22 → 7
            return hour >= start or hour < end
        return start <= hour < end

    def allow(self, *, now: Optional[datetime] = None, force: bool = False) -> bool:
        if force:
            return True
        now = now or datetime.now().astimezone()
        if self.in_quiet_hours(now):
            return False
        with self._lock:
            ts = time.time()
            if ts - self._last_sent_at < self.policy.min_interval_seconds:
                return False
            bucket = now.strftime("%Y-%m-%dT%H")
            if bucket != self._hour_bucket:
                self._hour_bucket = bucket
                self._hour_count = 0
            if self._hour_count >= self.policy.max_per_hour:
                return False
            self._last_sent_at = ts
            self._hour_count += 1
            return True

    def reset(self) -> None:
        with self._lock:
            self._last_sent_at = 0.0
            self._hour_count = 0
            self._hour_bucket = ""
