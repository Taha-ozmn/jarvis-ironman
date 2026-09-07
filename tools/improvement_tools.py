"""Tools for the safe self-improvement queue."""

from __future__ import annotations

from typing import Any

from core.self_improvement import SelfImprovementEngine
from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult


class ImprovementStatusTool(BaseTool):
    name = "self.improvement_status"
    description = "Show pending safe self-improvement proposals"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, engine: SelfImprovementEngine) -> None:
        self._engine = engine

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        return ToolResult(ok=True, data=self._engine.status_speech())


class ImprovementProposeTool(BaseTool):
    name = "self.propose_improvement"
    description = "Create a bounded improvement proposal for review"
    permission_level = PermissionLevel.LOCAL
    input_schema = {
        "title": {"type": "str", "required": True},
        "reason": {"type": "str", "required": True},
        "scope": {"type": "str", "required": False},
    }

    def __init__(self, engine: SelfImprovementEngine) -> None:
        self._engine = engine

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            proposal = self._engine.propose(
                str(arguments.get("title") or ""),
                str(arguments.get("reason") or ""),
                scope=str(arguments.get("scope") or "bug_fix"),
            )
        except (TypeError, ValueError) as err:
            return ToolResult(ok=False, error=str(err))
        return ToolResult(
            ok=True,
            data=f"Proposal {proposal.proposal_id} created: {proposal.title}. "
            "It requires isolated testing and Taha's approval.",
        )
