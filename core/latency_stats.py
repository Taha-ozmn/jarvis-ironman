"""Lightweight latency / routing stats — JSON under data/.

Stats-based hints only (no ML): record per-command latency, prefer the
faster successful path, and optionally bump soft timeouts for slow Cursor tasks.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

MAX_RECORDS = 500
MIN_SAMPLES_FOR_HINT = 2


def normalize_intent(command: str) -> str:
    """Cheap stable key from a voice/text command."""
    text = (command or "").lower().strip()
    for prefix in ("hey jarvis ", "ok jarvis ", "jarvis "):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    tokens = re.findall(r"[a-zçğıöşü0-9]+", text, flags=re.IGNORECASE)
    if not tokens:
        return "unknown"
    return " ".join(tokens[:5])[:64]


class LatencyStats:
    """Append-only JSON store with per-intent aggregates."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"records": [], "by_intent": {}}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"records": [], "by_intent": {}}
        if not isinstance(raw, dict):
            return {"records": [], "by_intent": {}}
        raw.setdefault("records", [])
        raw.setdefault("by_intent", {})
        return raw

    def _save_unlocked(self) -> None:
        records = self._data.get("records") or []
        if len(records) > MAX_RECORDS:
            self._data["records"] = records[-MAX_RECORDS:]
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def record(
        self,
        intent: str,
        path: str,
        ms: float,
        success: bool,
        *,
        request_id: Optional[str] = None,
        brain_path: Optional[str] = None,
    ) -> None:
        key = normalize_intent(intent) if intent else "unknown"
        route = (path or "unknown").strip().lower()
        if route not in ("tool", "cursor", "legacy", "meta"):
            route = "other"
        entry: dict[str, Any] = {
            "intent": key,
            "path": route,
            "ms": round(float(ms), 1),
            "success": bool(success),
            "ts": time.time(),
        }
        if request_id:
            entry["request_id"] = str(request_id)[:32]
        if brain_path:
            entry["brain_path"] = str(brain_path)[:16]
        with self._lock:
            self._data.setdefault("records", []).append(entry)
            bucket = self._data.setdefault("by_intent", {}).setdefault(
                key,
                {"tool": [], "cursor": [], "legacy": [], "meta": [], "other": []},
            )
            bucket.setdefault(route, []).append(
                {"ms": entry["ms"], "success": entry["success"]}
            )
            # Cap per-path samples
            if len(bucket[route]) > 40:
                bucket[route] = bucket[route][-40:]
            self._save_unlocked()

    def _success_samples(self, intent: str, path: str) -> list[float]:
        key = normalize_intent(intent)
        with self._lock:
            bucket = (self._data.get("by_intent") or {}).get(key) or {}
            rows = bucket.get(path) or []
        return [float(r["ms"]) for r in rows if r.get("success")]

    def prefer_tool(self, intent: str) -> bool:
        """True when tool path succeeded and was faster than cursor for this intent."""
        tool_ms = self._success_samples(intent, "tool")
        cursor_ms = self._success_samples(intent, "cursor")
        if len(tool_ms) < 1:
            return False
        tool_avg = sum(tool_ms) / len(tool_ms)
        if not cursor_ms:
            # Tool worked before — prefer it when router can match
            return tool_avg < 15_000
        cursor_avg = sum(cursor_ms) / len(cursor_ms)
        return tool_avg < cursor_avg

    def suggest_soft_timeout(self, intent: str, default: float) -> float:
        """Bump soft wait for known-slow successful Cursor tasks (p75 × 1.15)."""
        samples = self._success_samples(intent, "cursor")
        if len(samples) < MIN_SAMPLES_FOR_HINT:
            return float(default)
        ordered = sorted(samples)
        idx = max(0, int(len(ordered) * 0.75) - 1)
        p75 = ordered[idx]
        # Convert ms → seconds, add headroom, never shrink below default, cap 2×
        suggested = max(float(default), (p75 / 1000.0) * 1.15)
        return min(suggested, float(default) * 2.0)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._data.get("records") or [])
        return records[-max(1, limit) :]
