"""Speech cleanup — strip fillers and raw English tool failures before TTS."""

from __future__ import annotations

import re

from core.recovery import user_safe_speech

_EFENDIM = re.compile(r"(?i)\befendim\b")
_LEADING_ROBOTIC = re.compile(
    r"(?i)^(bakıyorum\.?|looking\.?|one moment\.?|processing\.?)\s*"
)
_MULTI_SPACE = re.compile(r"\s+")


def strip_efendim(text: str) -> str:
    return _EFENDIM.sub("", text or "").strip()


def strip_robotic_filler(text: str) -> str:
    t = (text or "").strip()
    prev = None
    while prev != t:
        prev = t
        t = _LEADING_ROBOTIC.sub("", t).strip()
    return _MULTI_SPACE.sub(" ", t).strip()


def speak_safe(text: str, language: str = "en-GB") -> str:
    """Clean TTS text; rewrite raw open/connect failures into recovery speech."""
    t = strip_robotic_filler(strip_efendim((text or "").strip()))
    if not t:
        return t
    if re.match(r"(?i)^(could not|failed to|unable to|connection failed)\b", t):
        return user_safe_speech(t, language=language)
    return t
