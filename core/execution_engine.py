"""Execution engine — routes tool calls through permission + registry."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from core.autonomy import AutonomyPolicy, autonomy_policy, requires_confirmation
from core.cancellation import (
    CancellationToken,
    cancel_active,
    set_active_token,
)
from core.event_bus import EventBus
from core.evidence import EvidenceClock, ExecutionEvidence
from core.planner import Plan, PlanStep
from core.recovery import (
    DEFAULT_MAX_RETRIES,
    classify_error,
    is_retryable,
    log_failure,
    sleep_backoff,
    user_safe_speech,
)
from core.request_context import get_request_id
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
        tool_max_retries: int = DEFAULT_MAX_RETRIES,
        working_dir: Optional[Callable[[], Path]] = None,
        tasks: Any = None,
        autonomy: Optional[AutonomyPolicy] = None,
        auto_approve_dangerous: bool = False,
        max_agent_steps: int = 12,
    ) -> None:
        self.registry = registry
        self.permissions = permissions
        self.audit = audit
        self.bus = bus
        self.confirmation = confirmation or ConfirmationGate()
        self.on_level_notify = on_level_notify
        self.max_retries = max(0, int(max_retries))
        # Single-tool path: max attempts = tool_max_retries (capped at 3)
        self.tool_max_retries = max(1, min(int(tool_max_retries), DEFAULT_MAX_RETRIES))
        self.working_dir = working_dir
        self.tasks = tasks
        self.autonomy = autonomy or autonomy_policy(4)
        self.auto_approve_dangerous = bool(auto_approve_dangerous)
        self.max_agent_steps = max(1, min(64, int(max_agent_steps)))
        self._plan_lock = threading.Lock()
        self._paused_plan: Optional[tuple[Plan, int]] = None
        self._cancel_token = CancellationToken()
        self.last_evidence: list[ExecutionEvidence] = []
        self.last_plan_progress: Optional[dict[str, Any]] = None
        self.plan_timeline: list[dict[str, Any]] = []

    def cancel_active_plan(self, reason: str = "user_cancel") -> bool:
        """Signal cancel for the in-flight plan (cooperative)."""
        self._cancel_token.cancel(reason)
        return cancel_active(reason)

    def execute(self, request: ExecutionRequest) -> ToolResult:
        """Execute one tool with bounded retry + exponential backoff + verify."""
        attempts = self.tool_max_retries
        last = ToolResult(ok=False, error="no attempt")
        for attempt in range(attempts):
            last = self._execute_once(request)
            if last.ok:
                if not should_verify(request.tool_name, step_verify=False):
                    return last
                outcome = verify_tool_result(
                    request.tool_name,
                    request.arguments,
                    last,
                    working_dir=self.working_dir,
                )
                self.audit.write(
                    action=f"verify.{request.tool_name}",
                    level=0,
                    success=outcome.ok,
                    details={"message": outcome.message, "alternate": outcome.alternate},
                )
                if outcome.ok:
                    if last.evidence is not None:
                        last.evidence["verified"] = True
                        last.evidence["status"] = "verified"
                    return last
                last = ToolResult(
                    ok=False,
                    error=user_safe_speech(
                        f"Verification failed: {outcome.message}. {outcome.alternate}"
                    ),
                    evidence=last.evidence,
                )
            else:
                # Never retry confirmation / permission denials
                err = last.error or ""
                if "confirmation" in err.lower() or "permission denied" in err.lower():
                    return ToolResult(ok=False, error=user_safe_speech(err), evidence=last.evidence)
                cls = classify_error(err)
                log_failure(request.tool_name, err, error_class=cls, attempt=attempt + 1)
                if not is_retryable(cls, err) or attempt >= attempts - 1:
                    return ToolResult(
                        ok=False,
                        error=user_safe_speech(
                            err,
                            target=str(request.arguments.get("name") or ""),
                            error_class=cls,
                        ),
                        evidence=last.evidence,
                    )
                self.audit.write(
                    action=f"tool.retry.{request.tool_name}",
                    level=0,
                    success=False,
                    details={
                        "attempt": attempt + 1,
                        "error_class": cls.value,
                        "error": err[:200],
                    },
                )
                sleep_backoff(attempt)
                continue

            # verify failed path — retry if attempts remain
            if attempt < attempts - 1:
                sleep_backoff(attempt)
                continue
            return last
        return last

    def execute_plan(
        self,
        plan: Plan,
        *,
        start_at: int = 0,
        persist_task: bool = True,
        requested_by: str = "planner",
        dry_run: bool = False,
    ) -> PlanRunResult:
        """Run plan steps sequentially with per-step audit + optional verify/retry."""
        if len(plan.steps) > self.max_agent_steps:
            plan.steps = list(plan.steps[: self.max_agent_steps])
            self.bus.publish(
                "plan.truncated",
                {
                    "plan_id": plan.plan_id,
                    "max_agent_steps": self.max_agent_steps,
                },
                source="execution_engine",
            )

        if dry_run:
            speech = f"DRY RUN — no tools executed. {plan.summary(max_chars=400)}"
            return PlanRunResult(
                ok=True,
                plan_id=plan.plan_id,
                completed=0,
                total=len(plan.steps),
                speech=speech,
                stopped_reason="dry_run",
            )

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
                self.tasks.update(task.id, status="running")
            except Exception:
                logger.exception("failed to persist plan task")

        results: list[dict[str, Any]] = []
        speeches: list[str] = []
        start = max(0, int(start_at))
        self._cancel_token.reset()
        set_active_token(self._cancel_token)
        total = len(plan.steps)
        self._set_plan_progress(
            {
                "plan_id": plan.plan_id,
                "goal": plan.goal[:120],
                "step": start,
                "total": total,
                "tool": "",
                "description": "starting",
                "phase": "started",
                "ok": None,
            }
        )
        self.bus.publish(
            "plan.started",
            {
                "plan_id": plan.plan_id,
                "goal": plan.goal[:160],
                "total": total,
                "start_at": start,
            },
            source="execution_engine",
        )

        try:
            for idx in range(start, len(plan.steps)):
                if self._cancel_token.is_cancelled:
                    speech = self._compose_speech(
                        speeches,
                        stopped=f"Cancelled at step {idx + 1}.",
                    )
                    self._update_task_status(plan, "cancelled")
                    self._set_plan_progress(
                        {
                            "plan_id": plan.plan_id,
                            "goal": plan.goal[:120],
                            "step": idx,
                            "total": total,
                            "tool": "",
                            "description": self._cancel_token.reason or "cancelled",
                            "phase": "cancelled",
                            "ok": False,
                        }
                    )
                    self.bus.publish(
                        "plan.cancelled",
                        {
                            "plan_id": plan.plan_id,
                            "step": idx,
                            "reason": self._cancel_token.reason,
                        },
                        source="execution_engine",
                    )
                    return PlanRunResult(
                        ok=False,
                        plan_id=plan.plan_id,
                        completed=idx,
                        total=total,
                        speech=speech,
                        stopped_reason=self._cancel_token.reason or "cancelled",
                        resume_from=idx,
                        step_results=results,
                    )

                step = plan.steps[idx]
                self._set_plan_progress(
                    {
                        "plan_id": plan.plan_id,
                        "goal": plan.goal[:120],
                        "step": idx + 1,
                        "total": total,
                        "tool": step.tool_name,
                        "description": step.description or step.tool_name,
                        "phase": "running",
                        "ok": None,
                    }
                )
                self.bus.publish(
                    "plan.step.progress",
                    {
                        "plan_id": plan.plan_id,
                        "step": idx + 1,
                        "total": total,
                        "tool": step.tool_name,
                        "description": step.description or step.tool_name,
                        "phase": "started",
                    },
                    source="execution_engine",
                )
                outcome = self._run_step_with_retries(step, requested_by=requested_by)
                results.append(
                    {
                        "index": idx,
                        "tool": step.tool_name,
                        "ok": outcome.ok,
                        "data": outcome.data if isinstance(outcome.data, str) else None,
                        "error": outcome.error,
                        "evidence": outcome.evidence,
                    }
                )
                self.bus.publish(
                    "plan.step.progress",
                    {
                        "plan_id": plan.plan_id,
                        "step": idx + 1,
                        "total": total,
                        "tool": step.tool_name,
                        "description": step.description or step.tool_name,
                        "phase": "completed" if outcome.ok else "failed",
                        "ok": outcome.ok,
                        "error": outcome.error,
                    },
                    source="execution_engine",
                )
                self._set_plan_progress(
                    {
                        "plan_id": plan.plan_id,
                        "goal": plan.goal[:120],
                        "step": idx + 1,
                        "total": total,
                        "tool": step.tool_name,
                        "description": step.description or step.tool_name,
                        "phase": "completed" if outcome.ok else "failed",
                        "ok": outcome.ok,
                    }
                )
                if outcome.ok and isinstance(outcome.data, str) and outcome.data.strip():
                    speeches.append(outcome.data.strip())

                # Level-3 denial → pause for resume
                if not outcome.ok and "confirmation" in (outcome.error or "").lower():
                    with self._plan_lock:
                        self._paused_plan = (plan, idx)
                    speech = self._compose_speech(
                        speeches,
                        stopped=f"Paused at step {idx + 1}: confirmation required.",
                    )
                    self._update_task_status(plan, "waiting")
                    self._set_plan_progress(
                        {
                            "plan_id": plan.plan_id,
                            "goal": plan.goal[:120],
                            "step": idx + 1,
                            "total": total,
                            "tool": step.tool_name,
                            "description": "confirmation required",
                            "phase": "paused",
                            "ok": False,
                        }
                    )
                    self.bus.publish(
                        "plan.paused",
                        {"plan_id": plan.plan_id, "step": idx, "reason": "confirmation"},
                        source="execution_engine",
                    )
                    return PlanRunResult(
                        ok=False,
                        plan_id=plan.plan_id,
                        completed=idx,
                        total=total,
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
                    self._update_task_status(plan, "failed")
                    self._set_plan_progress(
                        {
                            "plan_id": plan.plan_id,
                            "goal": plan.goal[:120],
                            "step": idx + 1,
                            "total": total,
                            "tool": step.tool_name,
                            "description": (outcome.error or "failed")[:160],
                            "phase": "failed",
                            "ok": False,
                        }
                    )
                    self.bus.publish(
                        "plan.failed",
                        {"plan_id": plan.plan_id, "step": idx, "error": outcome.error},
                        source="execution_engine",
                    )
                    return PlanRunResult(
                        ok=False,
                        plan_id=plan.plan_id,
                        completed=idx,
                        total=total,
                        speech=speech,
                        stopped_reason=outcome.error or "step_failed",
                        resume_from=idx,
                        step_results=results,
                    )

            self._update_task_status(plan, "completed")
            with self._plan_lock:
                if self._paused_plan and self._paused_plan[0].plan_id == plan.plan_id:
                    self._paused_plan = None
            speech = self._compose_speech(speeches, stopped="Plan complete.")
            self._set_plan_progress(
                {
                    "plan_id": plan.plan_id,
                    "goal": plan.goal[:120],
                    "step": total,
                    "total": total,
                    "tool": "",
                    "description": "complete",
                    "phase": "completed",
                    "ok": True,
                }
            )
            self.bus.publish(
                "plan.completed",
                {"plan_id": plan.plan_id, "steps": total},
                source="execution_engine",
            )
            return PlanRunResult(
                ok=True,
                plan_id=plan.plan_id,
                completed=total,
                total=total,
                speech=speech,
                step_results=results,
            )
        finally:
            set_active_token(None)

    def _set_plan_progress(self, payload: dict[str, Any]) -> None:
        import time

        entry = dict(payload)
        entry.setdefault("ts", time.time())
        self.last_plan_progress = entry
        # Timeline: keep step history for HUD PLAN pane (U-02)
        phase = str(entry.get("phase") or "")
        if phase in (
            "started",
            "running",
            "completed",
            "failed",
            "paused",
            "cancelled",
        ):
            self.plan_timeline.append(entry)
            if len(self.plan_timeline) > 48:
                self.plan_timeline = self.plan_timeline[-48:]
        self.bus.publish("plan.progress", entry, source="execution_engine")

    def resume_paused_plan(self) -> Optional[PlanRunResult]:
        with self._plan_lock:
            paused = self._paused_plan
        if not paused:
            return None
        plan, idx = paused
        self._cancel_token.reset()
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

        if requires_confirmation(
            effective,
            self.autonomy,
            auto_approve_dangerous=self.auto_approve_dangerous,
        ):
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

        # Tool-level validate() hook (optional; None = ok)
        if callable(getattr(tool, "validate", None)):
            try:
                custom = tool.validate(request.arguments)
                if custom:
                    result = ToolResult(ok=False, error=str(custom))
                    self._audit_failure(request, result.error or "", level=effective)
                    return result
            except Exception as err:
                result = ToolResult(ok=False, error=f"validate error: {err}")
                self._audit_failure(request, result.error or "", level=effective)
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
        clock = EvidenceClock()
        try:
            result = tool.run(request.arguments)
        except Exception as err:
            logger.exception("Tool %s crashed", tool.name)
            result = ToolResult(ok=False, error=str(err))

        if not isinstance(result, ToolResult):
            result = ToolResult(ok=False, error="tool returned invalid result type")

        evidence = ExecutionEvidence(
            tool=tool.name,
            input=dict(request.arguments),
            output=result.data if result.ok else None,
            status="ok" if result.ok else "error",
            duration_ms=round(clock.ms(), 2),
            error=result.error,
            request_id=get_request_id(),
        )
        if result.evidence is None:
            result.evidence = evidence.to_dict()
        else:
            # Preserve tool-supplied keys; fill gaps
            merged = evidence.to_dict()
            merged.update(result.evidence)
            result.evidence = merged
        self.last_evidence.append(evidence)
        if len(self.last_evidence) > 40:
            self.last_evidence = self.last_evidence[-40:]

        self.audit.write(
            action=f"tool.{tool.name}",
            level=int(effective),
            success=result.ok,
            details={
                "args": request.arguments,
                "error": result.error,
                "requested_by": request.requested_by,
                "evidence": result.evidence,
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
