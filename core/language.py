"""Language alignment helper — STT vs TTS / persona locale (N-05)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class LanguageAlignment:
    speak: str
    listen: str
    aligned: bool
    warning: str = ""


def _primary(tag: str) -> str:
    return (tag or "").strip().lower().split("-")[0].split("_")[0]


def check_language_alignment(config: Optional[dict[str, Any]] = None) -> LanguageAlignment:
    """Compare jarvis.language (TTS/persona) with listen_language (STT)."""
    cfg = config or {}
    jarvis = cfg.get("jarvis") or {}
    voice = cfg.get("voice") or {}
    speak = str(jarvis.get("language") or "en-GB")
    listen = str(
        voice.get("listen_language")
        or jarvis.get("listen_language")
        or speak
    )
    aligned = _primary(speak) == _primary(listen)
    warning = ""
    if not aligned:
        warning = (
            f"STT ({listen}) and TTS ({speak}) primary languages differ — "
            "confirm replies and speech may mix locales."
        )
    return LanguageAlignment(speak=speak, listen=listen, aligned=aligned, warning=warning)
