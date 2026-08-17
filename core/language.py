"""Language alignment helper — STT vs TTS / persona locale (Phase 9)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class LanguageAlignment:
    speak: str
    listen: str
    aligned: bool
    dual_locale: bool = False
    warning: str = ""


def _primary(tag: str) -> str:
    return (tag or "").strip().lower().split("-")[0].split("_")[0]


def check_language_alignment(config: Optional[dict[str, Any]] = None) -> LanguageAlignment:
    """Compare jarvis.language (TTS) with listen_language (STT).

    dual_locale=true is a first-class complete voice mode (e.g. TR listen / EN speak).
    """
    cfg = config or {}
    jarvis = cfg.get("jarvis") or {}
    voice = cfg.get("voice") or {}
    speak = str(jarvis.get("language") or "en-GB")
    listen = str(
        voice.get("listen_language") or jarvis.get("listen_language") or speak
    )
    dual = bool(voice.get("dual_locale", False) or jarvis.get("dual_locale", False))
    aligned = _primary(speak) == _primary(listen)
    warning = ""
    if not aligned and not dual:
        warning = (
            f"STT ({listen}) and TTS ({speak}) primary languages differ — "
            "set voice.dual_locale: true or match listen_language to jarvis.language."
        )
    return LanguageAlignment(
        speak=speak,
        listen=listen,
        aligned=aligned,
        dual_locale=dual,
        warning=warning,
    )
