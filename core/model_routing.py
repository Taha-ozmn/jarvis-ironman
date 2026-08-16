"""Model routing helpers — cheap vs smart by complexity (Phase 6)."""

from __future__ import annotations

from typing import Optional

from brain.model_router import ModelRouter
from core.complexity import TaskComplexity
from core.degraded import get_degraded_mode


def route_model(
    router: ModelRouter,
    *,
    complexity: TaskComplexity | str,
    command: str = "",
) -> str:
    """Pick a model ID. Degraded mode always returns the cheap chat model."""
    if get_degraded_mode().active:
        return router.pick("chat")
    key = complexity.value if isinstance(complexity, TaskComplexity) else str(complexity)
    if key in ("chat", "simple", "medium", "complex", "autonomous"):
        return router.pick_for_complexity(key)
    if command:
        return router.pick(router.classify(command))
    return router.pick("default")


def is_cheap_route(complexity: TaskComplexity | str) -> bool:
    key = complexity.value if isinstance(complexity, TaskComplexity) else str(complexity)
    return key in ("chat", "simple")
