"""Parallel project health probes (Phase 13 + «projeyi analiz et»)."""

from __future__ import annotations

from typing import Any, Callable

from core.parallel import run_parallel
from tools.base import ToolResult


def probe_project_health(
    working_dir: Callable[[], Any],
    *,
    include_tests: bool = False,
) -> ToolResult:
    """Run independent git + structure (+ optional tests) probes in parallel."""
    from tools.dev_tools import AnalyzeRepoTool, RunTestsTool
    from tools.git_tools import GitStatusTool

    jobs: list[tuple[str, Callable[[], ToolResult]]] = [
        ("git", lambda: GitStatusTool(working_dir).run({})),
        ("analyze", lambda: AnalyzeRepoTool(working_dir).run({})),
    ]
    if include_tests:
        jobs.append(("tests", lambda: RunTestsTool(working_dir).run({})))

    completed = run_parallel(jobs, max_workers=len(jobs))
    parts: list[str] = []
    evidence: dict[str, Any] = {}
    for name, _fn in jobs:
        value = completed.get(name)
        if isinstance(value, ToolResult):
            evidence[name] = {"ok": value.ok, "data": str(value.data or value.error or "")[:200]}
            if value.ok:
                parts.append(f"{name}: {str(value.data or 'ok')[:120]}")
            else:
                parts.append(f"{name}: {value.error or 'failed'}")
        elif isinstance(value, BaseException):
            parts.append(f"{name}: {value}")
        else:
            parts.append(f"{name}: missing")
    speech = "Project check — " + " | ".join(parts)
    if len(speech) > 400:
        speech = speech[:397] + "…"
    analyze = completed.get("analyze")
    analyze_ok = isinstance(analyze, ToolResult) and analyze.ok
    return ToolResult(ok=analyze_ok, data=speech, evidence=evidence)
