"""Rule-based memory extraction from conversation turns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from memory.repository import MemoryRepository

SECRET_PATTERNS = (
    re.compile(r"password\s*[:=]", re.I),
    re.compile(r"passwd\s*[:=]", re.I),
    re.compile(r"api[_ ]?key\s*[:=]", re.I),
    re.compile(r"secret\s*[:=]", re.I),
    re.compile(r"token\s*[:=]", re.I),
    re.compile(r"cursor_api", re.I),
    re.compile(r"bearer\s+\S+", re.I),
    re.compile(r"sk-[A-Za-z0-9]{16,}", re.I),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"aws_secret_access_key\s*=", re.I),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)

# Redact in-place when extraction somehow proceeds with mixed content
REDACT_SUBS = (
    (re.compile(r"(password\s*[:=]\s*)\S+", re.I), r"\1[REDACTED]"),
    (re.compile(r"(api[_ ]?key\s*[:=]\s*)\S+", re.I), r"\1[REDACTED]"),
    (re.compile(r"(secret\s*[:=]\s*)\S+", re.I), r"\1[REDACTED]"),
    (re.compile(r"(token\s*[:=]\s*)\S+", re.I), r"\1[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9]{16,}", re.I), "[REDACTED_KEY]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "[REDACTED_TOKEN]"),
    (re.compile(r"bearer\s+\S+", re.I), "bearer [REDACTED]"),
)

NAME_TOKEN = r"[A-Za-zğüşıöçĞÜŞİÖÇ .'-]{2,40}"

PREFERENCE_PATTERNS = (
    re.compile(
        r"(?:i prefer|i like|my favourite|my favorite|tercihim|tercih ederim|seviyorum)\s+(.+)$",
        re.I,
    ),
    re.compile(
        rf"(?:call me|benim adım|adım)\s+({NAME_TOKEN})$",
        re.I,
    ),
)

NAME_PREFERENCE_PATTERNS = (
    re.compile(rf"bana\s+({NAME_TOKEN})\s+diye\s+hitap\s+et", re.I),
    re.compile(rf"(?:benim\s+)?(?:ismim|adım|adim)\s+({NAME_TOKEN})", re.I),
    re.compile(rf"(?:call me|address me as)\s+({NAME_TOKEN})", re.I),
)

PROJECT_PATTERNS = (
    re.compile(
        r"(?:i(?:'m| am) working on|project(?: is)?|üzerinde çalışıyorum|proje(?:m)?)\s+(.+)$",
        re.I,
    ),
)


@dataclass
class ExtractedMemory:
    content: str
    category: str
    key: Optional[str] = None
    importance: int = 2


# Short acknowledgements / noise — do not persist as long-term memory.
TRIVIAL_UTTERANCES = frozenset(
    {
        "tamam",
        "ok",
        "okay",
        "anladım",
        "anladim",
        "evet",
        "hayır",
        "hayir",
        "yok",
        "var",
        "teşekkürler",
        "tesekkurler",
        "sağol",
        "sagol",
        "thanks",
        "thank you",
        "hmm",
        "hm",
        "aaa",
        "şey",
        "sey",
        "devam",
        "dur",
        "iptal",
        "cancel",
        "stop",
    }
)

TRIVIAL_PREFIXES = (
    "jarvis ",
    "hey jarvis ",
    "ok jarvis ",
)


def looks_like_secret(text: str) -> bool:
    return any(p.search(text or "") for p in SECRET_PATTERNS)


def is_trivial_utterance(text: str) -> bool:
    """True for short acks / noise that must not enter long-term memory."""
    raw = (text or "").strip().lower()
    if not raw:
        return True
    for prefix in TRIVIAL_PREFIXES:
        if raw.startswith(prefix):
            raw = raw[len(prefix) :].strip()
    raw = re.sub(r"[!.?…]+$", "", raw).strip()
    if not raw:
        return True
    if raw in TRIVIAL_UTTERANCES:
        return True
    # Very short non-preference chatter (≤2 tokens, no digits)
    tokens = re.findall(r"[a-zçğıöşü0-9]+", raw, flags=re.I)
    if len(tokens) <= 2 and len(raw) <= 16 and not any(c.isdigit() for c in raw):
        if not any(
            k in raw
            for k in (
                "adım",
                "adim",
                "ismim",
                "tercih",
                "hatırla",
                "hatirla",
                "unutma",
                "proje",
                "project",
                "prefer",
                "call me",
            )
        ):
            return True
    return False


def score_importance(item: ExtractedMemory) -> int:
    """Map extracted memory to 1–5 importance (profile/prefs highest)."""
    if item.importance and item.importance != 2:
        return max(1, min(5, int(item.importance)))
    cat = (item.category or "general").lower()
    key = (item.key or "").lower()
    if cat == "preference" or key.startswith("user_") or key.startswith("preference"):
        return 4
    if cat in ("project_context", "project") or key.startswith("project:"):
        return 3
    if cat == "profile":
        return 5
    content = (item.content or "").lower()
    if any(w in content for w in ("hatırla", "hatirla", "remember", "unutma")):
        return 3
    return 2


def redact_secrets(text: str) -> str:
    out = text or ""
    for pat, repl in REDACT_SUBS:
        out = pat.sub(repl, out)
    return out


def parse_name_preference(text: str) -> Optional[tuple[str, str]]:
    """Fast-path name / address preference — no LLM required."""
    raw = (text or "").strip()
    if not raw or looks_like_secret(raw):
        return None

    for pat in NAME_PREFERENCE_PATTERNS:
        match = pat.search(raw)
        if not match:
            continue
        name = match.group(1).strip(" .'\"")
        if not name or len(name) < 2:
            continue
        content = redact_secrets(f"Address user as {name}")
        return name, content
    return None


def is_name_preference_command(text: str) -> bool:
    return parse_name_preference(text) is not None


def extract_memories(user_text: str, assistant_text: str = "") -> list[ExtractedMemory]:
    """Lightweight rule-based extraction. Optional LLM hook can wrap this later."""
    _ = assistant_text
    text = (user_text or "").strip()
    if not text or looks_like_secret(text):
        return []
    # Name / preference commands are never trivial even if short.
    if is_trivial_utterance(text) and not is_name_preference_command(text):
        return []

    found: list[ExtractedMemory] = []

    name_pref = parse_name_preference(text)
    if name_pref:
        name, content = name_pref
        found.append(
            ExtractedMemory(
                content=content[:240],
                category="preference",
                key="user_name",
                importance=4,
            )
        )
        # Also store display name for recall snippets
        found.append(
            ExtractedMemory(
                content=f"User name is {name}"[:240],
                category="preference",
                key=f"preference:name:{name.lower()}",
                importance=4,
            )
        )

    for pat in PREFERENCE_PATTERNS:
        m = pat.search(text)
        if m:
            content = redact_secrets(m.group(0).strip())
            if not looks_like_secret(content):
                found.append(
                    ExtractedMemory(
                        content=content[:240],
                        category="preference",
                        key="preference:" + content[:40].lower(),
                        importance=4,
                    )
                )
            break

    for pat in PROJECT_PATTERNS:
        m = pat.search(text)
        if m:
            content = redact_secrets(m.group(0).strip())
            if not looks_like_secret(content):
                found.append(
                    ExtractedMemory(
                        content=content[:240],
                        category="project_context",
                        key="project:" + m.group(1).strip()[:40].lower(),
                        importance=3,
                    )
                )
            break

    # Explicit remember already handled by tools; also catch "note that I ..."
    m = re.search(r"(?:note that|unutma(?: ki)?)\s+(.+)$", text, re.I)
    if m and not looks_like_secret(m.group(1)):
        found.append(
            ExtractedMemory(
                content=redact_secrets(m.group(1).strip())[:240],
                category="general",
                importance=3,
            )
        )

    return found


def extract_and_save(
    repo: MemoryRepository,
    user_text: str,
    assistant_text: str = "",
) -> list[int]:
    """Extract and persist memories; returns saved ids. Skips trivial turns."""
    if is_trivial_utterance(user_text) and not is_name_preference_command(user_text):
        return []
    ids: list[int] = []
    for item in extract_memories(user_text, assistant_text):
        try:
            importance = score_importance(item)
            if item.key:
                mem = repo.upsert_by_key(
                    item.key,
                    item.content,
                    category=item.category,
                    importance=importance,
                )
            else:
                mem = repo.create(
                    item.content,
                    category=item.category,
                    importance=importance,
                )
            ids.append(mem.id)
        except Exception:
            continue
    return ids
