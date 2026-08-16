"""Normalize spoken app / open targets (TR+EN) — Phase 1 Stability.

Avoid treating Turkish adjective «açık» as the verb «aç»
(which previously produced garbage targets like «ık»).
"""

from __future__ import annotations

import re
from typing import Optional

# Speech-to-text and casual aliases → canonical keys for MacOSController.APP_ALIASES
SPEECH_APP_ALIASES = {
    "krom": "chrome",
    "google chrome": "chrome",
    "google krom": "chrome",
    "çift gp": "chrome",
    "cift gp": "chrome",
    "spotifi": "spotify",
    "spotifay": "spotify",
    "kursor": "cursor",
    "termınal": "terminal",
    "youtube": "youtube",
    "you tube": "youtube",
    "yt": "youtube",
    "ayarlar": "settings",
    "sistem ayarları": "settings",
    "sistem ayarlari": "settings",
}

_OPEN_VERB = (
    r"açar\s+m[ıi]s[ıi]n|açar\s+musun|açsana|açsene|"
    r"aç(?:ar)?|ac(?:ar)?|"
    r"open(?:ing)?|launch(?:ing)?|başlat|baslat|göster|goster|show"
)
_OPEN_VERB_FIND = re.compile(rf"(?<!\w)({_OPEN_VERB})(?!\w)", re.I)

_POLITE = re.compile(
    r"^(?:lütfen|please)\s+|\s+(?:lütfen|please|misin|mısın|musun|mu|mı|mi|efendim|sir)+$",
    re.I,
)


def has_open_verb(text: str) -> bool:
    """True only for open *verbs* — «açık» (adjective) does not match «aç»."""
    return bool(_OPEN_VERB_FIND.search((text or "").lower()))


def normalize_open_target(raw: str) -> str:
    target = (raw or "").strip(" .!?,\"'")
    if not target:
        return ""
    target = _POLITE.sub("", target).strip(" .!?,\"'")
    target = re.sub(r"^(?:the|uygulama|app|bana)\s+", "", target, flags=re.I)
    # Strip trailing open verbs: "chrome'u aç"
    target = re.sub(
        rf"\s+(?:'u|'yu|u|yu|yi|yı|i|ı)?\s*(?:{_OPEN_VERB})\s*$",
        "",
        target,
        flags=re.I,
    )
    # Strip leading open verbs: "aç chrome"
    target = re.sub(rf"^(?:{_OPEN_VERB})\s+", "", target, flags=re.I)
    target = _POLITE.sub("", target).strip(" .!?,\"'")
    # possessive endings
    target = re.sub(r"['']u$|['']yu$|u$|yu$|yi$|yı$", "", target, flags=re.I).strip()
    lower = target.lower()
    if lower in SPEECH_APP_ALIASES:
        return SPEECH_APP_ALIASES[lower]
    return target


def extract_open_target(text: str) -> Optional[str]:
    raw = (text or "").strip()
    if not raw:
        return None
    lower = raw.lower()

    # Tab / "açık …" questions are not open-app
    if re.search(r"(?<!\w)(?:açık|acik)\s+(?:sekme|tab|pencere)", lower):
        return None
    if not has_open_verb(lower):
        return None

    # "<app> aç" / "chrome'u açsana"
    m = re.search(
        rf"^(.+?)\s+(?:'u|'yu|u|yu|yi|yı|i|ı)?\s*(?:{_OPEN_VERB})\s*$",
        lower,
        re.I,
    )
    if m:
        candidate = normalize_open_target(raw[m.start(1) : m.end(1)])
        if candidate and candidate.lower() not in ("ık", "ik", "ık."):
            return candidate

    # "aç <app>"
    m = re.match(rf"^(?:{_OPEN_VERB})\s+(.+)$", lower, re.I)
    if m:
        candidate = normalize_open_target(raw[m.start(1) : m.end(1)])
        if candidate and candidate.lower() not in ("ık", "ik"):
            return candidate

    for m in _OPEN_VERB_FIND.finditer(lower):
        after = normalize_open_target(raw[m.end() :])
        before = normalize_open_target(raw[: m.start()])
        if before and (not after or after.lower() in ("lütfen", "please", "misin", "mısın")):
            if before.lower() not in ("ık", "ik"):
                return before
        if after and after.lower() not in ("ık", "ik", "lütfen", "please"):
            return after
        if before and before.lower() not in ("ık", "ik"):
            return before
    return None


def looks_like_action(command: str) -> bool:
    """True when utterance should stay on local tools, not chat-only Cursor."""
    import re

    lower = (command or "").lower()
    # Multi-char / spaced phrases — substring OK
    phrases = (
        "open", "launch", "başlat", "baslat",
        "close", "quit", "kapat", "kapa",
        "çalıştır", "calistir", "run ", "execute",
        "search", "google", "ara ",
        "kaydet", "hatırlat", "hatirlat", "göster", "goster",
    )
    if any(p in lower for p in phrases):
        return True
    # Short TR verbs need word boundaries ("ac" must not match "kısaca")
    return bool(
        re.search(r"(?<!\w)(?:aç|ac)(?!\w)", lower)
    )
