"""Short-term conversation memory for natural multi-turn dialogue."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ConversationMemory:
    """Keeps recent turns so JARVIS can resolve 'it', 'that', follow-ups.

    This is working memory for the voice session — Second Brain continuity.
    """

    max_turns: int = 40
    active_topic: str = ""
    last_user_intent: str = ""
    _turns: deque[tuple[str, str]] = field(default_factory=deque)

    def add(self, user: str, assistant: str) -> None:
        user = user.strip()
        assistant = assistant.strip()
        if not user or not assistant:
            return
        self._turns.append((user, assistant))
        self.last_user_intent = user
        # Lightweight topic: first ~8 words of latest user turn
        words = user.split()
        if len(words) >= 2:
            self.active_topic = " ".join(words[:8])
        while len(self._turns) > self.max_turns:
            self._turns.popleft()

    def format_context(self, user_name: str = "sir") -> str:
        if not self._turns:
            return ""
        lines = [
            "[WORKING MEMORY — continuous Second Brain session]",
            "Continue the SAME conversation. Never restart or ask what we were "
            "talking about if context is below. Resolve pronouns (it/that/onu/bunu) "
            "from prior turns. Build on prior decisions.",
        ]
        if self.active_topic:
            lines.append(f"Active topic: {self.active_topic}")
        for user, assistant in self._turns:
            # Keep assistant snippets short in prompt to save tokens
            a = assistant if len(assistant) <= 220 else assistant[:217] + "…"
            lines.append(f"{user_name}: {user}")
            lines.append(f"JARVIS: {a}")
        return "\n".join(lines)

    def summary_line(self) -> str:
        if not self._turns:
            return ""
        n = len(self._turns)
        topic = self.active_topic or "general"
        return f"{n} turns in session; topic≈{topic}"

    def clear(self) -> None:
        self._turns.clear()
        self.active_topic = ""
        self.last_user_intent = ""

    @property
    def turn_count(self) -> int:
        return len(self._turns)
