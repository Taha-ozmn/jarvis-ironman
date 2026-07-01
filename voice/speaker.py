"""JARVIS voice — neural TTS with safe single-playback fallback."""

from __future__ import annotations

import asyncio
import queue
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal, Optional

import edge_tts

Engine = Literal["native", "edge", "jarvis"]

VOICE_ALIASES = {
    "tr-ahmetneural": "tr-TR-AhmetNeural",
    "tr-ahmet": "tr-TR-AhmetNeural",
    "ahmet": "tr-TR-AhmetNeural",
    "ahmetneural": "tr-TR-AhmetNeural",
    "yelda": "Yelda",
    "tr-yelda": "Yelda",
    "ryan": "en-GB-RyanNeural",
    "daniel": "Daniel",
}


def normalize_voice(voice: str, language: str = "tr-TR") -> str:
    """Fix common voice typos (e.g. TR-AhmetNeural → tr-TR-AhmetNeural)."""
    raw = (voice or "").strip()
    if not raw:
        return "tr-TR-AhmetNeural" if language.lower().startswith("tr") else "en-GB-RyanNeural"

    key = re.sub(r"[_\s]+", "-", raw).lower()
    if key in VOICE_ALIASES:
        return VOICE_ALIASES[key]

    # TR-AhmetNeural, tr-ahmet-neural, etc.
    if "ahmet" in key and language.lower().startswith("tr"):
        return "tr-TR-AhmetNeural"
    if key in {"tr-ahmetneural", "tr-tr-ahmetneural"}:
        return "tr-TR-AhmetNeural"

    if raw in VOICE_ALIASES.values():
        return raw
    if "-" in raw and raw[0].islower():
        return raw
    if language.lower().startswith("tr") and not raw.startswith("tr-"):
        if "neural" in key or "ahmet" in key or "emel" in key:
            name = "AhmetNeural" if "ahmet" in key or "emel" not in key else "EmelNeural"
            return f"tr-TR-{name}"
    return raw


def is_edge_voice(voice: str) -> bool:
    return "Neural" in voice or voice.startswith(("tr-", "en-", "de-", "fr-"))


class VoiceSpeaker:
    """One phrase at a time — clears stale queue when a new reply starts."""

    DEFAULT_VOICE_EDGE = "tr-TR-AhmetNeural"
    DEFAULT_VOICE_NATIVE = "Yelda"

    def __init__(
        self,
        voice: str | None = None,
        rate: str = "+10%",
        engine: Engine = "jarvis",
        native_voice: str = "Yelda",
        native_rate: int = 178,
        edge_timeout: float = 10.0,
        cinematic: bool = True,
        native_first: bool = False,
        language: str = "tr-TR",
    ) -> None:
        self.language = language
        self.engine = engine
        self.edge_voice = normalize_voice(voice or "", language)
        self.native_voice = native_voice if native_voice else (
            "Yelda" if language.lower().startswith("tr") else "Daniel"
        )
        self.rate = rate
        self.native_rate = native_rate
        self.edge_timeout = edge_timeout
        self.cinematic = cinematic
        self.native_first = native_first
        self._last_spoken = ""
        self._queue: queue.Queue[Optional[str]] = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="jarvis-voice", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)
        print(f"🔊 Ses: {self.edge_voice} (motor: {self.engine})")

    @property
    def voice(self) -> str:
        return self.edge_voice

    @voice.setter
    def voice(self, value: str) -> None:
        self.edge_voice = value

    def flush(self) -> None:
        """Drop pending phrases — new command gets one clean reply."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def say(self, text: str) -> None:
        if text and text.strip():
            phrase = text.strip()
            if phrase == self._last_spoken:
                return
            self._last_spoken = phrase
            self._queue.put(phrase)

    def speak(self, text: str) -> None:
        self.flush()
        self._last_spoken = ""
        self.say(text)

    def speak_sync(self, text: str, timeout: float = 25.0) -> None:
        if not text or not text.strip():
            return
        done = threading.Event()
        phrase = text.strip()

        def _once() -> None:
            try:
                if self._loop and self._loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        self._speak_phrase_async(phrase), self._loop
                    )
                    future.result(timeout=timeout)
                else:
                    asyncio.run(self._speak_phrase_async(phrase))
            except Exception as err:
                print(f"⚠️  Voice: {err}")
            finally:
                done.set()

        threading.Thread(target=_once, daemon=True).start()
        if not done.wait(timeout=timeout):
            print("⚠️  Voice timeout — metin HUD'da görünür.")

    def _worker(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        while True:
            text = self._queue.get()
            if text is None:
                break
            try:
                self._loop.run_until_complete(self._speak_phrase_async(text))
            except Exception as err:
                print(f"⚠️  Voice error: {err}")

    async def _speak_phrase_async(self, text: str) -> None:
        if self.native_first or self.engine == "native":
            self._speak_native(text)
            return

        use_edge = self.engine == "edge" or (
            self.engine == "jarvis" and self.cinematic and is_edge_voice(self.edge_voice)
        )
        if use_edge:
            try:
                await asyncio.wait_for(self._speak_edge(text), timeout=self.edge_timeout)
                return
            except Exception as err:
                print(f"⚠️  Edge TTS: {err} — yerel Türkçe sese geçiliyor.")

        self._speak_native(text)

    def _speak_native(self, text: str) -> None:
        voice = self.native_voice
        if self.language.lower().startswith("tr"):
            voice = "Yelda"
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
        if not parts:
            return
        for i, part in enumerate(parts):
            subprocess.run(
                ["say", "-v", voice, "-r", str(self.native_rate), part],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
            if i < len(parts) - 1:
                time.sleep(0.22)

    async def _speak_edge(self, text: str) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            communicate = edge_tts.Communicate(text, self.edge_voice, rate=self.rate)
            await communicate.save(str(path))
            subprocess.run(
                ["afplay", str(path)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
        finally:
            path.unlink(missing_ok=True)
