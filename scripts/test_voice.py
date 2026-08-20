#!/usr/bin/env python3
"""Quick edge-tts voice smoke test — generates a human-paced Emel sample.

Play:
  python3 scripts/test_voice.py
  python3 scripts/test_voice.py --play
  python3 scripts/test_voice.py --out /tmp/jarvis_emel.mp3 && afplay /tmp/jarvis_emel.mp3
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import edge_tts

from voice.speaker import (
    DEFAULT_PITCH,
    DEFAULT_RATE,
    DEFAULT_TURKISH_VOICE,
    DEFAULT_VOLUME,
    DEFAULT_USE_SSML,
    list_turkish_voices,
)
from voice.speech_clean import speak_safe_tr, tts_inner_ssml

SAMPLE_TEXT = (
    "Günaydın. Sistemler hazır. "
    "Bugün takviminizde iki toplantı var; isterseniz özetleyeyim."
)


async def _speak_sample(
    voice: str,
    text: str,
    rate: str,
    pitch: str,
    volume: str,
    out: Path | None,
    *,
    use_ssml: bool,
) -> Path:
    target = out or Path(tempfile.gettempdir()) / f"jarvis_voice_{voice.replace('-', '_')}.mp3"
    phrase = speak_safe_tr(text) or text
    communicate = edge_tts.Communicate(
        phrase,
        voice,
        rate=rate,
        pitch=pitch,
        volume=volume,
    )
    if use_ssml and hasattr(communicate, "text"):
        inner = tts_inner_ssml(phrase)
        if inner:
            communicate.text = inner
    await communicate.save(str(target))
    return target


async def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS edge-tts voice smoke test")
    parser.add_argument(
        "--voice",
        default=DEFAULT_TURKISH_VOICE,
        help="edge-tts ShortName (default: tr-TR-EmelNeural)",
    )
    parser.add_argument("--text", default=SAMPLE_TEXT, help="Sample phrase")
    parser.add_argument("--rate", default=DEFAULT_RATE)
    parser.add_argument("--pitch", default=DEFAULT_PITCH)
    parser.add_argument("--volume", default=DEFAULT_VOLUME)
    parser.add_argument("--no-ssml", action="store_true", help="Disable SSML break injection")
    parser.add_argument("--list-tr", action="store_true", help="List Turkish edge-tts voices")
    parser.add_argument("--out", type=Path, default=None, help="Output MP3 path")
    parser.add_argument("--play", action="store_true", help="Play with afplay after save")
    args = parser.parse_args()

    if args.list_tr:
        for name in await list_turkish_voices():
            print(name)
        return

    use_ssml = DEFAULT_USE_SSML and not args.no_ssml
    path = await _speak_sample(
        args.voice,
        args.text,
        args.rate,
        args.pitch,
        args.volume,
        args.out,
        use_ssml=use_ssml,
    )
    print(f"Saved: {path}")
    print(f"Voice: {args.voice}  rate={args.rate}  pitch={args.pitch}  ssml={use_ssml}")
    print(f"Play:  afplay {path}")
    if args.play:
        import subprocess

        subprocess.run(["afplay", str(path)], check=False)


if __name__ == "__main__":
    asyncio.run(main())
