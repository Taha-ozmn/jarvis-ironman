"""Tool base types for the JARVIS registry."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional, Callable
from pathlib import Path

from security.permissions import PermissionLevel

WorkingDirFn = Callable[[], Path]


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: Optional[str] = None


@dataclass
class ToolSpec:
    name: str
    description: str
    permission_level: PermissionLevel
    input_schema: dict[str, Any] = field(default_factory=dict)
    # input_schema: { "field": {"type": "str|int|bool|float", "required": bool} }


class BaseTool(abc.ABC):
    """Typed tool contract with validation and rollback support."""

    name: str
    description: str
    permission_level: PermissionLevel = PermissionLevel.READ
    input_schema: dict[str, Any] = field(default_factory=dict)

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            permission_level=self.permission_level,
            input_schema=dict(self.input_schema),
        )

    @abc.abstractmethod
    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def validate(self, arguments: dict[str, Any]) -> Optional[str]:
        """Validate tool arguments before execution. Returns error message or None if valid.
        Override this method for custom validation logic beyond schema checking."""
        return None

    def prepare_rollback(self, arguments: dict[str, Any]) -> Any:
        """Prepare data needed for potential rollback. Returns rollback data or None if not supported.
        Override this method for tools that support rollback."""
        return None

    def rollback(self, arguments: dict[str, Any], rollback_data: Any) -> bool:
        """Execute rollback using prepared data. Returns True if successful, False otherwise.
        Override this method for tools that support rollback."""
        return False

    def dry_run(self, arguments: dict[str, Any]) -> ToolResult:
        """ Dry-run mode: simulate tool execution without side effects.
        Default implementation adds `dry_run=True` to arguments and calls `run`.
        Subclasses should override this method to provide a true simulation
        (e.g., return expected output without modifying state).
        If the tool's `run` method does not accept a `dry_run` argument,
        this default will return an error indicating the tool does not support dry-run.
        """
        args = dict(arguments)
        args["dry_run"] = True
        try:
            return self.run(args)
        except Exception as e:
            return ToolResult(
                ok=False,
                error=f"Tool '{self.name}' does not support dry-run. Consider implementing a dry_run method or accepting a 'dry_run' boolean argument.",
                data=None,
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