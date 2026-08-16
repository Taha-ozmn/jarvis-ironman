"""Task complexity classification — latency / Cursor gate (Phase 2).

CHAT / SIMPLE never spawn Cursor.
MEDIUM+ may fall through to DeepBrain.
"""

from __future__ import annotations

import re
from enum import Enum

from brain.task_router import COMPLEX_WORDS, DEEP_WORDS
from core.open_target import looks_like_action


class TaskComplexity(str, Enum):
    CHAT = "chat"
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    AUTONOMOUS = "autonomous"


# Pure social / meta — never worth a Cursor round-trip
_CHAT_EXACT = frozenset(
    {
        "merhaba",
        "hello",
        "hi",
        "hey",
        "selam",
        "thanks",
        "thank you",
        "teşekkür",
        "tesekkur",
        "teşekkürler",
        "tesekkurler",
        "sağol",
        "sagol",
        "günaydın",
        "gunaydin",
        "iyi akşamlar",
        "iyi aksamlar",
        "good morning",
        "good evening",
        "good night",
        "bye",
        "görüşürüz",
        "gorusuruz",
        "ok",
        "okay",
        "tamam",
        "yes",
        "yep",
        "no",
        "nope",
        "evet",
        "hayır",
        "hayir",
        "hmm",
        "hm",
        "ne",
        "anladım",
        "anladim",
        "peki",
    }
)

_CHAT_PHRASES = (
    "dinliyor musun",
    "are you listening",
    "duyuyor musun",
    "nasılsın",
    "nasilsin",
    "how are you",
    "who are you",
    "kimsin",
    "adın ne",
    "adin ne",
)

_SIMPLE_PHRASES = (
    "saat kaç",
    "saat kac",
    "what time",
    "what date",
    "tarih",
    "bugünün tarihi",
    "system status",
    "sistem durumu",
    "jarvis status",
    "diagnostics",
    "volume up",
    "volume down",
    "sesi aç",
    "sesi ac",
    "sesi kıs",
    "sesi kis",
    "mute",
    "unmute",
    "sessiz",
    "list tasks",
    "görevler",
    "gorevler",
    "show tasks",
    "list files",
    "dosyaları listele",
    "dosyalari listele",
    "stop",
    "dur",
    "be quiet",
    "weather",
    "hava durumu",
)

# Short local tool intents — keep off Cursor even if ≤3 words
_SIMPLE_EXACT = frozenset(
    {
        "stop",
        "dur",
        "mute",
        "unmute",
        "status",
        "diagnostics",
        "tasks",
        "görevler",
        "gorevler",
        "weather",
    }
)

_AUTONOMOUS_HINTS = (
    "plan and",
    "planla",
    "adım adım",
    "adim adim",
    "and then",
    "ve sonra",
    "fix and",
    "analiz et ve",
    "organize",
    "otonom",
    "autonomous",
    "hepsini hallet",
    "tamamını yap",
)

_MEDIUM_HINTS = (
    "araştır",
    "arastir",
    "research",
    "nedir",
    "ne demek",
    "why ",
    "neden",
    "explain",
    "anlat",
    "fikir",
    "opinion",
    "compare",
    "karşılaştır",
    "karsilastir",
    "hatırla",
    "hatirla",
    "remember",
)


def classify_task_complexity(text: str) -> TaskComplexity:
    """Classify utterance for Cursor gate + latency budget."""
    raw = (text or "").strip()
    lower = raw.lower().strip()
    if not lower:
        return TaskComplexity.CHAT

    # Strip wake prefix for classification
    for prefix in ("hey jarvis ", "ok jarvis ", "jarvis "):
        if lower.startswith(prefix):
            lower = lower[len(prefix) :].strip()
            raw = raw[len(prefix) :].strip() if raw.lower().startswith(prefix) else raw

    if lower in _CHAT_EXACT or any(p in lower for p in _CHAT_PHRASES):
        return TaskComplexity.CHAT

    if lower in _SIMPLE_EXACT or any(p in lower for p in _SIMPLE_PHRASES):
        return TaskComplexity.SIMPLE

    if any(h in lower for h in _AUTONOMOUS_HINTS):
        return TaskComplexity.AUTONOMOUS

    # Research / explain before open-action heuristic
    if any(h in lower for h in _MEDIUM_HINTS):
        return TaskComplexity.MEDIUM

    # Local open/close/volume before broad "app"/"project" substring traps
    if looks_like_action(lower) and len(lower.split()) <= 8:
        if not re.search(
            r"\b(bug|fix|debug|refactor|commit|test|github|kod|deploy|docker)\b",
            lower,
        ):
            return TaskComplexity.SIMPLE

    if _has_any_word(lower, DEEP_WORDS) or _has_any_word(lower, COMPLEX_WORDS):
        return TaskComplexity.COMPLEX

    # Code / bug without full project language
    if re.search(
        r"\b(bug|hata|fix|debug|refactor|commit|test|github|kod|code)\b",
        lower,
    ):
        return TaskComplexity.COMPLEX

    if looks_like_action(lower):
        return TaskComplexity.MEDIUM

    # Short follow-ups / vague → medium (may need context + Cursor)
    if len(lower.split()) <= 3:
        return TaskComplexity.MEDIUM

    # Default conversational second-brain
    return TaskComplexity.MEDIUM


def _has_any_word(text: str, words: tuple[str, ...]) -> bool:
    """Substring match for multi-word phrases; word-boundary for short tokens."""
    for w in words:
        if " " in w or len(w) >= 5:
            if w in text:
                return True
        else:
            if re.search(rf"\b{re.escape(w)}\b", text):
                return True
    return False


def allows_cursor(complexity: TaskComplexity) -> bool:
    """CHAT and SIMPLE never spawn Cursor (Phase 2 gate)."""
    return complexity not in (TaskComplexity.CHAT, TaskComplexity.SIMPLE)


def local_fallback_speech(complexity: TaskComplexity, command: str = "") -> str:
    """Speech when local path misses and Cursor is gated off."""
    if complexity is TaskComplexity.CHAT:
        return "Hello. How can I help?"
    if complexity is TaskComplexity.SIMPLE:
        if looks_like_action(command):
            return (
                "I couldn't run that locally. "
                "Try a clearer app or command — for example «open Chrome» or «saat kaç»."
            )
        return (
            "That's a simple request I handle locally. "
            "Rephrase it briefly, or say «Jarvis status» for diagnostics."
        )
    return "I need a bit more detail to continue."
