"""Structured validation for planner output and tool intents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.planner import ALLOWED_PLAN_TOOLS, Plan, PlanStep
from security.risk import is_blocked_shell

# Minimal argument type expectations per tool (extend as needed).
_TOOL_ARG_RULES: dict[str, dict[str, str]] = {
    "memory.search": {"query": "str"},
    "memory.save": {"content": "str"},
    "task.create": {"title": "str"},
    "task.list": {},
    "git.commit": {"message": "str"},
    "dev.run_command": {"command": "str"},
    "research.topic": {"query": "str"},
    "browser.open_url": {"url": "str"},
    "media.play": {"query": "str"},
    "plan.run": {"goal": "str"},
}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    sanitized_steps: list[PlanStep] = field(default_factory=list)


def _check_type(value: Any, expected: str) -> bool:
    if expected == "str":
        return isinstance(value, str) and bool(value.strip())
    if expected == "int":
        return isinstance(value, int) or (
            isinstance(value, str) and str(value).strip().isdigit()
        )
    if expected == "bool":
        return isinstance(value, bool)
    if expected == "dict":
        return isinstance(value, dict)
    return True


def validate_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> list[str]:
    rules = _TOOL_ARG_RULES.get(tool_name)
    if not rules:
        return []
    errors: list[str] = []
    args = arguments or {}
    for key, expected in rules.items():
        if key not in args:
            errors.append(f"{tool_name}: missing required argument '{key}'")
            continue
        if not _check_type(args.get(key), expected):
            errors.append(f"{tool_name}: invalid type for '{key}' (expected {expected})")
    return errors


def validate_plan(plan: Plan) -> ValidationResult:
    """Reject or sanitize LLM/heuristic plans before execution."""
    errors: list[str] = []
    sanitized: list[PlanStep] = []
    if not plan.steps:
        return ValidationResult(ok=False, errors=["Plan has no steps"])

    for idx, step in enumerate(plan.steps, 1):
        name = (step.tool_name or "").strip()
        if not name:
            errors.append(f"Step {idx}: empty tool name")
            continue
        if name not in ALLOWED_PLAN_TOOLS:
            errors.append(f"Step {idx}: tool '{name}' not in allowlist")
            continue
        if not isinstance(step.arguments, dict):
            errors.append(f"Step {idx}: arguments must be a dict")
            continue
        args = dict(step.arguments)
        arg_errors = validate_tool_arguments(name, args)
        errors.extend(arg_errors)
        if name == "dev.run_command" and is_blocked_shell(str(args.get("command") or "")):
            errors.append(f"Step {idx}: catastrophic command blocked")
        if not arg_errors:
            sanitized.append(
                PlanStep(
                    tool_name=name,
                    arguments=args,
                    description=(step.description or name)[:120],
                    verify=bool(step.verify),
                )
            )

    return ValidationResult(
        ok=bool(sanitized) and not errors,
        errors=errors,
        sanitized_steps=sanitized,
    )


def sanitize_plan(plan: Plan) -> Plan:
    """Return a plan with only schema-valid steps (drops invalid ones)."""
    result = validate_plan(plan)
    if not result.sanitized_steps:
        return Plan(goal=plan.goal, steps=[], complex=plan.complex, source=plan.source)
    return Plan(
        goal=plan.goal,
        steps=result.sanitized_steps[:12],
        plan_id=plan.plan_id,
        complex=plan.complex,
        task_id=plan.task_id,
        source=plan.source,
    )
