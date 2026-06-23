"""JARVIS voice — British neural, single-response queue."""

from __future__ import annotations

import asyncio
import queue
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Literal, Optional

import edge_tts

Engine = Literal["native", "edge", "jarvis"]


class VoiceSpeaker:
    """One phrase at a time — clears stale queue when a new reply starts."""

    DEFAULT_VOICE_EDGE = "en-GB-RyanNeural"
    DEFAULT_VOICE_NATIVE = "Daniel"

    def __init__(
        self,
        voice: str | None = None,
        rate: str = "+10%",
        engine: Engine = "jarvis",
        native_voice: str = "Daniel",
        native_rate: int = 178,
        edge_timeout: float = 10.0,
        cinematic: bool = True,
    ) -> None:
        self.engine = engine
        self.edge_voice = voice or self.DEFAULT_VOICE_EDGE
        self.native_voice = native_voice
        self.rate = rate
        self.native_rate = native_rate
        self.edge_timeout = edge_timeout
        self.cinematic = cinematic
        self._queue: queue.Queue[Optional[str]] = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="jarvis-voice", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)

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
            self._queue.put(text.strip())

    def speak(self, text: str) -> None:
        self.flush()
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
        if self.engine in ("edge", "jarvis") and self.cinematic:
            try:
                await asyncio.wait_for(self._speak_edge(text), timeout=self.edge_timeout)
                return
            except Exception:
                pass

        if self.engine in ("native", "jarvis"):
            self._speak_native(text)
            if self.engine == "native":
                return

        if self.engine in ("edge", "jarvis"):
            try:
                await asyncio.wait_for(self._speak_edge(text), timeout=self.edge_timeout)
            except Exception:
                self._speak_native(text)

    def _speak_native(self, text: str) -> None:
        subprocess.run(
            ["say", "-v", self.native_voice, "-r", str(self.native_rate), text],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )

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
