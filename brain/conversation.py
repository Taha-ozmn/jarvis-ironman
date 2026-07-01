"""Short-term conversation memory for natural multi-turn dialogue."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class ConversationMemory:
    """Keeps recent turns so JARVIS can resolve 'it', 'that', follow-ups."""

    max_turns: int = 6
    _turns: deque[tuple[str, str]] = field(default_factory=deque)

    def add(self, user: str, assistant: str) -> None:
        user = user.strip()
        assistant = assistant.strip()
        if not user or not assistant:
            return
        self._turns.append((user, assistant))
        while len(self._turns) > self.max_turns:
            self._turns.popleft()

    def format_context(self, user_name: str = "sir") -> str:
        if not self._turns:
            return ""
        lines = [
            "[RECENT CONVERSATION — continue naturally; "
            f"{user_name} may refer to prior topics with 'it', 'that', 'again']"
        ]
        for user, assistant in self._turns:
            lines.append(f"{user_name}: {user}")
            lines.append(f"JARVIS: {assistant}")
        return "\n".join(lines)

    def clear(self) -> None:
        self._turns.clear()
