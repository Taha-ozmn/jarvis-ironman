"""Context-aware timeout and progress speech — no robotic repeats."""

from __future__ import annotations

import hashlib
import re
from typing import Optional

OPEN_WORDS = ("aç", "ac", "open", "launch", "start", "başlat", "baslat")
BUILD_WORDS = (
    "build", "create", "oluştur", "olustur", "yaz", "write", "make",
    "proje", "project", "app", "website", "mobil", "mobile",
)
CODE_WORDS = (
    "kod", "code", "fix", "debug", "bug", "refactor", "implement",
    "function", "class", "script",
)
RESEARCH_WORDS = ("research", "araştır", "arastir", "search", "find", "bul")
MEDIA_WORDS = ("play", "music", "video", "youtube", "spotify", "çal", "cal")
CHAT_WORDS = ("hello", "hi", "merhaba", "nasılsın", "nasilsin", "how are")


def classify_intent(command: str) -> str:
    lower = (command or "").lower().strip()
    if not lower:
        return "unknown"
    if any(w in lower for w in OPEN_WORDS):
        return "open_app"
    if any(w in lower for w in BUILD_WORDS):
        return "build"
    if any(w in lower for w in CODE_WORDS):
        return "code"
    if any(w in lower for w in RESEARCH_WORDS):
        return "research"
    if any(w in lower for w in MEDIA_WORDS):
        return "media"
    if any(w in lower for w in CHAT_WORDS) or "?" in lower:
        return "chat"
    if len(lower.split()) <= 4:
        return "chat"
    return "general"


def _pick(options: tuple[str, ...], key: str) -> str:
    if not options:
        return ""
    if not key:
        return options[0]
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(options)
    return options[idx]


def _short_topic(command: str, *, max_len: int = 36) -> str:
    text = re.sub(r"\s+", " ", (command or "").strip())
    if not text:
        return "that"
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rsplit(" ", 1)[0] + "…"


class TimeoutResponses:
    """Generate varied, intent-aware spoken lines for waits and failures."""

    def __init__(
        self,
        *,
        user_name: str = "Taha",
        use_name: bool = True,
    ) -> None:
        self.user_name = (user_name or "Taha").strip() or "Taha"
        self.use_name = use_name

    def _name_bit(self) -> str:
        if not self.use_name or not self.user_name:
            return ""
        return f", {self.user_name}"

    def soft(self, command: str = "", *, level: str = "simple") -> str:
        intent = classify_intent(command)
        topic = _short_topic(command)
        name = self._name_bit()

        pools: dict[str, tuple[str, ...]] = {
            "open_app": (
                f"Opening {topic} — one moment{name}.",
                f"Still launching that for you{name}.",
                f"Almost there with {topic}{name}.",
            ),
            "build": (
                f"This is a proper build — still assembling it{name}.",
                f"Scaffolding takes a moment{name}; I'm on it.",
                f"Still constructing {topic}{name}.",
            ),
            "code": (
                f"Working through the code on {topic}{name}.",
                f"Still tracing that logic{name}.",
                f"Nearly done with the code side{name}.",
            ),
            "research": (
                f"Still gathering information on {topic}{name}.",
                f"Cross-checking sources{name} — won't be long.",
                f"Digging into {topic}{name}.",
            ),
            "media": (
                f"Still lining up {topic}{name}.",
                f"Fetching that media{name}.",
                f"Almost ready to play{name}.",
            ),
            "chat": (
                f"Still thinking that through{name}.",
                f"One moment while I consider that{name}.",
                f"Working out a sensible answer{name}.",
            ),
            "general": (
                f"Still on {topic}{name} — neural link is active.",
                f"Processing {topic}{name}{name}; bear with me.",
                f"Working through your request{name}.",
            ),
            "unknown": (
                f"Still working on that{name}.",
                f"One moment{name}.",
                f"Processing now{name}.",
            ),
        }

        if level in ("complex", "deep"):
            pools["general"] = (
                f"This is substantial — still building {topic}{name}.",
                f"Large directive in progress{name}; I shan't rush it.",
                f"Still executing {topic}{name} — systems engaged.",
            )

        pool = pools.get(intent, pools["general"])
        return _pick(pool, command or "soft")

    def fail(
        self,
        command: str = "",
        *,
        level: str = "simple",
        ask_retry: bool = False,
    ) -> str:
        intent = classify_intent(command)
        topic = _short_topic(command)
        name = self._name_bit()

        if intent == "open_app":
            base = (
                f"I couldn't confirm {topic} opened in time{name}. "
                "I stopped this attempt safely; check whether it's already running."
            )
        elif intent == "build":
            base = (
                f"The build for {topic} exceeded my wait window{name}. "
                "I stopped this attempt safely and saved its progress."
            )
        elif intent == "code":
            base = (
                f"The code work on {topic} timed out{name}. "
                "I stopped this attempt safely and saved its progress."
            )
        elif intent == "research":
            base = (
                f"I couldn't finish researching {topic} in time{name}. "
                "I stopped this attempt safely and saved its progress."
            )
        elif intent == "chat":
            base = (
                f"My answer on that took too long{name}. "
                "I stopped this attempt safely rather than repeating it."
            )
        elif level in ("complex", "deep"):
            base = (
                f"{topic} needs more time than I had{name}. "
                "I stopped this attempt safely and saved its progress."
            )
        else:
            base = (
                f"I ran out of time on {topic}{name}. "
                "I stopped this attempt safely rather than repeating it."
            )

        # Timeout must never turn into a conversational retry loop. The
        # argument is retained for backwards compatibility with callers.
        del ask_retry
        return base

    def background(self, command: str = "", *, level: str = "complex") -> str:
        topic = _short_topic(command)
        name = self._name_bit()
        if level == "deep":
            return (
                f"Full-scope work on {topic} — I'll finish in the background{name} "
                "and speak when it's done."
            )
        return (
            f"This is a sizeable task on {topic}{name}; "
            "I'll keep at it and report back when finished."
        )

    def active_run_retry(self) -> str:
        name = self._name_bit()
        return f"Previous task still clearing{name} — retrying now."

    def fault(self, command: str = "") -> str:
        intent = classify_intent(command)
        name = self._name_bit()
        if intent == "open_app":
            return f"Something faulted while opening that{name}. I'll try a different route."
        return (
            f"I hit a fault completing that{name}. "
            "The attempt has stopped safely; no success was claimed."
        )

    def progress(self, command: str, index: int) -> str:
        intent = classify_intent(command)
        topic = _short_topic(command)
        name = self._name_bit()
        lines = {
            "open_app": (
                f"Still opening {topic}{name}.",
                f"Almost there with {topic}.",
                f"Retrying the launch{name}.",
            ),
            "build": (
                f"Still building {topic}{name}.",
                f"Next layer of {topic} going in.",
                f"Compile and verify still running{name}.",
            ),
            "code": (
                f"Still editing {topic}{name}.",
                f"Running checks on {topic}.",
                f"Refining the code{name}.",
            ),
            "research": (
                f"Still researching {topic}{name}.",
                f"Pulling more sources on {topic}.",
                f"Synthesising what I found{name}.",
            ),
        }
        pool = lines.get(intent, (
            f"Still on {topic}{name}.",
            f"Working the next step{name}.",
            f"Processing {topic} — hang on.",
        ))
        return pool[index % len(pool)]

    def connection_error(self, detail: str = "") -> str:
        hint = (detail or "link interrupted").strip()[:80]
        return (
            f"Neural link hiccup ({hint}). "
            "The task is paused safely; no action was claimed."
        )
