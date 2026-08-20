"""FastBrain vs DeepBrain entry — thin wrapper over CommandRouter + Cursor.

Does not replace JarvisOS or JarvisBrain. Classifies whether a command should
stay on the local tool path (Fast) or fall through to Cursor (Deep).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.command_router import CommandRouter, RouteMatch
from core.mode_selector import AgentMode, select_mode
from core.open_target import extract_music_intent


class BrainPath(str, Enum):
    FAST = "fast"
    DEEP = "deep"


# Tools that must stay on the local latency path (<1s target).
FAST_TOOL_ALLOWLIST = frozenset(
    {
        "system.health",
        "diagnostics.health",
        "system.time",
        "system.date",
        "system.open_app",
        "system.close_app",
        "browser.list_tabs",
        "browser.open_url",
        "browser.search",
        "media.play",
        "weather.current",
        "preference.apply",
        "system.volume",
        "system.check_permissions",
        "memory.about_user",
        "memory.forget",
        "memory.list",
        "memory.search",
        "memory.save",
        "agent.research",
        "agent.coding_analyze",
        "memory.session_capture",
        "calendar.list_today",
        "github.list_issues",
        "github.list_pulls",
    }
)


@dataclass(frozen=True)
class BrainDecision:
    path: BrainPath
    reason: str
    match: Optional[RouteMatch] = None
    mode: Optional[AgentMode] = None

    @property
    def is_fast(self) -> bool:
        return self.path is BrainPath.FAST

    @property
    def tool_name(self) -> Optional[str]:
        if self.match is None:
            return None
        return self.match.request.tool_name


class BrainRouter:
    """Classify Fast (local tools) vs Deep (Cursor) without executing."""

    def __init__(self, command_router: Optional[CommandRouter] = None) -> None:
        self._router = command_router or CommandRouter()

    def decide(self, command: str) -> BrainDecision:
        text = (command or "").strip()
        mode = select_mode(text)
        if not text:
            return BrainDecision(BrainPath.DEEP, "empty", mode=mode)

        match = self._router.route(text)
        if match is not None:
            tool = match.request.tool_name
            if tool in FAST_TOOL_ALLOWLIST:
                return BrainDecision(
                    BrainPath.FAST, f"allowlist:{tool}", match, mode=mode
                )
            return BrainDecision(
                BrainPath.FAST, f"tool:{tool}", match, mode=mode
            )

        if extract_music_intent(text) is not None:
            return BrainDecision(BrainPath.FAST, "music_heuristic", mode=mode)

        # Chat / research / code / plan → DeepBrain (thinking second brain)
        if mode in (
            AgentMode.CHAT,
            AgentMode.RESEARCH,
            AgentMode.CODE,
            AgentMode.PLAN,
        ):
            return BrainDecision(BrainPath.DEEP, f"mode:{mode.value}", mode=mode)

        return BrainDecision(BrainPath.DEEP, "cursor_fallback", mode=mode)

    def route_fast(self, command: str) -> Optional[RouteMatch]:
        """Return RouteMatch only when Fast path has a concrete tool request."""
        decision = self.decide(command)
        if decision.is_fast and decision.match is not None:
            return decision.match
        return None
