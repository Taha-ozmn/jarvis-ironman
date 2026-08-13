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

PREFERENCE_PATTERNS = (
    re.compile(
        r"(?:i prefer|i like|my favourite|my favorite|tercihim|tercih ederim|seviyorum)\s+(.+)$",
        re.I,
    ),
    re.compile(
        r"(?:call me|benim adım|adım)\s+([A-Za-zğüşıöçĞÜŞİÖÇ .'-]{2,40})$",
        re.I,
    ),
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


def looks_like_secret(text: str) -> bool:
    return any(p.search(text or "") for p in SECRET_PATTERNS)


def redact_secrets(text: str) -> str:
    out = text or ""
    for pat, repl in REDACT_SUBS:
        out = pat.sub(repl, out)
    return out


def extract_memories(user_text: str, assistant_text: str = "") -> list[ExtractedMemory]:
    """Lightweight rule-based extraction. Optional LLM hook can wrap this later."""
    _ = assistant_text
    text = (user_text or "").strip()
    if not text or looks_like_secret(text):
        return []

    found: list[ExtractedMemory] = []

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
            )
        )

    return found


def extract_and_save(
    repo: MemoryRepository,
    user_text: str,
    assistant_text: str = "",
) -> list[int]:
    """Extract and persist memories; returns saved ids."""
    ids: list[int] = []
    for item in extract_memories(user_text, assistant_text):
        try:
            if item.key:
                mem = repo.upsert_by_key(
                    item.key,
                    item.content,
                    category=item.category,
                    importance=2,
                )
            else:
                mem = repo.create(item.content, category=item.category, importance=2)
            ids.append(mem.id)
        except Exception:
            continue
    return ids
