"""Transcribe audio uploaded from mobile HUD clients (iPhone / Android)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Sequence


def _convert_to_wav(source: Path, destination: Path) -> bool:
    """Convert uploaded mobile audio to 16-bit PCM WAV for SpeechRecognition."""
    suffix = source.suffix.lower()
    if suffix == ".wav":
        destination.write_bytes(source.read_bytes())
        return destination.exists() and destination.stat().st_size > 44

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(source),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                str(destination),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and destination.exists():
            return destination.stat().st_size > 44

    if suffix in {".m4a", ".mp4", ".caf", ".aac"}:
        result = subprocess.run(
            [
                "afconvert",
                "-f",
                "WAVE",
                "-d",
                "LEI16@16000",
                str(source),
                str(destination),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and destination.exists():
            return destination.stat().st_size > 44

    return False


def _recognize_wav(wav_path: Path, languages: Sequence[str]) -> Optional[str]:
    try:
        import speech_recognition as sr
    except ImportError:
        return None

    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(str(wav_path)) as source:
            audio = recognizer.record(source)
    except Exception:
        return None

    candidates: list[tuple[str, float]] = []
    for language in languages:
        lang = (language or "tr-TR").strip()
        if not lang:
            continue
        try:
            result = recognizer.recognize_google(audio, language=lang, show_all=True)
        except sr.UnknownValueError:
            continue
        except sr.RequestError:
            continue
        except Exception:
            continue

        if isinstance(result, dict):
            alternatives = result.get("alternative") or []
            if alternatives:
                transcript = str(alternatives[0].get("transcript") or "").strip()
                confidence = float(alternatives[0].get("confidence") or 0.0)
                if transcript:
                    candidates.append((transcript, confidence))
        elif isinstance(result, str) and result.strip():
            candidates.append((result.strip(), 0.0))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[1])[0]


def transcribe_bytes(
    data: bytes,
    *,
    filename: str = "upload.webm",
    languages: Sequence[str] = ("tr-TR", "en-US"),
) -> Optional[str]:
    """Return transcript text or None when recognition fails."""
    if not data or len(data) < 128:
        return None

    suffix = Path(filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(data)
        source = Path(handle.name)

    destination = source.with_suffix(".wav")
    try:
        if not _convert_to_wav(source, destination):
            return None
        return _recognize_wav(destination, languages)
    finally:
        source.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
