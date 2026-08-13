"""Diagnostics tool — real health check via JarvisOS."""

from __future__ import annotations

from typing import Any, Callable, Optional

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult

HealthFn = Callable[[], dict[str, Any]]


class DiagnosticsHealthTool(BaseTool):
    name = "diagnostics.health"
    description = "Report JARVIS 2.0 subsystem health"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, health_fn: HealthFn) -> None:
        self._health_fn = health_fn

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        health = self._health_fn()
        status = "nominal" if health.get("ok") else "degraded"
        checks = health.get("checks") or []
        failed = [c["name"] for c in checks if not c.get("ok")]
        highlights = []
        for name in ("projects", "backup", "planner", "browser", "mcp", "automation"):
            for c in checks:
                if c.get("name") == name:
                    highlights.append(f"{name}={c.get('detail', '')[:60]}")
                    break
        if failed:
            msg = (
                f"JARVIS 2.0 core {status}: "
                f"{health.get('passed')}/{health.get('total')} checks. "
                f"Issues: {', '.join(failed)}."
            )
        else:
            msg = (
                f"JARVIS 2.0 core {status}: "
                f"all {health.get('total')} subsystems OK."
            )
        if highlights:
            msg += " " + "; ".join(highlights[:4])
        if len(msg) > 360:
            msg = msg[:357] + "…"
        return ToolResult(ok=True, data=msg)
