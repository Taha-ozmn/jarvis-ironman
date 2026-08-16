"""Tool registry — register, discover, validate stubs."""

from __future__ import annotations

from typing import Any, Optional

from security.permissions import PermissionLevel
from tools.base import BaseTool, StubTool, ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if not tool.name:
            raise ValueError("Tool name is required")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._tools.keys())

    def list_specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]

    def discover(self, *, max_level: Optional[PermissionLevel] = None) -> list[ToolSpec]:
        specs = self.list_specs()
        if max_level is None:
            return specs
        return [s for s in specs if s.permission_level <= max_level]

    def validate_input(self, name: str, arguments: dict[str, Any]) -> Optional[str]:
        """Lightweight schema check. Returns error message or None if OK."""
        tool = self.get(name)
        if tool is None:
            return f"Unknown tool: {name}"
        schema = tool.input_schema or {}
        if not schema:
            return None
        args = arguments or {}
        for field, rules in schema.items():
            required = bool(rules.get("required", False))
            expected = rules.get("type", "any")
            if field not in args:
                if required:
                    return f"Missing required field: {field}"
                continue
            value = args[field]
            if expected == "str" and not isinstance(value, str):
                return f"Field '{field}' must be str"
            if expected == "int" and not isinstance(value, int):
                return f"Field '{field}' must be int"
            if expected == "bool" and not isinstance(value, bool):
                return f"Field '{field}' must be bool"
            if expected == "float" and not isinstance(value, (int, float)):
                return f"Field '{field}' must be float"
        return None


def register_builtin_stubs(registry: ToolRegistry) -> None:
    """Lightweight stubs for unit tests / discovery only.

    Production registers real tools via ``register_phase3_tools``.
    """
    stubs = [
        StubTool(
            "memory.search",
            "Search long-term memories (keyword) — stub for tests",
            PermissionLevel.READ,
            {"query": {"type": "str", "required": True}},
        ),
        StubTool(
            "system.shell",
            "Run a shell command — stub for tests",
            PermissionLevel.SYSTEM,
            {"command": {"type": "str", "required": True}},
        ),
        StubTool(
            "browser.navigate",
            "Open URL (test stub; production uses browser.open_url)",
            PermissionLevel.SYSTEM,
            {"url": {"type": "str", "required": True}},
        ),
        StubTool(
            "automation.run",
            "Run automation rule (test stub; production AutomationRunTool)",
            PermissionLevel.SYSTEM,
            {"rule_id": {"type": "int", "required": True}},
        ),
        StubTool(
            "diagnostics.health",
            "Report JARVIS 2.0 subsystem health — stub for tests",
            PermissionLevel.READ,
        ),
    ]
    for tool in stubs:
        registry.register(tool)
