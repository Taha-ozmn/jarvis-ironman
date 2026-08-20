"""Thin JarvisState facade over ContextManager + confirmation/tasks/projects.

Formalizes session fields without replacing existing subsystems.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class JarvisStateSnapshot:
    user_name: str
    language: str
    status: str
    active_project_id: Optional[int]
    active_project_key: str
    active_task_id: Optional[int]
    pending_confirmations: int
    memory_capture: bool
    last_command: str
    last_response: str
    request_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_name": self.user_name,
            "language": self.language,
            "status": self.status,
            "active_project_id": self.active_project_id,
            "active_project_key": self.active_project_key,
            "active_task_id": self.active_task_id,
            "pending_confirmations": self.pending_confirmations,
            "memory_capture": self.memory_capture,
            "last_command": self.last_command,
            "last_response": self.last_response,
            "request_id": self.request_id,
        }


class JarvisState:
    """Read/write session state used by FastBrain tools and HUD."""

    def __init__(
        self,
        context: Any,
        *,
        confirmation: Any = None,
        tasks: Any = None,
        projects: Any = None,
    ) -> None:
        self.context = context
        self.confirmation = confirmation
        self.tasks = tasks
        self.projects = projects

    @property
    def active_project_id(self) -> Optional[int]:
        return getattr(self.context.current, "active_project_id", None)

    @property
    def active_project_key(self) -> str:
        return str(self.context.get_extra("active_project_key") or "")

    @property
    def active_task_id(self) -> Optional[int]:
        raw = self.context.get_extra("active_task_id")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def set_active_task_id(self, task_id: Optional[int]) -> None:
        self.context.set_extra("active_task_id", task_id)

    @property
    def pending_confirmations(self) -> int:
        gate = self.confirmation
        if gate is None:
            return 0
        try:
            if hasattr(gate, "pending_count"):
                return int(gate.pending_count())
            pending = getattr(gate, "pending", None) or getattr(gate, "_pending", None)
            if pending is None:
                return 1 if gate.has_pending() else 0
            return len(pending)
        except Exception:
            try:
                return 1 if gate.has_pending() else 0
            except Exception:
                return 0

    @property
    def memory_capture(self) -> bool:
        """When False, ingest/episodic writes are skipped for this session."""
        val = self.context.get_extra("memory_capture", True)
        return bool(val) if val is not None else True

    def set_memory_capture(self, enabled: bool) -> None:
        self.context.set_extra("memory_capture", bool(enabled))

    def snapshot(self, *, request_id: str = "") -> JarvisStateSnapshot:
        ctx = self.context.current
        return JarvisStateSnapshot(
            user_name=str(getattr(ctx, "user_name", "") or ""),
            language=str(getattr(ctx, "language", "tr-TR") or "tr-TR"),
            status=str(getattr(ctx, "status", "idle") or "idle"),
            active_project_id=self.active_project_id,
            active_project_key=self.active_project_key,
            active_task_id=self.active_task_id,
            pending_confirmations=self.pending_confirmations,
            memory_capture=self.memory_capture,
            last_command=str(getattr(ctx, "last_command", "") or ""),
            last_response=str(getattr(ctx, "last_response", "") or "")[:120],
            request_id=request_id or "",
        )
