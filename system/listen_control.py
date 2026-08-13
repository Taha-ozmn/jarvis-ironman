"""Voice/text phrases to pause or resume microphone listening."""

from __future__ import annotations

PAUSE_PHRASES = (
    "beni dinleme",
    "artık dinleme",
    "arti dinleme",
    "dinleme artık",
    "dinleme artik",
    "dinlemeyi durdur",
    "dinlemeyi kapat",
    "mikrofonu kapat",
    "mikrofon kapat",
    "stop listening",
    "don't listen",
    "do not listen",
    "pause listening",
    "mute mic",
    "mic off",
)

RESUME_PHRASES = (
    "tekrar dinle",
    "yeniden dinle",
    "dinlemeye başla",
    "dinlemeye basla",
    "mikrofonu aç",
    "mikrofonu ac",
    "mikrofon aç",
    "start listening",
    "listen again",
    "resume listening",
    "listen to me",
    "mic on",
    "beni dinle",
)


def is_pause_command(text: str) -> bool:
    lower = text.lower().strip()
    return any(p in lower for p in PAUSE_PHRASES)


def is_resume_command(text: str) -> bool:
    lower = text.lower().strip()
    if is_pause_command(lower):
        return False
    return any(p in lower for p in RESUME_PHRASES)


def classify_listen_command(text: str) -> str | None:
    if is_pause_command(text):
        return "pause"
    if is_resume_command(text):
        return "resume"
    return None
