"""Diagnostics tools — host status (fast) + JARVIS subsystem health."""

from __future__ import annotations

from typing import Any, Callable, Optional

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult

HealthFn = Callable[[], dict[str, Any]]
HostStatusFn = Callable[[], str]


class SystemHealthTool(BaseTool):
    """Fast local host status — CPU / RAM / swap only (English TTS)."""

    name = "system.health"
    description = "Short Mac host status: CPU, RAM, swap (no LLM)"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, status_fn: Optional[HostStatusFn] = None) -> None:
        self._status_fn = status_fn

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        if self._status_fn is not None:
            msg = self._status_fn()
        else:
            from system.host_metrics import format_host_status_en, get_host_metrics

            metrics = get_host_metrics(force=True)
            msg = format_host_status_en(metrics)
        return ToolResult(ok=True, data=msg)


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
        pw = ""
        for c in checks:
            if c.get("name") == "browser":
                detail = str(c.get("detail") or "")
                meta = c.get("meta") if isinstance(c.get("meta"), dict) else {}
                note = str((meta or {}).get("note") or "")
                if "playwright=False" in detail or "playwright=false" in detail:
                    pw = (
                        " Playwright yok: pip install -r requirements-optional.txt "
                        "&& playwright install chromium "
                        "(macOS 12: Playwright <1.62 / 1.61.0)."
                    )
                elif "chromium=False" in detail or meta.get("chromium") is False:
                    pw = (
                        " Chromium yok/uyumsuz: macOS 12'de Playwright <1.62 pin + "
                        "playwright install chromium; open URL yolu çalışır."
                    )
                elif "mac12" in note.lower() or "monterey" in note.lower():
                    pw = " Monterey: Playwright 1.62+ chromium desteklemez; <1.62 kullanın."
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
        msg += pw
        if len(msg) > 360:
            msg = msg[:357] + "…"
        return ToolResult(ok=True, data=msg)
