#!/usr/bin/env python3
"""Speak text aloud — CLI hook for agents, scripts, and Cursor replies."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.loader import load_config
from voice.speaker import VoiceSpeaker


def build_speaker() -> VoiceSpeaker:
    config = load_config()
    j = config.get("jarvis", {})
    v = config.get("voice", {})
    return VoiceSpeaker(
        voice=v.get("english_voice") or j.get("voice", "en-GB-RyanNeural"),
        rate=v.get("rate", "-10%"),
        pitch=v.get("pitch", "-4Hz"),
        volume=v.get("volume", "+0%"),
        engine=v.get("engine", "jarvis"),
        native_voice=v.get("native_voice", "Daniel"),
        native_rate=int(v.get("native_rate", 165)),
        edge_timeout=float(v.get("edge_timeout", 25)),
        edge_retries=int(v.get("edge_retries", 2)),
        cinematic=bool(v.get("cinematic", True)),
        native_first=bool(v.get("native_first", True)),
        language=j.get("language", "en-GB"),
        use_ssml=bool(v.get("ssml", True)),
        phrase_gap_sec=float(v.get("phrase_gap_sec", 0.04)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Speak text with JARVIS voice")
    parser.add_argument("text", nargs="*", help="Words to speak")
    parser.add_argument(
        "--stdin", action="store_true", help="Read full reply from stdin when no args"
    )
    parser.add_argument("--timeout", type=float, default=45.0, help="Max seconds to wait")
    args = parser.parse_args(argv)

    text = " ".join(args.text).strip()
    if not text and (args.stdin or not sys.stdin.isatty()):
        text = sys.stdin.read().strip()
    if not text:
        parser.error("nothing to speak")

    speaker = build_speaker()
    speaker.speak_sync(text, timeout=args.timeout)
    speaker.wait_until_idle(timeout=args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
