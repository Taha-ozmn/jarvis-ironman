"""Internal reasoning trace — visible JARVIS thinking phases for HUD."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

TraceCallback = Callable[[dict[str, Any]], None]


class ThinkingPhase(str, Enum):
    UNDERSTANDING = "understanding"
    DECIDING = "deciding"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RESPONDING = "responding"
    IDLE = "idle"


_PHASE_LABELS: dict[ThinkingPhase, str] = {
    ThinkingPhase.UNDERSTANDING: "Analyzing",
    ThinkingPhase.DECIDING: "Deciding",
    ThinkingPhase.PLANNING: "Planning",
    ThinkingPhase.EXECUTING: "Executing",
    ThinkingPhase.VERIFYING: "Verifying",
    ThinkingPhase.RESPONDING: "Responding",
    ThinkingPhase.IDLE: "Standing by",
}


@dataclass
class TraceEntry:
    phase: ThinkingPhase
    message: str
    ts: float = field(default_factory=time.time)


class ThinkingTrace:
    """Collects and broadcasts short internal monologue lines."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        on_update: Optional[TraceCallback] = None,
        max_history: int = 12,
    ) -> None:
        self.enabled = enabled
        self._on_update = on_update
        self._history: list[TraceEntry] = []
        self._max_history = max(4, int(max_history))
        self._current: Optional[TraceEntry] = None

    def set_callback(self, on_update: Optional[TraceCallback]) -> None:
        self._on_update = on_update

    def emit(self, phase: ThinkingPhase | str, message: str) -> None:
        if not self.enabled:
            return
        try:
            ph = phase if isinstance(phase, ThinkingPhase) else ThinkingPhase(str(phase))
        except ValueError:
            ph = ThinkingPhase.UNDERSTANDING
        text = (message or "").strip()
        if not text:
            text = _PHASE_LABELS.get(ph, "Thinking")
        entry = TraceEntry(phase=ph, message=text)
        self._current = entry
        self._history.append(entry)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]
        self._notify(entry)

    def clear(self) -> None:
        self._current = None

    def current_label(self) -> str:
        if self._current is None:
            return ""
        label = _PHASE_LABELS.get(self._current.phase, "Thinking")
        return f"{label}: {self._current.message}"

    def recent_lines(self, *, limit: int = 4) -> list[str]:
        out: list[str] = []
        for entry in self._history[-limit:]:
            label = _PHASE_LABELS.get(entry.phase, "Thinking")
            out.append(f"{label}: {entry.message}")
        return out

    def as_dict(self) -> dict[str, Any]:
        cur = self._current
        return {
            "phase": cur.phase.value if cur else "",
            "message": cur.message if cur else "",
            "label": self.current_label(),
            "recent": self.recent_lines(),
        }

    def _notify(self, entry: TraceEntry) -> None:
        if not self._on_update:
            return
        label = _PHASE_LABELS.get(entry.phase, "Thinking")
        try:
            self._on_update(
                {
                    "phase": entry.phase.value,
                    "message": entry.message,
                    "label": f"{label}: {entry.message}",
                }
            )
        except Exception:
            pass
