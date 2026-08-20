"""Auto-select JARVIS operating mode from user intent.

Modes drive DeepBrain prompting — not a separate LLM call.
"""

from __future__ import annotations

import re
from enum import Enum


class AgentMode(str, Enum):
    CHAT = "chat"          # discuss, brainstorm, remember, advise
    ACT = "act"            # open apps, files, media, shell
    RESEARCH = "research"  # web / compare / investigate
    CODE = "code"          # repo, bugs, tests, patches
    PLAN = "plan"          # multi-step goals, organize week, strategy


_RESEARCH = re.compile(
    r"\b(araştır|arastir|research|investigate|karşılaştır|karsilastir|"
    r"nedir|ne demek|how does|what is|best way|en iyi)\b",
    re.I,
)
_CODE = re.compile(
    r"(kod|bug[ıi]?|hata|test|repo|github|commit|\bpr\b|pull request|"
    r"refactor|debug|function|class|deploy|build)",
    re.I,
)
_PLAN = re.compile(
    r"\b(plan|organize|organize et|strateji|haftalık|haftalik|"
    r"roadmap|adım adım|adim adim|break down|görevleri düzenle)\b",
    re.I,
)
_ACT = re.compile(
    r"\b(aç|ac|kapat|başlat|baslat|çalıştır|calistir|oynat|play|"
    r"open|close|launch|run|move|sil|delete|yaz|type|click|"
    r"screenshot|ekran|volume|ses|spotify|chrome|youtube)\b",
    re.I,
)
_CHAT = re.compile(
    r"\b(ne düşün|ne dusun|fikir|brainstorm|konuş|konus|anlat|"
    r"hatırla|hatirla|neden|why|opinion|tavsiye|öner|oner)\b",
    re.I,
)


def select_mode(command: str) -> AgentMode:
    text = (command or "").strip()
    if not text:
        return AgentMode.CHAT
    # Priority: code > research > plan > act > chat
    if _CODE.search(text):
        return AgentMode.CODE
    if _RESEARCH.search(text):
        return AgentMode.RESEARCH
    if _PLAN.search(text):
        return AgentMode.PLAN
    if _ACT.search(text) and not _CHAT.search(text):
        return AgentMode.ACT
    if _CHAT.search(text):
        return AgentMode.CHAT
    # Short follow-ups → continue conversationally
    if len(text.split()) <= 4:
        return AgentMode.CHAT
    return AgentMode.CHAT


MODE_HINTS = {
    AgentMode.CHAT: (
        "[MODE: CHAT — Second Brain] "
        "Think with the user. Reason briefly, share a clear opinion or next step. "
        "Ask at most ONE clarifying question if critical ambiguity blocks progress; "
        "otherwise decide and continue. Use memory/context. Do not restart topics."
    ),
    AgentMode.ACT: (
        "[MODE: ACT] Execute with Mac tools now. Confirm crisply after success. "
        "If a follow-up like 'that one' / 'onu' — use recent conversation."
    ),
    AgentMode.RESEARCH: (
        "[MODE: RESEARCH] Search/read sources with tools, then synthesize a clear answer. "
        "Cite briefly. If unsure, research — never invent."
    ),
    AgentMode.CODE: (
        "[MODE: CODE] Analyze/fix with project tools. Plan briefly, then act. "
        "Verify with tests when relevant. Report what changed."
    ),
    AgentMode.PLAN: (
        "[MODE: PLAN] Break the goal into ordered steps, dependencies, and first action. "
        "Then start step 1 unless the user only asked for a plan."
    ),
}


def mode_hint(mode: AgentMode) -> str:
    return MODE_HINTS.get(mode, MODE_HINTS[AgentMode.CHAT])
