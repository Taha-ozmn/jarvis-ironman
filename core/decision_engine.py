"""Universal decision engine — Second Brain judgment for ALL commands.

Flow: interpret → use context → decide (clarify | rewrite | proceed) → act.

Music has a specialized picker (decision_music); everything else uses this layer
so JARVIS never blindly dumps a half-resolved tool call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from core.decision_music import decide_music_play, is_vague_music_query
from core.mode_selector import AgentMode, select_mode
from core.open_target import extract_music_intent


@dataclass
class DecisionContext:
    """Snapshot of working memory for judgment."""

    last_command: str = ""
    last_response: str = ""
    last_entity: str = ""
    last_opened_app: str = ""
    active_topic: str = ""
    recent_user_turns: list[str] = field(default_factory=list)
    screen_summary: str = ""


@dataclass
class Decision:
    """Outcome of one judgment cycle."""

    original: str
    rewritten: str
    mode: AgentMode
    needs_clarification: bool = False
    clarification: str = ""
    autonomous: bool = False
    rationale: str = ""
    speak_preamble: str = ""
    tool_overrides: dict[str, Any] = field(default_factory=dict)


_VAGUE_OPEN = re.compile(
    r"^(?:bana\s+)?(?:bir\s+)?(?:uygulama|app|application|şey|sey|program)\s*"
    r"(?:aç|ac|open|launch)\s*$|"
    r"^(?:aç|ac|open|launch)\s+(?:bir\s+|an?\s+)?(?:şey|sey|uygulama|app|application)\s*$|"
    r"^(?:open|launch)\s+(?:an?\s+)?(?:app|application)\s*$|"
    r"^(?:tarayıcı|tarayici|browser)\s*(?:aç|ac|open|launch)?\s*$",
    re.I,
)
_VAGUE_RESEARCH = re.compile(
    r"^(?:bunu|onu|şunu|sunu)?\s*(?:araştır|arastir|research|bak)\s*$|"
    r"^(?:araştır|arastir|investigate)\s*$",
    re.I,
)
_VAGUE_REMIND = re.compile(
    r"^(?:hatırlat|hatirlat|remind\s+me)\s*$|"
    r"^(?:bunu|onu)\s+(?:hatırlat|hatirlat|kaydet)\s*$",
    re.I,
)
_VAGUE_ORGANIZE = re.compile(
    r"^(?:bugün|bugun|today)?\s*(?:ne\s+yap|plan|organize|düzenle|duzenle)\s*$|"
    r"^(?:bugünkü|bugunku)\s*(?:işler|isler|görevler|gorevler)\s*$",
    re.I,
)
_FOLLOW_SHORT = re.compile(
    r"^(?:evet|hayır|hayir|ok|okay|tamam|devam|peki|peki ya|neden|"
    r"yes|no|continue|why|and\s+then|sonra|o\s+zaman)\s*[?.!]*$",
    re.I,
)


class DecisionEngine:
    """Judge every user utterance before tools / DeepBrain."""

    def decide(self, command: str, ctx: Optional[DecisionContext] = None) -> Decision:
        text = (command or "").strip()
        ctx = ctx or DecisionContext()
        mode = select_mode(text)
        if not text:
            return Decision(
                original=text,
                rewritten=text,
                mode=mode,
                needs_clarification=True,
                clarification="What would you like me to do?",
            )

        # 1) Music — specialized autonomous picker
        music = extract_music_intent(text)
        if music is not None:
            pick = decide_music_play(music.query)
            rewritten = text
            overrides: dict[str, Any] = {
                "query": pick.search_query,
                "service": music.service,
            }
            preamble = pick.rationale if pick.autonomous else ""
            return Decision(
                original=text,
                rewritten=rewritten,
                mode=AgentMode.ACT,
                autonomous=pick.autonomous,
                rationale=pick.rationale,
                speak_preamble=preamble,
                tool_overrides=overrides,
            )

        # 2) Vague open → Chrome (default daily browser) with explanation
        if _VAGUE_OPEN.match(text):
            return Decision(
                original=text,
                rewritten="open chrome",
                mode=AgentMode.ACT,
                autonomous=True,
                rationale="No app named — opening Chrome.",
                speak_preamble="No app named — opening Chrome.",
            )

        # 3) Vague research → use topic / last entity or ask once
        if _VAGUE_RESEARCH.match(text):
            topic = ctx.active_topic or ctx.last_entity or _topic_from_turns(ctx)
            if topic:
                return Decision(
                    original=text,
                    rewritten=f"{topic} hakkında araştır",
                    mode=AgentMode.RESEARCH,
                    autonomous=True,
                    rationale=f"Researching «{topic}» from our current thread.",
                    speak_preamble=f"I'll research «{topic}» from our current thread.",
                )
            return Decision(
                original=text,
                rewritten=text,
                mode=AgentMode.RESEARCH,
                needs_clarification=True,
                clarification="What should I research — a project, a tech, or a person?",
            )

        # 4) Vague remind → use last user statement as task
        if _VAGUE_REMIND.match(text):
            prior = _last_substantive_turn(ctx)
            if prior:
                return Decision(
                    original=text,
                    rewritten=f"bunu görev olarak kaydet: {prior}",
                    mode=AgentMode.PLAN,
                    autonomous=True,
                    rationale="Saving your last point as a task.",
                    speak_preamble="I'll save your last point as a task.",
                )
            return Decision(
                original=text,
                rewritten=text,
                mode=AgentMode.PLAN,
                needs_clarification=True,
                clarification="What should I remind you about?",
            )

        # 5) Organize / what should I do today
        if _VAGUE_ORGANIZE.match(text):
            return Decision(
                original=text,
                rewritten="bugünkü görevlerim ve takvim özeti",
                mode=AgentMode.PLAN,
                autonomous=True,
                rationale="Pulling today's tasks and calendar.",
                speak_preamble="I'll pull today's priorities and calendar.",
            )

        # 6) Short follow-ups — keep for DeepBrain with strong context (don't rewrite away)
        if _FOLLOW_SHORT.match(text):
            return Decision(
                original=text,
                rewritten=text,
                mode=AgentMode.CHAT,
                autonomous=False,
                rationale="Continuing the same conversation thread.",
            )

        # 7) Pronoun / incomplete open with last entity
        rewritten = _maybe_fill_entity(text, ctx)
        if rewritten != text:
            return Decision(
                original=text,
                rewritten=rewritten,
                mode=AgentMode.ACT,
                autonomous=True,
                rationale=f"Using «{ctx.last_entity or ctx.last_opened_app}» from context.",
                speak_preamble=(
                    f"Using «{ctx.last_entity or ctx.last_opened_app}» from our context."
                ),
            )

        # 8) Default — proceed with selected mode; DeepBrain reasons with full memory
        return Decision(
            original=text,
            rewritten=text,
            mode=mode,
            autonomous=False,
            rationale=f"Mode {mode.value}: proceeding with judgment from context.",
        )


def decision_context_from_session(
    *,
    last_command: str = "",
    last_response: str = "",
    last_entity: str = "",
    last_opened_app: str = "",
    active_topic: str = "",
    recent_user_turns: Optional[list[str]] = None,
    screen_summary: str = "",
) -> DecisionContext:
    return DecisionContext(
        last_command=last_command or "",
        last_response=last_response or "",
        last_entity=last_entity or "",
        last_opened_app=last_opened_app or "",
        active_topic=active_topic or "",
        recent_user_turns=list(recent_user_turns or []),
        screen_summary=screen_summary or "",
    )


def _topic_from_turns(ctx: DecisionContext) -> str:
    for turn in reversed(ctx.recent_user_turns):
        words = turn.split()
        if len(words) >= 2:
            return " ".join(words[:8])
    return ""


def _last_substantive_turn(ctx: DecisionContext) -> str:
    for turn in reversed(ctx.recent_user_turns):
        if len(turn.split()) >= 3 and not _FOLLOW_SHORT.match(turn):
            return turn[:160]
    if ctx.last_command and len(ctx.last_command.split()) >= 3:
        return ctx.last_command[:160]
    return ""


def _maybe_fill_entity(text: str, ctx: DecisionContext) -> str:
    lower = text.lower().strip()
    entity = (ctx.last_entity or ctx.last_opened_app or "").strip()
    if not entity:
        return text
    if any(
        p in lower
        for p in ("onu aç", "open it", "open that", "bunu aç", "şunu aç", "onu ac")
    ):
        return f"open {entity}"
    if lower in ("aç", "ac", "open") and entity:
        return f"open {entity}"
    return text
