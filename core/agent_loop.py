"""Think → plan → act → observe → verify loop with a hard iteration cap.

Wraps the existing Planner + ExecutionEngine. Catastrophic shell blocks stay
in ExecutionEngine regardless of full_autonomy.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def run_agent_loop(
    os_core: Any,
    goal: str,
    *,
    max_iterations: Optional[int] = None,
    background: bool = False,
) -> str:
    """Local tool loop — never spawns Cursor. Fast path stays outside this."""
    cap = int(
        max_iterations
        if max_iterations is not None
        else getattr(os_core, "deep_max_iterations", 8) or 8
    )
    cap = max(1, min(cap, 16))
    planner = os_core.planner
    execution = os_core.execution
    last = ""
    observed = (goal or "").strip()
    if not observed:
        return "Goal is empty."

    plan = planner.create(observed)
    if not plan.steps:
        return (
            "That looks like a one-step request — try the command directly, "
            "or say «plan …»."
        )
    if not background and len(plan.steps) >= 3:
        background = True

    if background:

        def _done(result: Any) -> None:
            speak = getattr(os_core, "_speak", None)
            text = getattr(result, "speech", None) or ""
            if speak and text:
                try:
                    speak(str(text)[:280])
                except Exception:
                    logger.exception("agent loop notify failed")

        execution.execute_plan_background(plan, on_done=_done)
        return f"Started — I'll report when done. {plan.summary(max_chars=100)}"

    for iteration in range(cap):
        if iteration > 0:
            plan = planner.create(observed)
            if not plan.steps:
                return last or "Could not build a plan — try the command directly."
        result = execution.execute_plan(plan)
        last = (result.speech or "").strip()
        if result.ok:
            return last or "Plan complete."
        reason = result.stopped_reason or last or "step failed"
        logger.info(
            "agent_loop iter=%s/%s failed: %s",
            iteration + 1,
            cap,
            reason[:120],
        )
        observed = f"{goal}\nObservation (turn {iteration + 1}): {reason[:240]}"
    return last or f"Tried {cap} turns; no verified result."
