"""Session control tools — stop / pause / resume / retry / continue / project health."""

from __future__ import annotations

from typing import Any, Callable

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult

SessionFn = Callable[[dict[str, Any]], ToolResult]


class _CallbackTool(BaseTool):
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, fn: SessionFn) -> None:
        self._fn = fn

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            return self._fn(arguments or {})
        except Exception as err:
            return ToolResult(ok=False, error=str(err))


class SessionRetryTool(_CallbackTool):
    name = "session.retry"
    description = "Retry the last failed tool request"


class SessionContinueTool(_CallbackTool):
    name = "session.continue"
    description = "Resume work from recent / yesterday tasks and memory"


class SessionStopTool(_CallbackTool):
    name = "session.stop"
    description = "Cancel the in-flight plan or long task"


class SessionPauseTool(_CallbackTool):
    name = "session.pause"
    description = "Pause the in-flight plan (resumable)"


class SessionResumeTool(_CallbackTool):
    name = "session.resume"
    description = "Resume a paused plan"


class SessionEditFileTool(_CallbackTool):
    name = "session.edit_file"
    description = "Edit the current/context file (asks if unknown)"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"path": {"type": "str", "required": False}}


class ProjectHealthTool(_CallbackTool):
    name = "project.health"
    description = "Parallel git + repo structure health check"
    permission_level = PermissionLevel.READ


def register_session_tools(registry: Any, hooks: dict[str, SessionFn]) -> None:
    mapping = {
        "retry": SessionRetryTool,
        "continue": SessionContinueTool,
        "stop": SessionStopTool,
        "pause": SessionPauseTool,
        "resume": SessionResumeTool,
        "edit_file": SessionEditFileTool,
        "project_health": ProjectHealthTool,
    }
    for key, cls in mapping.items():
        fn = hooks.get(key)
        if fn is not None:
            registry.register(cls(fn))
