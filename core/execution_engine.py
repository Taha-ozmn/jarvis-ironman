"""Execution engine — routes tool calls through permission + registry."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from core.event_bus import EventBus
from core.evidence import Evidence, make_evidence
from core.planner import Plan, PlanStep
from core.verification import should_verify, verify_tool_result
from security.audit import AuditLog
from security.confirmation import ConfirmationGate
from security.permissions import PermissionLevel, PermissionGate
from tools.base import BaseTool, ToolResult

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
        max_plan_steps: int = 12,
        plan_timeout_sec: float = 300.0,
        working_dir: Optional[Callable[[], Path]] = None,
        tasks: Any = None,
        dry_run: bool = False,
        workspace_only: bool = False,
    ) -> None:
        self.registry = registry
        self.permissions = permissions
        self.audit = audit
        self.bus = bus
        self.confirmation = confirmation or ConfirmationGate()
        self.on_level_notify = on_level_notify
        self.max_retries = max(0, int(max_retries))
        self.max_plan_steps = max(1, int(max_plan_steps))
        self.plan_timeout_sec = max(0.05, float(plan_timeout_sec))
        self.working_dir = working_dir
        self.tasks = tasks
        self.dry_run = dry_run
        self.workspace_only = bool(workspace_only)
        self._plan_lock = threading.Lock()
        self._paused_plan: Optional[tuple[Plan, int]] = None
        self._on_checkpoint: Optional[Callable[[Plan, int, str], None]] = None
        self.last_evidence: Optional[Evidence] = None
        self.plan_evidence: list[Evidence] = []

    def set_checkpoint_handler(
        self,
        handler: Optional[Callable[[Plan, int, str], None]],
    ) -> None:
        self._on_checkpoint = handler

    def _persist_checkpoint(self, plan: Plan, resume_from: int, reason: str) -> None:
        if self._on_checkpoint is None or resume_from is None:
            return
        try:
            self._on_checkpoint(plan, int(resume_from), reason or "")
        except Exception:
            logger.exception("checkpoint handler failed")

    def execute(self, request: ExecutionRequest) -> ToolResult:
        started = time.monotonic()
        result = self._execute_once(request)
        self.last_evidence = make_evidence(
            request.tool_name,
            result,
            started_at=started,
        )
        if not result.ok:
            return result
        if not should_verify(request.tool_name, step_verify=False):
            return result
        outcome = verify_tool_result(
            request.tool_name,
            request.arguments,
            result,
            working_dir=self.working_dir,
        )
        self.audit.write(
            action=f"verify.{request.tool_name}",
            level=0,
            success=outcome.ok,
            details={"message": outcome.message, "alternate": outcome.alternate},
        )
        if outcome.ok:
            self.last_evidence = make_evidence(
                request.tool_name,
                result,
                started_at=started,
                verified=True,
                verification_message=outcome.message,
            )
            return result
        self.last_evidence = make_evidence(
            request.tool_name,
            ToolResult(ok=False, error=outcome.message),
            started_at=started,
            verified=False,
            verification_message=outcome.message,
        )
        return ToolResult(
            ok=False,
            error=f"Verification failed: {outcome.message}. {outcome.alternate}",
        )

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
        self.plan_evidence = []
        start = max(0, int(start_at))
        # Agent loop guards: max steps (iterations) + wall-clock timeout
        steps = plan.steps
        if len(steps) > self.max_plan_steps:
            logger.warning(
                "plan %s truncated %s → %s steps (max_plan_steps)",
                plan.plan_id,
                len(steps),
                self.max_plan_steps,
            )
            plan.steps = list(steps[: self.max_plan_steps])
            steps = plan.steps
        deadline = time.monotonic() + self.plan_timeout_sec

        for idx in range(start, len(plan.steps)):
            if time.monotonic() > deadline:
                speech = self._compose_speech(
                    speeches,
                    stopped=(
                        f"Stopped at step {idx + 1}: plan timeout "
                        f"({int(self.plan_timeout_sec)}s)."
                    ),
                )
                self._update_task_status(plan, "cancelled")
                self.bus.publish(
                    "plan.timeout",
                    {
                        "plan_id": plan.plan_id,
                        "step": idx,
                        "timeout_sec": self.plan_timeout_sec,
                    },
                    source="execution_engine",
                )
                self.audit.write(
                    action="plan.timeout",
                    level=0,
                    success=False,
                    details={
                        "plan_id": plan.plan_id,
                        "step": idx,
                        "timeout_sec": self.plan_timeout_sec,
                    },
                )
                self._persist_checkpoint(plan, idx, "plan_timeout")
                return PlanRunResult(
                    ok=False,
                    plan_id=plan.plan_id,
                    completed=idx,
                    total=len(plan.steps),
                    speech=speech,
                    stopped_reason="plan_timeout",
                    resume_from=idx,
                    step_results=results,
                )

            step = plan.steps[idx]
            outcome = self._run_step_with_retries(step, requested_by=requested_by)
            evidence = self.plan_evidence[-1] if self.plan_evidence else None
            results.append(
                {
                    "index": idx,
                    "tool": step.tool_name,
                    "ok": outcome.ok,
                    "data": outcome.data if isinstance(outcome.data, str) else None,
                    "error": outcome.error,
                    "evidence": evidence.as_dict() if evidence else None,
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
                self._persist_checkpoint(plan, idx, "confirmation_required")
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
                self._persist_checkpoint(plan, idx, outcome.error or "step_failed")
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
        self._persist_checkpoint(plan, len(plan.steps), "__completed__")
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
        """Execute a plan step with retry mechanism and exponential backoff."""
        import time

        started = time.monotonic()
        max_attempts = self.max_retries + 1
        base_delay = 0.5  # Start with 500ms delay

        last_result = ToolResult(ok=False, error="no attempt")

        for attempt in range(max_attempts):
            # Execute the step
            last_result = self._execute_once(
                ExecutionRequest(step.tool_name, dict(step.arguments), requested_by=requested_by)
            )

            # If successful, break out of retry loop
            if last_result.ok:
                break

            # Check if we should retry based on error type
            if not self._is_retryable_error(last_result.error):
                # Non-retryable errors (like confirmation/permission) should not be retried
                break

            # If this was our last attempt, don't sleep
            if attempt < max_attempts - 1:
                # Calculate delay with exponential backoff
                delay = base_delay * (2 ** attempt)  # Exponential backoff
                # Add jitter to prevent thundering herd
                import random
                delay += random.uniform(0, delay * 0.1)  # Up to 10% jitter

                # Log the retry attempt
                self.audit.write(
                    action=f"plan.retry.{step.tool_name}",
                    level=0,
                    success=False,
                    details={
                        "attempt": attempt + 1,
                        "max_attempts": max_attempts,
                        "delay_ms": round(delay * 1000),
                        "error": last_result.error,
                    },
                )

                # Wait before retrying
                time.sleep(delay)
            else:
                # Final attempt failed
                self.audit.write(
                    action=f"plan.final_attempt_failed.{step.tool_name}",
                    level=0,
                    success=False,
                    details={
                        "attempt": attempt + 1,
                        "max_attempts": max_attempts,
                        "error": last_result.error,
                    },
                )

        # After all attempts, run verification if needed and if we had success
        if last_result.ok and should_verify(step.tool_name, step_verify=step.verify):
            outcome = verify_tool_result(
                step.tool_name,
                step.arguments,
                last_result,
                working_dir=self.working_dir,
            )
            self.audit.write(
                action=f"plan.verify.{step.tool_name}",
                level=0,
                success=outcome.ok,
                details={"message": outcome.message, "alternate": outcome.alternate},
            )
            if not outcome.ok:
                # Verification failed, treat as overall failure.
                last_result = ToolResult(
                    ok=False,
                    error=f"Verification failed: {outcome.message}. {outcome.alternate}",
                )

        self.plan_evidence.append(
            make_evidence(
                step.tool_name,
                last_result,
                started_at=started,
                verified=bool(last_result.ok),
                verification_message="plan step completed" if last_result.ok else (
                    last_result.error or ""
                ),
            )
        )
        return last_result

    def _is_retryable_error(self, error_message: Optional[str]) -> bool:
        """Determine if an error is retryable based on its message."""
        if not error_message:
            return True  # Empty error might be transient

        error_lower = error_message.lower()

        # Non-retryable errors
        non_retryable_patterns = [
            "confirmation required",
            "permission denied",
            "user confirmation required",
            "unknown tool",
            "validation error",
            "blocked:",  # Security blocks
            "catastrophic command",
        ]

        for pattern in non_retryable_patterns:
            if pattern in error_lower:
                return False

        # Retryable errors (timeouts, network issues, etc.)
        retryable_patterns = [
            "timeout",
            "timed out",
            "network",
            "connection",
            "temporary",
            "try again",
            "retry",
            "failed to connect",
            "connection refused",
        ]

        # If it matches retryable patterns, it's retryable
        for pattern in retryable_patterns:
            if pattern in error_lower:
                return True

        # Default: if it's not explicitly non-retryable, assume retryable for safety
        # (but this could be adjusted based on experience)
        return True

    def _execute_once(self, request: ExecutionRequest) -> ToolResult:
        tool = self.registry.get(request.tool_name)
        if tool is None:
            result = ToolResult(ok=False, error=f"Unknown tool: {request.tool_name}")
            self._audit_failure(request, result.error or "")
            return result

        if self.workspace_only and request.tool_name.startswith("fs."):
            workspace = self.working_dir() if self.working_dir else Path.cwd()
            for key in ("path", "src", "dst"):
                raw = str(request.arguments.get(key) or "").strip()
                if not raw:
                    continue
                candidate = Path(raw).expanduser()
                if not candidate.is_absolute():
                    candidate = workspace / candidate
                try:
                    candidate.resolve().relative_to(workspace.resolve())
                except ValueError:
                    msg = f"Permission denied outside active workspace: {key}"
                    result = ToolResult(ok=False, error=msg)
                    self._audit_failure(request, msg)
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
            # Hard-block catastrophic shell before any auto-approve path
            if request.tool_name == "system.shell":
                from security.risk import is_blocked_shell

                cmd = str(request.arguments.get("command") or "")
                if is_blocked_shell(cmd):
                    msg = "Blocked: catastrophic command refused (never auto-approved)."
                    result = ToolResult(ok=False, error=msg)
                    self._audit_failure(request, msg, level=effective)
                    return result
            if self.confirmation.auto_approve:
                self.audit.write(
                    action=f"autonomy.auto_approve.{request.tool_name}",
                    level=int(effective),
                    success=True,
                    details={
                        "args": request.arguments,
                        "requested_by": request.requested_by,
                        "note": "full_autonomy or auto_approve_dangerous",
                    },
                )
            elif not self.confirmation.require(
                request.tool_name,
                details=str(request.arguments),
                level=int(effective),
            ):
                result = ToolResult(ok=False, error="User confirmation required")
                self._audit_failure(request, result.error or "", level=effective)
                return result

        # Dry-run mode: simulate tool execution without side effects
        if self.dry_run:
            if hasattr(tool, "dry_run"):
                result = tool.dry_run(request.arguments)
            else:
                # Fallback to BaseTool's dry_run implementation
                result = tool.dry_run(request.arguments)
            self.audit.write(
                action=f"tool.{tool.name}.dry_run",
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

        # Enhanced validation pipeline: schema validation + tool-specific validation
        validation_error = self.registry.validate_input(tool.name, request.arguments)
        if validation_error:
            result = ToolResult(ok=False, error=validation_error)
            self._audit_failure(request, validation_error, level=effective)
            return result

        # Tool-specific validation hook
        if isinstance(tool, BaseTool):
            tool_validation_error = tool.validate(request.arguments)
            if tool_validation_error:
                result = ToolResult(ok=False, error=tool_validation_error)
                self._audit_failure(request, tool_validation_error, level=effective)
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

            # If tool execution was successful, audit success
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
        except Exception as err:
            logger.exception("Tool %s crashed", tool.name)
            error_result = ToolResult(ok=False, error=str(err))

            # Attempt rollback for tools that support it
            rollback_attempted = False
            rollback_success = False
            if isinstance(tool, BaseTool):
                try:
                    rollback_data = tool.prepare_rollback(request.arguments)
                    if rollback_data is not None:
                        rollback_attempted = True
                        rollback_success = tool.rollback(request.arguments, rollback_data)

                        # Audit rollback attempt
                        self.audit.write(
                            action=f"tool.{tool.name}.rollback",
                            level=int(effective),
                            success=rollback_success,
                            details={
                                "args": request.arguments,
                                "original_error": str(err),
                                "rollback_attempted": rollback_attempted,
                                "rollback_success": rollback_success,
                                "requested_by": request.requested_by,
                            },
                        )
                except Exception as rollback_err:
                    logger.exception("Rollback failed for tool %s", tool.name)
                    # Audit rollback failure
                    self.audit.write(
                        action=f"tool.{tool.name}.rollback",
                        level=int(effective),
                        success=False,
                        details={
                            "args": request.arguments,
                            "original_error": str(err),
                            "rollback_error": str(rollback_err),
                            "rollback_attempted": True,
                            "rollback_success": False,
                            "requested_by": request.requested_by,
                        },
                    )

            # Audit the original tool execution failure
            self.audit.write(
                action=f"tool.{tool.name}",
                level=int(effective),
                success=False,
                details={
                    "args": request.arguments,
                    "error": str(err),
                    "rollback_attempted": rollback_attempted,
                    "rollback_success": rollback_success,
                    "requested_by": request.requested_by,
                },
            )
            self.bus.publish(
                "tool.completed",
                {"tool": tool.name, "ok": False, "error": str(err)},
                source="execution_engine",
            )
            return error_result

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