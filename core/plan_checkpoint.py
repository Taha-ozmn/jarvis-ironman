"""Persist plan execution checkpoints for resume-after-failure."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

from core.planner import Plan, PlanStep

CHECKPOINT_KEY = "plan_checkpoint"


def plan_to_dict(plan: Plan, *, resume_from: int = 0, reason: str = "") -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "goal": plan.goal,
        "complex": plan.complex,
        "source": plan.source,
        "task_id": plan.task_id,
        "resume_from": int(resume_from),
        "reason": (reason or "")[:240],
        "steps": [
            {
                "tool_name": s.tool_name,
                "arguments": dict(s.arguments or {}),
                "description": s.description,
                "verify": bool(s.verify),
            }
            for s in plan.steps
        ],
    }


def plan_from_dict(data: dict[str, Any]) -> tuple[Plan, int]:
    steps = [
        PlanStep(
            tool_name=str(item.get("tool_name") or ""),
            arguments=dict(item.get("arguments") or {}),
            description=str(item.get("description") or ""),
            verify=bool(item.get("verify", False)),
        )
        for item in (data.get("steps") or [])
        if isinstance(item, dict) and item.get("tool_name")
    ]
    plan = Plan(
        goal=str(data.get("goal") or ""),
        steps=steps,
        plan_id=str(data.get("plan_id") or ""),
        complex=bool(data.get("complex", True)),
        task_id=data.get("task_id"),
        source=str(data.get("source") or "checkpoint"),
    )
    resume_from = int(data.get("resume_from") or 0)
    return plan, max(0, resume_from)


class PlanCheckpointStore:
    """Session-scoped plan checkpoint in ContextManager extras."""

    def __init__(self, context: Any, *, path: Optional[Path] = None) -> None:
        self._context = context
        self._path = Path(path) if path else None
        self._lock = threading.Lock()

    def save(self, plan: Plan, resume_from: int, reason: str = "") -> None:
        payload = plan_to_dict(plan, resume_from=resume_from, reason=reason)
        self._context.set_extra(CHECKPOINT_KEY, payload)
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(self._path.suffix + ".tmp")
            with self._lock:
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )
                os.replace(temporary, self._path)

    def load(self) -> Optional[tuple[Plan, int, dict[str, Any]]]:
        raw = self._context.get_extra(CHECKPOINT_KEY)
        if not isinstance(raw, dict) and self._path is not None:
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._context.set_extra(CHECKPOINT_KEY, raw)
            except (OSError, ValueError, TypeError):
                raw = None
        if not isinstance(raw, dict) or not raw.get("steps"):
            return None
        plan, resume_from = plan_from_dict(raw)
        if not plan.steps:
            return None
        return plan, resume_from, raw

    def clear(self) -> None:
        self._context.set_extra(CHECKPOINT_KEY, None)
        if self._path is not None:
            try:
                self._path.unlink(missing_ok=True)
            except OSError:
                pass

    def has_checkpoint(self) -> bool:
        return self.load() is not None

    def summary(self) -> str:
        loaded = self.load()
        if not loaded:
            return ""
        plan, idx, raw = loaded
        total = len(plan.steps)
        step_no = min(idx + 1, total) if total else 0
        reason = str(raw.get("reason") or "").strip()
        base = f"«{plan.goal[:80]}» — step {step_no}/{total}"
        return f"{base} ({reason})" if reason else base
