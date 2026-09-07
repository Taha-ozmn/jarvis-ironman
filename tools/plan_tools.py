"""Backup + plan execution tools (Phase 7)."""

from __future__ import annotations

from typing import Any, Optional

from core.backup import BackupService
from core.planner import Planner
from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult


class SystemBackupTool(BaseTool):
    name = "system.backup"
    description = "Versioned backup of SQLite DB + critical YAML into data/backups/"
    permission_level = PermissionLevel.LOCAL
    input_schema: dict = {}

    def __init__(self, backup: BackupService) -> None:
        self._backup = backup

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        result = self._backup.run()
        if not result.ok:
            return ToolResult(ok=False, error=result.message or "Backup failed")
        return ToolResult(
            ok=True,
            data=result.message,
        )


class PlanResumeTool(BaseTool):
    """Resume a paused or checkpointed multi-step plan."""

    name = "plan.resume"
    description = "Resume the last paused or failed plan from checkpoint"
    permission_level = PermissionLevel.LOCAL
    input_schema: dict = {}

    def __init__(self, runner: Any) -> None:
        self._runner = runner

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        try:
            speech = self._runner()
        except Exception as err:
            return ToolResult(ok=False, error=str(err))
        return ToolResult(ok=True, data=speech)


class PlanRunTool(BaseTool):
    """Delegates to JarvisOS / ExecutionEngine via injected runner."""

    name = "plan.run"
    description = "Create and execute a multi-step plan for a complex goal"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"goal": {"type": "str", "required": True}}

    def __init__(self, runner: Any) -> None:
        self._runner = runner

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        goal = str(arguments.get("goal") or "").strip()
        if not goal:
            return ToolResult(ok=False, error="goal required")
        background = bool(arguments.get("background", False))
        try:
            speech = self._runner(goal, background=background)
        except Exception as err:
            return ToolResult(ok=False, error=str(err))
        return ToolResult(ok=True, data=speech)
