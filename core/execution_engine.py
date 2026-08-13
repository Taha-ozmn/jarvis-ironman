"""Execution engine — routes tool calls through permission + registry."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from core.event_bus import EventBus
from core.planner import Plan, PlanStep
from core.verification import should_verify, verify_tool_result
from security.audit import AuditLog
from security.confirmation import ConfirmationGate
from security.permissions import PermissionLevel, PermissionGate
from tools.base import ToolResult

logger = logging.getLogger(__name__)

LevelNotifyFn = Callable[[int, str, dict[str, Any]], None]
PlanDoneFn = Callable[["PlanRunResult"], None]


@dataclass
class ExecutionRequest:
    tool_name: str
    arguments: dict[str, Any]
    requested_by: str = "user"


@dataclass
class PlanRunResult:
    ok: bool
    plan_id: str
    completed: int
    total: int
    speech: str
    stopped_reason: str = ""
    resume_from: Optional[int] = None
    step_results: list[dict[str, Any]] = field(default_factory=list)


class ExecutionEngine:
    """Validate → authorize → execute → audit (+ plan / verify / retry)."""

    def __init__(
        self,
        registry: Any,
        permissions: PermissionGate,
        audit: AuditLog,
        bus: EventBus,
        confirmation: Optional[ConfirmationGate] = None,
        *,
        on_level_notify: Optional[LevelNotifyFn] = None,
        max_retries: int = 1,
        working_dir: Optional[Callable[[], Path]] = None,
        tasks: Any = None,
    ) -> None:
        self.registry = registry
        self.permissions = permissions
        self.audit = audit
        self.bus = bus
        self.confirmation = confirmation or ConfirmationGate()
        self.on_level_notify = on_level_notify
        self.max_retries = max(0, int(max_retries))
        self.working_dir = working_dir
        self.tasks = tasks
        self._plan_lock = threading.Lock()
        self._paused_plan: Optional[tuple[Plan, int]] = None

    def execute(self, request: ExecutionRequest) -> ToolResult:
        return self._execute_once(request)

    def execute_plan(
        self,
        plan: Plan,
        *,
        start_at: int = 0,
        persist_task: bool = True,
        requested_by: str = "planner",
    ) -> PlanRunResult:
        """Run plan steps sequentially with per-step audit + optional verify/retry."""
        if persist_task and self.tasks is not None and plan.task_id is None:
            try:
                meta = json.dumps(
                    {
                        "plan_id": plan.plan_id,
                        "steps": [
                            {"tool": s.tool_name, "args": s.arguments, "desc": s.description}
                            for s in plan.steps
                        ],
                    },
                    ensure_ascii=False,
                )
                task = self.tasks.create(
                    f"Plan: {plan.goal[:80]}",
                    description=plan.summary(max_chars=500),
                    priority=2,
                    metadata=meta,
                )
                plan.task_id = task.id
                self.tasks.update(task.id, status="in_progress")
            except Exception:
                logger.exception("failed to persist plan task")

        results: list[dict[str, Any]] = []
        speeches: list[str] = []
        start = max(0, int(start_at))

        for idx in range(start, len(plan.steps)):
            step = plan.steps[idx]
            outcome = self._run_step_with_retries(step, requested_by=requested_by)
            results.append(
                {
                    "index": idx,
                    "tool": step.tool_name,
                    "ok": outcome.ok,
                    "data": outcome.data if isinstance(outcome.data, str) else None,
                    "error": outcome.error,
                }
            )
            if outcome.ok and isinstance(outcome.data, str) and outcome.data.strip():
                speeches.append(outcome.data.strip())

            # Level-3 denial → pause for resume
            if not outcome.ok and "confirmation" in (outcome.error or "").lower():
                with self._plan_lock:
                    self._paused_plan = (plan, idx)
                speech = self._compose_speech(speeches, stopped=f"Paused at step {idx + 1}: confirmation required.")
                self._update_task_status(plan, "in_progress")
                self.bus.publish(
                    "plan.paused",
                    {"plan_id": plan.plan_id, "step": idx, "reason": "confirmation"},
                    source="execution_engine",
                )
                return PlanRunResult(
                    ok=False,
                    plan_id=plan.plan_id,
                    completed=idx,
                    total=len(plan.steps),
                    speech=speech,
                    stopped_reason="confirmation_required",
                    resume_from=idx,
                    step_results=results,
                )

            if not outcome.ok:
                speech = self._compose_speech(
                    speeches,
                    stopped=f"Stopped at step {idx + 1} ({step.tool_name}): {outcome.error}",
                )
                self._update_task_status(plan, "cancelled")
                self.bus.publish(
                    "plan.failed",
                    {"plan_id": plan.plan_id, "step": idx, "error": outcome.error},
                    source="execution_engine",
                )
                return PlanRunResult(
                    ok=False,
                    plan_id=plan.plan_id,
                    completed=idx,
                    total=len(plan.steps),
                    speech=speech,
                    stopped_reason=outcome.error or "step_failed",
                    resume_from=idx,
                    step_results=results,
                )

        self._update_task_status(plan, "done")
        with self._plan_lock:
            if self._paused_plan and self._paused_plan[0].plan_id == plan.plan_id:
                self._paused_plan = None
        speech = self._compose_speech(speeches, stopped="Plan complete.")
        self.bus.publish(
            "plan.completed",
            {"plan_id": plan.plan_id, "steps": len(plan.steps)},
            source="execution_engine",
        )
        return PlanRunResult(
            ok=True,
            plan_id=plan.plan_id,
            completed=len(plan.steps),
            total=len(plan.steps),
            speech=speech,
            step_results=results,
        )

    def resume_paused_plan(self) -> Optional[PlanRunResult]:
        with self._plan_lock:
            paused = self._paused_plan
        if not paused:
            return None
        plan, idx = paused
        return self.execute_plan(plan, start_at=idx, persist_task=False)

    def execute_plan_background(
        self,
        plan: Plan,
        *,
        on_done: Optional[PlanDoneFn] = None,
        start_at: int = 0,
    ) -> str:
        """Run long plans on a daemon thread — does not block voice loop."""

        def _worker() -> None:
            try:
                result = self.execute_plan(plan, start_at=start_at)
            except Exception as err:
                logger.exception("background plan crashed")
                result = PlanRunResult(
                    ok=False,
                    plan_id=plan.plan_id,
                    completed=0,
                    total=len(plan.steps),
                    speech=f"Plan failed: {err}",
                    stopped_reason=str(err),
                )
            if on_done:
                try:
                    on_done(result)
                except Exception:
                    logger.exception("plan on_done failed")

        threading.Thread(target=_worker, daemon=True, name=f"plan-{plan.plan_id}").start()
        return f"Running plan in background ({len(plan.steps)} steps)."

    def _run_step_with_retries(self, step: PlanStep, *, requested_by: str) -> ToolResult:
        attempts = self.max_retries + 1
        last = ToolResult(ok=False, error="no attempt")
        for attempt in range(attempts):
            last = self._execute_once(
                ExecutionRequest(step.tool_name, dict(step.arguments), requested_by=requested_by)
            )
            if not last.ok:
                if "confirmation" in (last.error or "").lower():
                    return last
                if attempt < attempts - 1:
                    self.audit.write(
                        action=f"plan.retry.{step.tool_name}",
                        level=0,
                        success=False,
                        details={"attempt": attempt + 1, "error": last.error},
                    )
                    continue
                return last

            if should_verify(step.tool_name, step_verify=step.verify):
                outcome = verify_tool_result(
                    step.tool_name,
                    step.arguments,
                    last,
                    working_dir=self.working_dir,
                )
                self.audit.write(
                    action=f"plan.verify.{step.tool_name}",
                    level=0,
                    success=outcome.ok,
                    details={"message": outcome.message, "alternate": outcome.alternate},
                )
                if outcome.ok:
                    return last
                last = ToolResult(
                    ok=False,
                    error=f"Verification failed: {outcome.message}. {outcome.alternate}",
                )
                if attempt < attempts - 1:
                    continue
                return last
            return last
        return last

    def _execute_once(self, request: ExecutionRequest) -> ToolResult:
        tool = self.registry.get(request.tool_name)
        if tool is None:
            result = ToolResult(ok=False, error=f"Unknown tool: {request.tool_name}")
            self._audit_failure(request, result.error or "")
            return result

        effective = tool.permission_level
        resolve = getattr(tool, "resolve_permission", None)
        if callable(resolve):
            try:
                effective = PermissionLevel(resolve(request.arguments))
            except Exception:
                effective = tool.permission_level

        if not self.permissions.allows(effective):
            msg = (
                f"Permission denied for {request.tool_name} "
                f"(requires level {int(effective)})"
            )
            result = ToolResult(ok=False, error=msg)
            self._audit_failure(request, msg, level=effective)
            return result

        if effective >= PermissionLevel.SYSTEM:
            self._notify_level(int(effective), tool.name, request.arguments)

        if effective >= PermissionLevel.DANGEROUS:
            if not self.confirmation.require(
                request.tool_name,
                details=str(request.arguments),
                level=int(effective),
            ):
                result = ToolResult(ok=False, error="User confirmation required")
                self._audit_failure(request, result.error or "", level=effective)
                return result

        validation_error = self.registry.validate_input(tool.name, request.arguments)
        if validation_error:
            result = ToolResult(ok=False, error=validation_error)
            self._audit_failure(request, validation_error, level=effective)
            return result

        self.bus.publish(
            "tool.executing",
            {
                "tool": tool.name,
                "args": request.arguments,
                "level": int(effective),
            },
            source="execution_engine",
        )
        try:
            result = tool.run(request.arguments)
        except Exception as err:
            logger.exception("Tool %s crashed", tool.name)
            result = ToolResult(ok=False, error=str(err))

        self.audit.write(
            action=f"tool.{tool.name}",
            level=int(effective),
            success=result.ok,
            details={
                "args": request.arguments,
                "error": result.error,
                "requested_by": request.requested_by,
            },
        )
        self.bus.publish(
            "tool.completed",
            {"tool": tool.name, "ok": result.ok, "error": result.error},
            source="execution_engine",
        )
        return result

    def _update_task_status(self, plan: Plan, status: str) -> None:
        if self.tasks is None or plan.task_id is None:
            return
        try:
            self.tasks.update(plan.task_id, status=status)
        except Exception:
            logger.exception("plan task status update failed")

    @staticmethod
    def _compose_speech(parts: list[str], *, stopped: str) -> str:
        bits = [p for p in parts if p][-3:]
        bits.append(stopped)
        text = " ".join(bits)
        if len(text) > 320:
            text = text[:317] + "…"
        return text

    def _notify_level(self, level: int, tool_name: str, args: dict[str, Any]) -> None:
        payload = {"level": level, "tool": tool_name, "args": args}
        self.bus.publish("permission.notify", payload, source="execution_engine")
        if self.on_level_notify:
            try:
                self.on_level_notify(level, tool_name, args)
            except Exception:
                logger.exception("level notify failed")

    def _audit_failure(
        self,
        request: ExecutionRequest,
        error: str,
        *,
        level: Optional[PermissionLevel] = None,
    ) -> None:
        self.audit.write(
            action=f"tool.{request.tool_name}",
            level=(level or PermissionLevel.READ).value,
            success=False,
            details={"args": request.arguments, "error": error},
        )
