"""Tool base types for the JARVIS registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from security.permissions import PermissionLevel


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: Optional[str] = None
    evidence: Optional[dict[str, Any]] = None


@dataclass
class ToolSpec:
    name: str
    description: str
    permission_level: PermissionLevel
    input_schema: dict[str, Any] = field(default_factory=dict)
    # input_schema: { "field": {"type": "str|int|bool|float", "required": bool} }


class BaseTool(ABC):
    """Typed tool contract — validate / run / optional rollback."""

    name: str
    description: str
    permission_level: PermissionLevel = PermissionLevel.READ
    input_schema: dict[str, Any] = {}

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            permission_level=self.permission_level,
            input_schema=dict(self.input_schema),
        )

    def validate(self, arguments: dict[str, Any]) -> Optional[str]:
        """Return error message or None if OK. Override for custom checks."""
        del arguments
        return None

    @abstractmethod
    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def rollback(self, arguments: dict[str, Any], previous: Any = None) -> ToolResult:
        """Best-effort undo. Default: honest failure (not silently ignored)."""
        del arguments, previous
        return ToolResult(
            ok=False,
            error=f"rollback not supported for '{self.name}'",
        )


class StubTool(BaseTool):
    """Placeholder tool — registered for discovery, not fully implemented."""

    def __init__(
        self,
        name: str,
        description: str,
        permission_level: PermissionLevel = PermissionLevel.READ,
        input_schema: Optional[dict[str, Any]] = None,
    ) -> None:
        self.name = name
        self.description = description
        self.permission_level = permission_level
        self.input_schema = input_schema or {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=False,
            error=f"Tool '{self.name}' is a stub — not implemented yet (Phase 3+)",
            data={"received": arguments},
        )
