"""Goal → ordered plan of tool steps (Phase 7–8)."""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

COMPLEX_HINTS = (
    "plan and",
    "plan to",
    "make a plan",
    "adım adım",
    "planla",
    "ve sonra",
    "and then",
    " then ",
    "organize",
    "düzenle",
    "organize et",
    "analyze and",
    "analyse and",
    "fix and",
    "incele ve",
    "analiz et ve",
    "multi-step",
    "çok adımlı",
    "backup and",
    "yedekle ve",
    "fix cycle",
    "düzelt ve test",
)

# Allowed tools the LLM may emit (whitelist — never invent shell wipe etc.)
ALLOWED_PLAN_TOOLS = frozenset(
    {
        "project.list",
        "project.set_active",
        "project.get",
        "git.status",
        "git.diff",
        "git.branch",
        "git.log",
        "git.add",
        "git.commit",
        "dev.analyze_repo",
        "dev.run_tests",
        "dev.run_command",
        "dev.fix_cycle",
        "dev.apply_patch",
        "fs.list",
        "fs.read",
        "fs.write",
        "fs.create",
        "fs.move",
        "task.list",
        "task.create",
        "memory.search",
        "memory.save",
        "research.topic",
        "system.backup",
        "proactive.briefing",
        "diagnostics.health",
        "browser.open_url",
        "browser.get_page_text",
        "media.play",
        "screen.describe",
        "screen.capture",
    }
)

LLMRefineFn = Callable[[str, "Plan"], Optional["Plan"]]


@dataclass
class PlanStep:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    verify: bool = False


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep]
    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    complex: bool = True
    task_id: Optional[int] = None
    source: str = "heuristic"  # heuristic | llm

    def summary(self, *, max_chars: int = 280) -> str:
        if not self.steps:
            return f"No steps for «{self.goal}»."
        lines = [f"Plan ({len(self.steps)} steps, {self.source}):"]
        for i, step in enumerate(self.steps, 1):
            desc = step.description or step.tool_name
            lines.append(f"{i}. {desc}")
        text = " ".join(lines) if len(" ".join(lines)) < max_chars else "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        return text


class Planner:
    """Heuristic planner with optional LLM refine (offline-safe fallback)."""

    def __init__(
        self,
        llm_refine: Optional[LLMRefineFn] = None,
        *,
        max_steps: int = 12,
    ) -> None:
        self._llm_refine = llm_refine
        self.max_steps = max(1, int(max_steps))

    def set_llm_refine(self, fn: Optional[LLMRefineFn]) -> None:
        self._llm_refine = fn

    def needs_plan(self, goal: str) -> bool:
        lower = (goal or "").strip().lower()
        if not lower:
            return False
        if any(h in lower for h in COMPLEX_HINTS):
            return True
        if lower.count(" and ") >= 2 or lower.count(" ve ") >= 2:
            return True
        return False

    def create(self, goal: str) -> Plan:
        text = (goal or "").strip()
        lower = text.lower()
        if not text:
            return Plan(goal="", steps=[], complex=False, source="heuristic")

        if not self.needs_plan(text):
            return Plan(goal=text, steps=[], complex=False, source="heuristic")

        steps = self._template_steps(lower, text)
        if not steps:
            steps = [
                PlanStep(
                    "research.topic",
                    {"query": self._strip_plan_prefix(text)},
                    description="Research the topic",
                )
            ]
        steps = steps[: self.max_steps]
        plan = Plan(goal=text, steps=steps, complex=True, source="heuristic")

        if self._llm_refine is not None:
            try:
                refined = self._llm_refine(text, plan)
                if refined is not None and refined.steps:
                    refined.steps = refined.steps[: self.max_steps]
                    refined.source = "llm"
                    refined.complex = True
                    refined.goal = text
                    plan = refined
            except Exception:
                logger.exception("LLM plan refine failed — using heuristic")

        # Agent allowlists — drop tools outside profile (no fake capabilities)
        try:
            from core.agent_profiles import (
                filter_plan_steps,
                looks_like_coding_analyze,
                looks_like_research_agent,
            )

            if looks_like_research_agent(text) or text.lower().startswith("research"):
                plan = filter_plan_steps(plan, "research")
            elif looks_like_coding_analyze(text) or any(
                k in text.lower() for k in ("fix cycle", "analyze repo", "dev.", "git ")
            ):
                # Only force coding filter for explicit coding agent goals
                if looks_like_coding_analyze(text) or "fix cycle" in text.lower():
                    plan = filter_plan_steps(plan, "coding")
        except Exception:
            logger.exception("agent allowlist filter skipped")
        return plan

    def _template_steps(self, lower: str, text: str) -> list[PlanStep]:
        steps: list[PlanStep] = []

        if any(k in lower for k in ("backup", "yedek", "yedekle")):
            steps.append(
                PlanStep(
                    "system.backup",
                    {},
                    description="Backup database and config",
                    verify=True,
                )
            )

        # Developer fix cycle
        if any(
            k in lower
            for k in (
                "fix cycle",
                "analyze and fix",
                "analyse and fix",
                "incele ve düzelt",
                "incele ve duzelt",
                "düzelt ve test",
            )
        ):
            steps.append(
                PlanStep("dev.fix_cycle", {}, description="Analyze → locate → test", verify=True)
            )
            return self._dedupe(steps)

        if any(
            k in lower
            for k in ("analyze", "analyse", "incele", "repo", "repository", "fix", "test")
        ):
            if any(k in lower for k in ("analyze", "analyse", "incele", "repo", "repository")):
                steps.append(
                    PlanStep("dev.analyze_repo", {}, description="Analyze repository structure")
                )
            if any(k in lower for k in ("test", "fix", "düzelt")):
                steps.append(
                    PlanStep("dev.run_tests", {}, description="Run project tests", verify=True)
                )
            if "git" in lower or "commit" in lower or "status" in lower:
                steps.append(PlanStep("git.status", {}, description="Check git status"))

        if any(k in lower for k in ("organize", "düzenle", "organize et")):
            if not any(s.tool_name == "project.list" for s in steps):
                steps.append(PlanStep("project.list", {}, description="List projects"))
            steps.append(PlanStep("task.list", {}, description="List open tasks"))
            steps.append(PlanStep("proactive.briefing", {}, description="Generate briefing"))

        if any(k in lower for k in ("research", "araştır", "arastir")) and not any(
            s.tool_name == "research.topic" for s in steps
        ):
            q = self._strip_plan_prefix(text)
            q = re.sub(r"^(?:research|araştır|arastir)\s+", "", q, flags=re.I).strip() or q
            steps.append(
                PlanStep(
                    "research.topic",
                    {"query": q, "save_memory": True},
                    description=f"Research «{q[:40]}»",
                )
            )

        # Music / media multi-step: search URL → open (verify)
        from core.open_target import extract_music_intent

        music = extract_music_intent(text)
        if music is not None and not any(s.tool_name == "media.play" for s in steps):
            steps.append(
                PlanStep(
                    "media.play",
                    {"query": music.query, "service": music.service},
                    description=f"Play/search «{music.query[:40]}» on {music.service}",
                    verify=True,
                )
            )

        return self._dedupe(steps)

    @staticmethod
    def _dedupe(steps: list[PlanStep]) -> list[PlanStep]:
        seen: set[str] = set()
        unique: list[PlanStep] = []
        for step in steps:
            sig = f"{step.tool_name}:{sorted(step.arguments.items())}"
            if sig in seen:
                continue
            seen.add(sig)
            unique.append(step)
        return unique

    @staticmethod
    def _strip_plan_prefix(text: str) -> str:
        cleaned = re.sub(
            r"^(?:plan and (?:do|execute)|plan to|make a plan to|adım adım|planla)\s+",
            "",
            text.strip(),
            flags=re.I,
        )
        return cleaned.strip() or text.strip()


def parse_llm_plan_json(raw: str, *, goal: str) -> Optional[Plan]:
    """Parse LLM JSON plan; whitelist tools; return None on garbage."""
    text = (raw or "").strip()
    if not text:
        return None
    # Extract JSON array/object from fences
    m = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    items = data.get("steps") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        return None
    steps: list[PlanStep] = []
    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool") or item.get("tool_name") or "").strip()
        if name not in ALLOWED_PLAN_TOOLS:
            continue
        args = item.get("arguments") or item.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        steps.append(
            PlanStep(
                tool_name=name,
                arguments=args,
                description=str(item.get("description") or name)[:120],
                verify=bool(item.get("verify", False)),
            )
        )
    if not steps:
        return None
    return Plan(goal=goal, steps=steps, complex=True, source="llm")


def make_llm_refine(provider: Any) -> LLMRefineFn:
    """Build refine callback from LLMProvider-like object."""

    def _refine(goal: str, heuristic: Plan) -> Optional[Plan]:
        if provider is None or not getattr(provider, "available", lambda: False)():
            return None
        allowed = ", ".join(sorted(ALLOWED_PLAN_TOOLS))
        hint = [
            {"tool": s.tool_name, "arguments": s.arguments, "description": s.description}
            for s in heuristic.steps
        ]
        prompt = (
            "You are JARVIS planner. Return ONLY JSON: "
            '{"steps":[{"tool":"...","arguments":{},"description":"...","verify":false}]}. '
            f"Allowed tools: {allowed}. "
            f"Goal: {goal}\nHeuristic hint: {json.dumps(hint, ensure_ascii=False)}\n"
            "Max 8 steps. No prose."
        )
        raw = provider.complete(prompt, category="system", timeout=18.0)
        return parse_llm_plan_json(raw, goal=goal)

    return _refine
