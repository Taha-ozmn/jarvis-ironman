"""Session / runtime context for JARVIS 2.0."""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Turn:
    command: str
    response: str
    at: float = field(default_factory=time.time)


@dataclass
class SessionContext:
    """Mutable session state shared across subsystems."""

    user_name: str = "sir"
    language: str = "en-GB"
    model: str = "gemini-3-flash"
    listening_enabled: bool = True
    status: str = "idle"
    last_command: str = ""
    last_response: str = ""
    active_project_id: Optional[int] = None
    extras: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)


FOLLOWUP_MARKERS = (
    "şimdi",
    "simdi",
    "now ",
    "then ",
    "also ",
    "bir de",
    "onu",
    "bunu",
    "that",
    "it ",
    "the same",
    "yine",
    "again",
)

ENTITY_HINTS = (
    "github",
    "chrome",
    "safari",
    "spotify",
    "cursor",
    "terminal",
    "finder",
    "slack",
    "discord",
    "notes",
    "mail",
    "youtube",
    "jettel",
    "passo",
    "gnb",
    "jarvis",
)


class ContextManager:
    """Thread-safe holder for current session context + short-term turns."""

    def __init__(
        self,
        initial: Optional[SessionContext] = None,
        *,
        max_turns: int = 8,
    ) -> None:
        self._lock = threading.RLock()
        self._ctx = initial or SessionContext()
        self._turns: deque[Turn] = deque(maxlen=max(2, int(max_turns)))
        self._last_entity: Optional[str] = None

    @property
    def current(self) -> SessionContext:
        with self._lock:
            return self._ctx

    def update(self, **kwargs: Any) -> SessionContext:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._ctx, key):
                    setattr(self._ctx, key, value)
                else:
                    self._ctx.extras[key] = value
            return self._ctx

    def set_extra(self, key: str, value: Any) -> None:
        with self._lock:
            self._ctx.extras[key] = value

    def get_extra(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._ctx.extras.get(key, default)

    def record_turn(self, command: str, response: str) -> None:
        with self._lock:
            self._ctx.last_command = command
            self._ctx.last_response = response
            self._turns.append(Turn(command=command, response=response))
            entity = self._extract_entity(command) or self._extract_entity(response)
            if entity:
                self._last_entity = entity
                self._ctx.extras["last_entity"] = entity

    def resolve_followup(self, command: str) -> str:
        """Expand short follow-ups like 'şimdi GitHub'ı aç' using last entity if needed."""
        text = (command or "").strip()
        if not text:
            return text
        lower = text.lower()
        # If command already has a clear entity, keep it
        if self._extract_entity(text):
            with self._lock:
                ent = self._extract_entity(text)
                if ent:
                    self._last_entity = ent
            return text
        # Relative open: "şimdi onu aç" / "open it"
        if any(m in lower for m in FOLLOWUP_MARKERS) or lower in (
            "aç",
            "open",
            "onu aç",
            "open it",
            "open that",
        ):
            with self._lock:
                entity = self._last_entity or self._ctx.extras.get("last_entity")
            if entity and any(k in lower for k in ("aç", "open", "launch", "göster", "show")):
                return f"open {entity}"
            if entity and len(text.split()) <= 4:
                # "şimdi github" style already has entity via extract — else append
                if entity not in lower:
                    return f"{text} {entity}".strip()
        return text

    def recent_turns(self, limit: int = 4) -> list[dict[str, str]]:
        with self._lock:
            items = list(self._turns)[-limit:]
            return [{"command": t.command, "response": t.response} for t in items]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "user_name": self._ctx.user_name,
                "language": self._ctx.language,
                "model": self._ctx.model,
                "listening_enabled": self._ctx.listening_enabled,
                "status": self._ctx.status,
                "last_command": self._ctx.last_command,
                "last_response": self._ctx.last_response,
                "last_entity": self._last_entity,
                "active_project_id": self._ctx.active_project_id,
                "extras": dict(self._ctx.extras),
                "started_at": self._ctx.started_at,
                "uptime_seconds": time.time() - self._ctx.started_at,
                "recent_turns": [
                    {"command": t.command, "response": t.response[:120]}
                    for t in list(self._turns)[-3:]
                ],
            }

    @staticmethod
    def _extract_entity(text: str) -> Optional[str]:
        lower = (text or "").lower()
        for hint in ENTITY_HINTS:
            if hint in lower:
                return hint
        # URL host
        m = re.search(r"https?://(?:www\.)?([a-z0-9\-]+)", lower)
        if m:
            return m.group(1)
        return None
