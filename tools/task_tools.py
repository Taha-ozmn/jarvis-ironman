"""Task tools wrapping TaskManager."""

from __future__ import annotations

from typing import Any

from core.task_manager import TaskManager
from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult


class TaskCreateTool(BaseTool):
    name = "task.create"
    description = "Create a tracked task"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"title": {"type": "str", "required": True}}

    def __init__(self, tasks: TaskManager) -> None:
        self._tasks = tasks

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        title = str(arguments.get("title") or "").strip()
        if not title:
            return ToolResult(ok=False, error="Title required")
        desc = str(arguments.get("description") or "")
        priority = int(arguments.get("priority") or 1)
        task = self._tasks.create(title, description=desc, priority=priority)
        return ToolResult(ok=True, data=f"Task #{task.id} created: {task.title}.")


class TaskListTool(BaseTool):
    name = "task.list"
    description = "List tasks"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, tasks: TaskManager) -> None:
        self._tasks = tasks

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        status = arguments.get("status")
        limit = int(arguments.get("limit") or 10)
        items = self._tasks.list(status=status, limit=limit)
        if not items:
            return ToolResult(ok=True, data="No tasks.")
        parts = [f"#{t.id} [{t.status}] {t.title}" for t in items]
        text = "; ".join(parts)
        if len(text) > 220:
            text = text[:220] + "…"
        return ToolResult(ok=True, data=f"Tasks: {text}")


class TaskCompleteTool(BaseTool):
    name = "task.complete"
    description = "Mark a task as done"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"task_id": {"type": "int", "required": True}}

    def __init__(self, tasks: TaskManager) -> None:
        self._tasks = tasks

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        task_id = arguments.get("task_id")
        if task_id is None:
            return ToolResult(ok=False, error="task_id required")
        try:
            task = self._tasks.update(int(task_id), status="done")
        except KeyError:
            return ToolResult(ok=False, error=f"Task not found: {task_id}")
        return ToolResult(ok=True, data=f"Task #{task.id} completed.")
