"""Thin decision facade — documents turn routing order (O-04 prep).

Does not replace CommandRouter or complexity gate. Callers still use
JarvisOS.handle_turn; this module records the intended decision path.
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
    """Classify before execution — Cursor only when MEDIUM+ and not degraded."""
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
            preferred_path=BrainPath.BLOCKED
            if complexity is TaskComplexity.SIMPLE
            else BrainPath.META,
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
