"""DecisionEngine — canonical Cursor gate for JarvisOS.handle_turn (O-04).

Does not replace CommandRouter (NL → tools). Complexity + degraded mode
live here so handle_turn does not duplicate gate logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.complexity import TaskComplexity, allows_cursor, classify_task_complexity


class BrainPath(str, Enum):
    FAST = "fast"
    META = "meta"
    LEGACY = "legacy"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    DEEP = "deep"


@dataclass(frozen=True)
class TurnDecision:
    complexity: TaskComplexity
    allow_cursor: bool
    preferred_path: BrainPath
    reason: str


def decide_turn(command: str, *, degraded: bool = False) -> TurnDecision:
    """Classify before local handlers — Cursor only when MEDIUM+ and not degraded."""
    complexity = classify_task_complexity(command)
    if degraded:
        return TurnDecision(
            complexity=complexity,
            allow_cursor=False,
            preferred_path=BrainPath.DEGRADED,
            reason="degraded_mode",
        )
    if not allows_cursor(complexity):
        return TurnDecision(
            complexity=complexity,
            allow_cursor=False,
            preferred_path=BrainPath.BLOCKED,
            reason=f"gate:{complexity.value}",
        )
    return TurnDecision(
        complexity=complexity,
        allow_cursor=True,
        preferred_path=BrainPath.DEEP,
        reason=f"cursor_fallback:{complexity.value}",
    )


def path_after_local(
    *,
    tool_hit: bool,
    meta_hit: bool = False,
    legacy_hit: bool = False,
    decision: Optional[TurnDecision] = None,
) -> BrainPath:
    """Resolve path after local handlers run (mirrors handle_turn order)."""
    if tool_hit:
        return BrainPath.FAST
    if meta_hit:
        return BrainPath.META
    if legacy_hit:
        return BrainPath.LEGACY
    if decision is None:
        return BrainPath.DEEP
    return decision.preferred_path


class DecisionEngine:
    """Single place for complexity + degraded Cursor policy."""

    def decide(self, command: str) -> TurnDecision:
        degraded = False
        try:
            from core.degraded import get_degraded_mode

            degraded = bool(get_degraded_mode().active) or (
                not get_degraded_mode().allow_cursor()
            )
        except Exception:
            degraded = False
        return decide_turn(command, degraded=degraded)

    def fallback_speech(self, decision: TurnDecision, command: str = "") -> str:
        from core.complexity import TaskComplexity, local_fallback_speech

        if decision.preferred_path is BrainPath.DEGRADED:
            if decision.complexity in (TaskComplexity.CHAT, TaskComplexity.SIMPLE):
                return local_fallback_speech(decision.complexity, command)
            return (
                "I'm in offline mode — local tools only. "
                "Try a direct command, or restore the model connection."
            )
        return local_fallback_speech(decision.complexity, command)
