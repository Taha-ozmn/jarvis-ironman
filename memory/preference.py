"""Fast-path user name / address / language preference handling."""

from __future__ import annotations

import re
import threading
from typing import Any, Callable, Optional

from memory.extractor import extract_and_save, parse_name_preference
from memory.repository import MemoryRepository
from voice.speaker import DEFAULT_ENGLISH_VOICE, resolve_edge_voice

SaveConfigFn = Callable[[dict], None]

LANGUAGE_TR_PATTERNS = (
    "türkçe konuşur musun",
    "turkce konusur musun",
    "türkçe konuş",
    "turkce konus",
    "türkçe cevap",
    "turkce cevap",
    "türkçe yanıt",
    "turkce yanit",
    "benimle türkçe",
    "benimle turkce",
    "turkish please",
    "speak turkish",
    "in turkish",
)

LANGUAGE_EN_PATTERNS = (
    "ingilizce cevap",
    "ingilizce konuş",
    "ingilizce konus",
    "speak english",
    "answer in english",
    "english please",
    "full ingilizce",
    "british english",
    "ingilizce aksan",
    "english accent",
    "british accent",
    "british voice",
    "speak british",
)

# Spoken when user asks for Turkish replies — JARVIS stays English (text + TTS).
ENGLISH_REPLY_LOCK_ACK = (
    "I understand Turkish, but I'll keep replying in English. "
    "Say the command again whenever you're ready."
)

# Legacy alias — English replies are locked on.
TURKISH_ONLY_ACK = ENGLISH_REPLY_LOCK_ACK

LOCKED_REPLY_LOCALE = "en-GB"
LOCKED_REPLY_CODE = "en"


def wants_english_replies(text: str) -> bool:
    """True when the user asks JARVIS to speak / accent in English."""
    lower = (text or "").lower().strip()
    if not lower:
        return False
    if any(phrase in lower for phrase in LANGUAGE_EN_PATTERNS):
        return True
    return "ingilizce" in lower and any(
        w in lower for w in ("cevap", "konuş", "konus", "aksan", "yanıt", "yanit")
    )


def wants_turkish_replies(text: str) -> bool:
    """True when the user explicitly asks for Turkish replies (ignored for TTS)."""
    lower = (text or "").lower().strip()
    if not lower:
        return False
    for phrase in LANGUAGE_TR_PATTERNS:
        if phrase in lower:
            return True
    return bool(
        re.search(r"\btürkçe\b|\bturkce\b", lower)
        and any(
            w in lower
            for w in ("konuş", "konus", "cevap", "yanıt", "yanit", "speak", "answer")
        )
    )


def parse_language_preference(text: str) -> Optional[str]:
    """Return 'en-GB' for English lock requests; None for Turkish (no TTS switch)."""
    lower = (text or "").lower().strip()
    if not lower:
        return None
    if wants_english_replies(lower):
        return LOCKED_REPLY_LOCALE
    # Turkish reply requests are acknowledged elsewhere — never switch speak language.
    if wants_turkish_replies(lower):
        return None
    return None


def language_preference_ack(language: str = "en-GB") -> str:
    del language
    return "Understood — I'll reply in English from now on."


def looks_turkish(text: str) -> bool:
    """Heuristic: user is speaking Turkish (listen locale; replies stay EN)."""
    if re.search(r"[ğüşıöçĞÜŞİÖÇ]", text or ""):
        return True
    lower = (text or "").lower()
    hints = (
        "merhaba", "selam", "aç", "açar", "saat", "hava",
        "teşekkür", "tesekkur", "dinle", "dinliyor", "güncelle", "guncelle",
        "yardım", "yardim", "tamam", "evet", "hayır", "hayir",
    )
    return any(h in lower for h in hints)


def preference_ack(name: str, *, language: str = "en-GB") -> str:
    del language
    return f"Understood — I'll address you as {name}."


def _lock_english_speech(
    *,
    config: Optional[dict[str, Any]],
    brain: Any,
    speaker: Any,
) -> str:
    """Force reply_language=en and Ryan Neural — never Emel."""
    edge_voice = DEFAULT_ENGLISH_VOICE
    if config is not None:
        voice_cfg = config.get("voice") or {}
        jarvis = config.setdefault("jarvis", {})
        edge_voice = resolve_edge_voice(
            LOCKED_REPLY_LOCALE,
            turkish_voice=voice_cfg.get("turkish_voice"),
            english_voice=voice_cfg.get("english_voice") or DEFAULT_ENGLISH_VOICE,
            legacy_voice=jarvis.get("voice") or DEFAULT_ENGLISH_VOICE,
        )
        jarvis["language"] = LOCKED_REPLY_LOCALE
        jarvis["reply_language"] = LOCKED_REPLY_CODE
        jarvis["speak_language"] = LOCKED_REPLY_CODE
        jarvis["turkish_only"] = False
        jarvis["voice"] = edge_voice
        voice_cfg = config.setdefault("voice", {})
        voice_cfg.setdefault("listen_language", "tr-TR")
        voice_cfg["english_voice"] = (
            voice_cfg.get("english_voice") or DEFAULT_ENGLISH_VOICE
        )

    if brain is not None and hasattr(brain, "set_language"):
        brain.set_language(LOCKED_REPLY_LOCALE)
    elif brain is not None:
        brain.language = LOCKED_REPLY_LOCALE
        if hasattr(brain, "reply_language"):
            brain.reply_language = LOCKED_REPLY_CODE
        if hasattr(brain, "address"):
            brain.address = getattr(brain, "user_name", "") or "sir"

    if speaker is not None:
        speaker.language = LOCKED_REPLY_LOCALE
        speaker.voice = edge_voice

    return edge_voice


def apply_name_preference(
    command: str,
    *,
    repo: Optional[MemoryRepository] = None,
    config: Optional[dict[str, Any]] = None,
    brain: Any = None,
    os_context: Any = None,
    save_config: Optional[SaveConfigFn] = None,
    async_persist: bool = True,
) -> Optional[str]:
    """Parse, persist, and apply a name preference without invoking Cursor agent."""
    parsed = parse_name_preference(command)
    if not parsed:
        return None

    name, content = parsed
    ack = preference_ack(name, language=LOCKED_REPLY_LOCALE)

    if brain is not None:
        brain.user_name = name
        brain.address = name

    if os_context is not None:
        try:
            if hasattr(os_context, "update"):
                os_context.update(user_name=name)
            else:
                os_context.user_name = name
        except Exception:
            pass

    if config is not None:
        jarvis = config.setdefault("jarvis", {})
        jarvis["user_name"] = name

    def _persist() -> None:
        if repo is not None:
            try:
                repo.upsert_by_key("user_name", content, category="preference", importance=3)
                extract_and_save(repo, command, ack)
            except Exception:
                pass
        if config is not None and save_config is not None:
            try:
                save_config(config)
            except Exception:
                pass

    if async_persist:
        threading.Thread(target=_persist, daemon=True).start()
    else:
        _persist()

    return ack


def apply_language_preference(
    command: str,
    *,
    repo: Optional[MemoryRepository] = None,
    config: Optional[dict[str, Any]] = None,
    brain: Any = None,
    speaker: Any = None,
    save_config: Optional[SaveConfigFn] = None,
    async_persist: bool = True,
) -> Optional[str]:
    """English replies locked: reinforce EN/Ryan; refuse Turkish TTS switch."""
    if wants_turkish_replies(command):
        _lock_english_speech(config=config, brain=brain, speaker=speaker)
        ack = ENGLISH_REPLY_LOCK_ACK

        def _persist_tr_refuse() -> None:
            if repo is not None:
                try:
                    repo.upsert_by_key(
                        "reply_language_en",
                        "User asked for Turkish; JARVIS stays English replies",
                        category="preference",
                        importance=3,
                    )
                    extract_and_save(repo, command, ack)
                except Exception:
                    pass
            if config is not None and save_config is not None:
                try:
                    save_config(config)
                except Exception:
                    pass

        if async_persist:
            threading.Thread(target=_persist_tr_refuse, daemon=True).start()
        else:
            _persist_tr_refuse()
        return ack

    lang = parse_language_preference(command)
    if not lang:
        return None

    ack = language_preference_ack(lang)
    _lock_english_speech(config=config, brain=brain, speaker=speaker)

    def _persist() -> None:
        if repo is not None:
            try:
                repo.upsert_by_key(
                    "reply_language_en",
                    "User prefers English replies",
                    category="preference",
                    importance=3,
                )
                extract_and_save(repo, command, ack)
            except Exception:
                pass
        if config is not None and save_config is not None:
            try:
                save_config(config)
            except Exception:
                pass

    if async_persist:
        threading.Thread(target=_persist, daemon=True).start()
    else:
        _persist()

    return ack
