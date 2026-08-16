"""Turn outcome from JarvisOS.handle_turn (Phase 2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.complexity import TaskComplexity


@dataclass
class TurnResult:
    """Result of one user turn through the OS facade."""

    speech: Optional[str]
    allow_cursor: bool
    complexity: TaskComplexity
    request_id: str
    brain_path: str  # fast | meta | legacy | deep | blocked
    reason: str = ""

    @property
    def handled(self) -> bool:
        return self.speech is not None
