"""Safe coding-task orchestration for JARVIS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from core.agent_profiles import (
    CODING_TOOLS,
    coding_analyze_plan,
    coding_fix_plan,
    filter_plan_steps,
    looks_like_coding_analyze,
)
from core.intent_schema import sanitize_plan
from core.planner import Plan, Planner


@dataclass(frozen=True)
class CodingTask:
    """Normalized coding request."""

    goal: str
    mode: str  # analyze | fix | implement | explain
    requires_deep_brain: bool = False


def classify_coding_task(goal: str) -> CodingTask:
    """Classify coding work without an LLM round-trip."""
    text = (goal or "").strip()
    lower = text.lower()
    if looks_like_coding_analyze(text):
        return CodingTask(text, "analyze")
    if any(word in lower for word in ("fix", "debug", "bug", "hata", "düzelt", "duzelt")):
        return CodingTask(text, "fix")
    if any(
        word in lower
        for word in (
            "write code",
            "kod yaz",
            "implement",
            "create a script",
            "fonksiyon yaz",
            "dosya oluştur",
            "dosya olustur",
        )
    ):
        return CodingTask(text, "implement", requires_deep_brain=True)
    return CodingTask(text, "explain", requires_deep_brain=True)


class CodingAgent:
    """Coordinate local coding plans and defer implementation to Cursor."""

    def __init__(self, os_core: Any, *, planner: Optional[Planner] = None) -> None:
        self.os_core = os_core
        self.planner = planner or os_core.planner

    def build_plan(self, goal: str) -> Plan:
        task = classify_coding_task(goal)
        if task.mode == "analyze":
            plan = coding_analyze_plan(
                max_steps=int(getattr(self.planner, "max_steps", 4)),
            )
        elif task.mode == "fix":
            plan = coding_fix_plan(
                max_steps=int(getattr(self.planner, "max_steps", 4)),
            )
        else:
            plan = self.planner.create(goal)
        plan = filter_plan_steps(plan, "coding")
        return sanitize_plan(plan)

    def run(self, goal: str, *, background: bool = True) -> str:
        """Run safe analysis/fix work; implementation uses DeepBrain."""
        task = classify_coding_task(goal)
        if task.requires_deep_brain:
            return (
                "This coding task requires the deep coding brain. "
                "I will edit, test, and verify the workspace before reporting."
            )
        plan = self.build_plan(goal)
        if not plan.steps:
            return "I could not build a safe coding plan for that request."
        result = self.os_core.execution.execute_plan_background(plan) if background else (
            self.os_core.execution.execute_plan(plan)
        )
        if background:
            return f"Started coding {task.mode} in the background."
        return result.speech or "Coding task finished without a report."

    @staticmethod
    def allowed_tools() -> frozenset[str]:
        return CODING_TOOLS
