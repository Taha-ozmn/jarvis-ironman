"""Research vs Coding agent tool allowlists — thin policy over existing tools.

No fake capabilities: only tools that are registered and implemented.
"""

from __future__ import annotations

from typing import Iterable, Optional

from core.planner import Plan, PlanStep

# Deep / planner research path — web + memory + screen (read-mostly)
RESEARCH_TOOLS = frozenset(
    {
        "research.topic",
        "browser.open_url",
        "browser.search",
        "browser.get_page_text",
        "browser.list_tabs",
        "memory.search",
        "memory.save",
        "screen.describe",
        "screen.capture",
        "weather.current",
        "calendar.list_today",
        "github.list_issues",
        "github.list_pulls",
        "proactive.briefing",
        "diagnostics.health",
    }
)

# Coding / repo path — local project tools only
CODING_TOOLS = frozenset(
    {
        "project.list",
        "project.get",
        "project.set_active",
        "dev.analyze_repo",
        "dev.run_tests",
        "dev.run_command",
        "dev.fix_cycle",
        "dev.apply_patch",
        "git.status",
        "git.diff",
        "git.branch",
        "git.log",
        "git.add",
        "git.commit",
        "fs.list",
        "fs.read",
        "fs.write",
        "fs.create",
        "fs.move",
        "task.list",
        "task.create",
        "memory.search",
        "memory.save",
        "system.backup",
        "diagnostics.health",
    }
)

AGENT_PROFILES = {
    "research": RESEARCH_TOOLS,
    "coding": CODING_TOOLS,
}


def allowlist_for(profile: str) -> frozenset[str]:
    key = (profile or "").strip().lower()
    return AGENT_PROFILES.get(key, frozenset())


def filter_plan_steps(plan: Plan, profile: str) -> Plan:
    """Drop steps whose tools are outside the agent allowlist (honest)."""
    allowed = allowlist_for(profile)
    if not allowed or not plan.steps:
        return plan
    kept = [s for s in plan.steps if s.tool_name in allowed]
    plan.steps = kept
    return plan


def research_plan(query: str, *, max_steps: int = 4) -> Plan:
    """Minimal research agent plan — real research.topic only (no fake browse)."""
    q = (query or "").strip() or "general topic"
    steps = [
        PlanStep(
            "research.topic",
            {"query": q},
            description=f"Research: {q[:60]}",
        ),
    ]
    return Plan(
        goal=f"research:{q}",
        steps=steps[: max(1, max_steps)],
        complex=True,
        source="research_agent",
    )


def coding_analyze_plan(*, max_steps: int = 4) -> Plan:
    """Analyze active project — real tools only."""
    steps = [
        PlanStep("dev.analyze_repo", {}, description="Analyze repository structure"),
        PlanStep("git.status", {}, description="Check git status"),
    ]
    return Plan(
        goal="coding:analyze_repo",
        steps=steps[: max(1, max_steps)],
        complex=True,
        source="coding_agent",
    )


def coding_fix_plan(*, max_steps: int = 4) -> Plan:
    steps = [
        PlanStep(
            "dev.fix_cycle",
            {},
            description="Analyze → locate → test",
            verify=True,
        ),
    ]
    return Plan(
        goal="coding:fix_cycle",
        steps=steps[: max(1, max_steps)],
        complex=True,
        source="coding_agent",
    )


def looks_like_coding_analyze(text: str) -> bool:
    lower = (text or "").lower()
    triggers = (
        "projeyi analiz",
        "projeyi incele",
        "kodu analiz",
        "kodu incele",
        "analyze the project",
        "analyse the project",
        "analyze project",
        "analyse project",
        "repo analizi",
        "repository analiz",
        "analyze repo",
        "analyse repo",
        "repoyu incele",
        "repoyu analiz",
    )
    return any(t in lower for t in triggers)


def looks_like_research_agent(text: str) -> bool:
    lower = (text or "").lower()
    # Explicit research agent phrasing (router may already catch "araştır X")
    return any(
        t in lower
        for t in (
            "araştırıp özetle",
            "arastirip ozetle",
            "research and summarize",
            "derin araştırma",
            "derin arastirma",
        )
    )


def extract_research_query(text: str) -> str:
    raw = (text or "").strip()
    lower = raw.lower()
    for prefix in (
        "araştırıp özetle",
        "arastirip ozetle",
        "research and summarize",
        "derin araştırma",
        "derin arastirma",
        "araştır",
        "arastir",
        "research",
    ):
        if lower.startswith(prefix):
            return raw[len(prefix) :].strip(" :,-")
        idx = lower.find(prefix)
        if idx >= 0:
            return raw[idx + len(prefix) :].strip(" :,-")
    return raw
