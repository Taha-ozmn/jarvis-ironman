"""Project tools — list / get / set active."""

from __future__ import annotations

from typing import Any

from projects.registry import ProjectRegistry
from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult


class ProjectListTool(BaseTool):
    name = "project.list"
    description = "List registered projects and availability on disk"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, registry: ProjectRegistry) -> None:
        self._registry = registry

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        projects = self._registry.list_projects()
        if not projects:
            return ToolResult(ok=True, data="No projects registered.")
        active = self._registry.active()
        parts = []
        for p in projects:
            mark = "*" if active and active.key == p.key else "-"
            status = "ok" if p.exists else "missing"
            parts.append(f"{mark} {p.key} [{status}] {p.name}")
        text = "; ".join(parts)
        if len(text) > 240:
            text = text[:240] + "…"
        return ToolResult(ok=True, data=f"Projects: {text}")


class ProjectGetTool(BaseTool):
    name = "project.get"
    description = "Get details for a project by key/alias"
    permission_level = PermissionLevel.READ
    input_schema = {"name": {"type": "str", "required": True}}

    def __init__(self, registry: ProjectRegistry) -> None:
        self._registry = registry

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments.get("name") or "").strip()
        proj = self._registry.get(name)
        if proj is None:
            return ToolResult(ok=False, error=f"Unknown project: {name}")
        status = "available" if proj.exists else "path missing"
        return ToolResult(
            ok=True,
            data=f"{proj.name} ({proj.key}) — {status} at {proj.path}",
        )


class ProjectSetActiveTool(BaseTool):
    name = "project.set_active"
    description = "Set the active project / workspace context"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"name": {"type": "str", "required": True}}

    def __init__(self, registry: ProjectRegistry) -> None:
        self._registry = registry

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments.get("name") or "").strip()
        try:
            proj = self._registry.set_active(name)
        except KeyError as err:
            return ToolResult(ok=False, error=str(err))
        if not proj.exists:
            return ToolResult(
                ok=True,
                data=(
                    f"Active project set to {proj.name}, but path is missing "
                    f"({proj.path}). Clone or update config/projects.yaml."
                ),
            )
        return ToolResult(
            ok=True,
            data=f"Working on {proj.name}. Path: {proj.path}",
        )
