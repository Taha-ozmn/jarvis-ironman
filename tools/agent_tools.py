"""Thin research / coding agent tools — wrap allowlisted plans, no fake caps."""

from __future__ import annotations

from typing import Any, Callable, Optional

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult

RunAgentFn = Callable[..., str]


class ResearchAgentTool(BaseTool):
    name = "agent.research"
    description = "Research agent: allowlisted research.topic (+ optional memory) — background OK"
    permission_level = PermissionLevel.LOCAL
    input_schema = {
        "query": {"type": "str", "required": True},
        "background": {"type": "bool", "required": False},
    }

    def __init__(self, runner: RunAgentFn) -> None:
        self._runner = runner

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="query required")
        background = bool(arguments.get("background", True))
        try:
            speech = self._runner(query, background=background)
        except Exception as err:
            return ToolResult(ok=False, error=str(err))
        return ToolResult(ok=True, data=speech or "Research started.")


class CodingAnalyzeAgentTool(BaseTool):
    name = "agent.coding_analyze"
    description = "Coding agent: analyze_repo + git.status (allowlisted) — prefers background"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"background": {"type": "bool", "required": False}}

    def __init__(self, runner: RunAgentFn) -> None:
        self._runner = runner

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        background = bool(arguments.get("background", True))
        try:
            speech = self._runner(background=background)
        except Exception as err:
            return ToolResult(ok=False, error=str(err))
        return ToolResult(ok=True, data=speech or "Analysis started.")
