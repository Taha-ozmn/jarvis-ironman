"""Neural TTS MP3 bytes for iPhone HUD playback (Ryan / en-GB)."""

from __future__ import annotations

import asyncio
import io
from typing import Optional

import edge_tts

from voice.speaker import (
    DEFAULT_ENGLISH_VOICE,
    DEFAULT_PITCH,
    DEFAULT_RATE,
    DEFAULT_VOLUME,
    normalize_voice,
)
from voice.speech_clean import speak_safe


async def _synth_mp3(
    text: str,
    *,
    voice: str,
    rate: str,
    pitch: str,
    volume: str,
) -> bytes:
    communicate = edge_tts.Communicate(
        text,
        voice,
        rate=rate,
        pitch=pitch,
        volume=volume,
    )
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    data = buf.getvalue()
    if len(data) < 64:
        raise RuntimeError("empty mobile tts output")
    return data


def synthesize_mp3_bytes(
    text: str,
    *,
    voice: str = DEFAULT_ENGLISH_VOICE,
    language: str = "en-GB",
    rate: str = DEFAULT_RATE,
    pitch: str = DEFAULT_PITCH,
    volume: str = DEFAULT_VOLUME,
    max_chars: int = 320,
) -> Optional[bytes]:
    """Return MP3 bytes for phone playback, or None on failure."""
    clean = speak_safe(text, language=language)
    if not clean:
        return None
    if len(clean) > max_chars:
        trimmed = clean[: max_chars - 1].rsplit(" ", 1)[0]
        clean = (trimmed or clean[:max_chars]).rstrip(".,;:") + "."
    resolved = normalize_voice(voice, language)
    try:
        return asyncio.run(
            _synth_mp3(
                clean,
                voice=resolved,
                rate=rate,
                pitch=pitch,
                volume=volume,
            )
        )
    except Exception:
        return None
