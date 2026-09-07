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
from typing import Any, Callable, Literal, Optional

try:
    import edge_tts as _edge_tts
except ImportError:  # pragma: no cover - native-first still works offline
    _edge_tts = None  # type: ignore[assignment]


def _edge_tts_module() -> Any:
    if _edge_tts is None:
        raise RuntimeError("edge-tts is not installed")
    return _edge_tts

from voice.speech_clean import (
    normalize_for_dedupe,
    speak_safe,
    split_speech_phrases,
    tts_inner_ssml,
)

# Import structured logger
from core.structured_logger import (
    log_tts_started,
    log_tts_interrupted,
    log_error,
    log_retry,
    log_recovery,
    LogEvent,
)

Engine = Literal["native", "edge", "jarvis"]

DEFAULT_TURKISH_VOICE = "tr-TR-EmelNeural"
DEFAULT_ENGLISH_VOICE = "en-GB-RyanNeural"
AHMET_VOICE = "tr-TR-AhmetNeural"
# Slightly slower + lower — calm professional, not rushed neural TTS.
DEFAULT_RATE = "-10%"
DEFAULT_PITCH = "-4Hz"
DEFAULT_VOLUME = "+0%"
DEFAULT_PHRASE_GAP_SEC = 0.04
DEFAULT_USE_SSML = True

# Synthesis only (afplay is separate). edge-tts needs headroom on slow links.
DEFAULT_EDGE_TIMEOUT = 25.0
DEFAULT_EDGE_RETRIES = 2
EDGE_CONNECT_TIMEOUT = 15
EDGE_RECEIVE_TIMEOUT = 60
FALLBACK_WARN_COOLDOWN_SEC = 120.0

VOICE_ALIASES = {
    "tr-ahmetneural": AHMET_VOICE,
    "tr-ahmet": AHMET_VOICE,
    "ahmet": AHMET_VOICE,
    "ahmetneural": AHMET_VOICE,
    "tr-emelneural": DEFAULT_TURKISH_VOICE,
    "tr-emel": DEFAULT_TURKISH_VOICE,
    "emel": DEFAULT_TURKISH_VOICE,
    "emelneural": DEFAULT_TURKISH_VOICE,
    "yelda": "Yelda",
    "tr-yelda": "Yelda",
    "ryan": DEFAULT_ENGLISH_VOICE,
    "daniel": "Daniel",
}


def normalize_voice(voice: str, language: str = "en-GB") -> str:
    """Fix common voice typos; honour language for EN vs TR neural voices."""
    raw = (voice or "").strip()
    lang = (language or "en-GB").lower()
    default = DEFAULT_ENGLISH_VOICE if lang.startswith("en") else DEFAULT_TURKISH_VOICE
    if not raw:
        return default

    key = re.sub(r"[_\s]+", "-", raw).lower()
    if key in VOICE_ALIASES:
        return VOICE_ALIASES[key]

    if "ahmet" in key:
        return AHMET_VOICE
    if "emel" in key:
        return DEFAULT_TURKISH_VOICE
    if "ryan" in key:
        return DEFAULT_ENGLISH_VOICE
    if key in {"tr-ahmetneural", "tr-tr-ahmetneural"}:
        return AHMET_VOICE
    if key in {"tr-emelneural", "tr-tr-emelneural"}:
        return DEFAULT_TURKISH_VOICE

    if raw.startswith(("en-", "tr-")):
        return raw
    if raw in (DEFAULT_TURKISH_VOICE, AHMET_VOICE, DEFAULT_ENGLISH_VOICE):
        return raw
    if "-" in raw and raw[0].islower() and raw.startswith("tr-"):
        return raw
    if not raw.startswith(("tr-", "en-")):
        if "neural" in key or "ahmet" in key or "emel" in key:
            name = "AhmetNeural" if "ahmet" in key else "EmelNeural"
            return f"tr-TR-{name}"
    return default


def resolve_edge_voice(
    language: str = "en-GB",
    *,
    turkish_voice: str | None = None,
    english_voice: str | None = None,
    legacy_voice: str | None = None,
) -> str:
    """Resolve edge-tts voice from reply language (English film JARVIS by default)."""
    lang = (language or "en-GB").lower()
    if lang.startswith("en"):
        raw = english_voice or legacy_voice or DEFAULT_ENGLISH_VOICE
        return normalize_voice(raw, "en-GB")
    raw = turkish_voice or legacy_voice or DEFAULT_TURKISH_VOICE
    return normalize_voice(raw, "tr-TR")


def is_edge_voice(voice: str) -> bool:
    return "Neural" in voice or voice.startswith(("tr-", "en-", "de-", "fr-"))


def format_edge_error(err: BaseException) -> str:
    """Human-readable edge-tts / asyncio errors (TimeoutError has empty str)."""
    if isinstance(err, asyncio.TimeoutError):
        return "timeout (TimeoutError)"
    name = type(err).__name__
    msg = str(err).strip()
    if msg:
        return f"{name}: {msg}"
    cause = getattr(err, "__cause__", None) or getattr(err, "__context__", None)
    if cause is not None:
        cmsg = str(cause).strip() or type(cause).__name__
        return f"{name} ({cmsg})"
    return name


async def list_turkish_voices() -> list[str]:
    """Return ShortName list for tr-* edge-tts voices."""
    edge_tts = _edge_tts_module()
    voices = await edge_tts.list_voices()
    return sorted(v["ShortName"] for v in voices if v["Locale"].startswith("tr-"))


async def is_valid_edge_voice(voice: str) -> bool:
    """Check voice ID against live edge-tts catalog."""
    edge_tts = _edge_tts_module()
    voices = await edge_tts.list_voices()
    names = {v["ShortName"] for v in voices}
    return voice in names


class VoiceSpeaker:
    """One phrase at a time — clears stale queue when a new reply starts."""

    DEFAULT_VOICE_EDGE = DEFAULT_ENGLISH_VOICE
    DEFAULT_VOICE_NATIVE = "Daniel"

    def __init__(
        self,
        voice: str | None = None,
        rate: str = DEFAULT_RATE,
        pitch: str = DEFAULT_PITCH,
        volume: str = DEFAULT_VOLUME,
        engine: Engine = "jarvis",
        native_voice: str = "Daniel",
        native_rate: int = 178,
        edge_timeout: float = DEFAULT_EDGE_TIMEOUT,
        edge_retries: int = DEFAULT_EDGE_RETRIES,
        cinematic: bool = True,
        native_first: bool = False,
        language: str = "en-GB",
        use_ssml: bool = DEFAULT_USE_SSML,
        phrase_gap_sec: float = DEFAULT_PHRASE_GAP_SEC,
    ) -> None:
        self.language = language
        self.engine = engine
        self.edge_voice = normalize_voice(voice or "", language)
        self.native_voice = native_voice if native_voice else (
            "Yelda" if language.lower().startswith("tr") else "Daniel"
        )
        self.rate = rate
        self.pitch = pitch
        self.volume = volume
        self.native_rate = native_rate
        self.edge_timeout = max(8.0, float(edge_timeout))
        self.edge_retries = max(0, int(edge_retries))
        self.cinematic = cinematic
        self.native_first = native_first
        self.use_ssml = bool(use_ssml)
        self.phrase_gap_sec = max(0.0, min(0.45, float(phrase_gap_sec)))
        self._last_spoken = ""
        self._last_spoken_norm = ""
        self._queue: queue.Queue[Optional[str]] = queue.Queue()
        self._speaking = threading.Event()
        self._on_busy_change: Optional[Callable[[bool], None]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._edge_ok = True
        self._fallback_warned_at = 0.0
        self._last_edge_ok_at = 0.0
        self._thread = threading.Thread(target=self._worker, name="jarvis-voice", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)
        print(
            f"🔊 Ses: {self.edge_voice} "
            f"(motor: {self.engine}, hız: {self.rate}, ton: {self.pitch})"
        )
        # Log speaker initialization
        from core.structured_logger import structured_logger
        structured_logger.info(
            LogEvent.TASK_CREATED,  # Using TASK_CREATED as a generic init event
            "voice.speaker",
            f"VoiceSpeaker initialized: voice={self.edge_voice}, engine={self.engine}",
            status="initialized"
        )

    @property
    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    @property
    def is_busy(self) -> bool:
        """True while a phrase is queued or currently playing (hard listen gate)."""
        return self.is_speaking or (not self._queue.empty())

    def set_busy_callback(self, callback: Optional[Callable[[bool], None]]) -> None:
        self._on_busy_change = callback

    def _emit_busy(self, busy: bool) -> None:
        cb = self._on_busy_change
        if cb is None:
            return
        try:
            cb(busy)
        except Exception:
            pass

    @property
    def voice(self) -> str:
        return self.edge_voice

    @voice.setter
    def voice(self, value: str) -> None:
        self.edge_voice = normalize_voice(value, self.language)

    def flush(self) -> None:
        """Drop pending phrases — new command gets one clean reply."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self.interrupt()

    def interrupt(self) -> None:
        """Stop current TTS playback aggressively (afplay/say)."""
        self._last_spoken = ""
        self._last_spoken_norm = ""
        for proc_name in ("afplay", "say"):
            try:
                subprocess.run(
                    ["killall", proc_name],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except Exception:
                pass
        # Log interruption
        log_tts_interrupted("voice.speaker")

    def say(self, text: str) -> None:
        if text and text.strip():
            phrase = speak_safe(text.strip(), self.language)
            if not phrase:
                return
            norm = normalize_for_dedupe(phrase)
            if norm and norm == self._last_spoken_norm:
                return
            if phrase == self._last_spoken:
                return
            self._last_spoken = phrase
            self._last_spoken_norm = norm
            was_busy = self.is_busy
            self._queue.put(phrase)
            if not was_busy:
                self._emit_busy(True)
            # Log that we queued a phrase (debug level)
            from core.structured_logger import structured_logger
            structured_logger.debug(
                LogEvent.TTS_STARTED,  # We'll use TTS_STARTED for queuing? Actually, we queued but not started playing.
                "voice.speaker",
                f"Queued TTS phrase: {phrase[:50]}...",
                status="queued"
            )

    def speak(self, text: str) -> None:
        self.flush()
        self._last_spoken = ""
        self._last_spoken_norm = ""
        self.say(text)

    def wait_until_idle(self, timeout: float = 30.0) -> None:
        """Block until the voice queue finishes (for mic resume after TTS)."""
        deadline = time.monotonic() + max(0.5, timeout)
        while time.monotonic() < deadline:
            if self._queue.empty() and not self._speaking.is_set():
                return
            time.sleep(0.05)

    def speak_sync(self, text: str, timeout: float = 25.0) -> None:
        if not text or not text.strip():
            return
        done = threading.Event()
        phrase = speak_safe(text.strip(), self.language)
        if not phrase:
            return

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
                print(f"⚠️  Voice: {format_edge_error(err)}")
                # Log error
                log_error("voice.speaker", format_edge_error(err), "TTSError")
            finally:
                done.set()

        threading.Thread(target=_once, daemon=True).start()
        if not done.wait(timeout=timeout):
            print("⚠️  Voice timeout — metin HUD'da görünür.")
            log_error("voice.speaker", "TTS timeout", "TimeoutError")

    def _worker(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        while True:
            text = self._queue.get()
            if text is None:
                break
            # Log that we started speaking a phrase
            log_tts_started("voice.speaker", text[:50] if len(text) > 50 else text)
            self._speaking.set()
            self._emit_busy(True)
            try:
                self._loop.run_until_complete(self._speak_phrase_async(text))
            except Exception as err:
                print(f"⚠️  Voice error: {format_edge_error(err)}")
                log_error("voice.speaker", format_edge_error(err), "TTSError")
            finally:
                self._speaking.clear()
                if not self.is_busy:
                    self._emit_busy(False)
                # Log that we finished speaking a phrase
                from core.structured_logger import structured_logger
                structured_logger.info(
                    LogEvent.TTS_STARTED,  # Actually we finished, but we don't have a TTS_COMPLETED event? We have TTS_STARTED and TTS_INTERRUPTED. Let's use TTS_STARTED for start and then we don't have an end. We'll add a custom status.
                    "voice.speaker",
                    f"Finished TTS phrase: {text[:50] if len(text) > 50 else text}",
                    status="completed"
                )

    async def _speak_phrase_async(self, text: str) -> None:
        if self.native_first or self.engine == "native":
            self._speak_native(text)
            return

        use_edge = (
            _edge_tts is not None
            and (
                self.engine == "edge"
                or (
                    self.engine == "jarvis"
                    and self.cinematic
                    and is_edge_voice(self.edge_voice)
                )
            )
        )
        if use_edge:
            last_err: BaseException | None = None
            attempts = 1 + self.edge_retries
            for attempt in range(attempts):
                try:
                    # Synthesis only — afplay must not share the edge timeout budget.
                    await asyncio.wait_for(
                        self._synthesize_edge(text),
                        timeout=self.edge_timeout,
                    )
                    self._edge_ok = True
                    self._last_edge_ok_at = time.monotonic()
                    # Log successful edge TTS synthesis
                    from core.structured_logger import structured_logger
                    structured_logger.info(
                        LogEvent.MODEL_RESPONSE,  # Using MODEL_RESPONSE as a stand-in for successful TTS? Not ideal.
                        "voice.speaker",
                        f"Edge TTS synthesis succeeded (attempt {attempt+1}/{attempts})",
                        status="success"
                    )
                    return
                except Exception as err:
                    last_err = err
                    if attempt < attempts - 1:
                        await asyncio.sleep(0.35 * (attempt + 1))
                        # Log retry
                        log_retry("voice.speaker", attempt+1, attempts, f"Edge TTS failed: {format_edge_error(err)}")
                        continue
            self._notify_edge_fallback(last_err)
            # Always deliver the phrase — edge failure must not leave text-only replies.
            self._speak_native(text)
            return
        else:
            # Use native
            self._speak_native(text)

    def _notify_edge_fallback(self, err: BaseException | None) -> None:
        """Warn once per cooldown — avoid spamming every phrase."""
        now = time.monotonic()
        detail = format_edge_error(err) if err else "bilinmeyen hata"
        if now - self._fallback_warned_at >= FALLBACK_WARN_COOLDOWN_SEC:
            self._fallback_warned_at = now
            self._edge_ok = False
            print(
                f"⚠️  Edge TTS: {detail} — neural voice unavailable, "
                "falling back to local speech."
            )
            # Log fallback
            log_recovery("voice.speaker", f"Falling back to native TTS due to: {detail}")
            # One clear spoken notice (native), then continue with phrase.
            notice = (
                "Neural voice is temporarily unavailable. "
                "Continuing with the local voice."
            )
            try:
                self._speak_native(notice)
            except Exception:
                pass
        # Within cooldown: silent native fallback (no log spam).

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

    def _make_communicate(self, text: str) -> Any:
        """Build Communicate; inject SSML <break> into the inner prosody body."""
        edge_tts = _edge_tts_module()
        communicate = edge_tts.Communicate(
            text,
            self.edge_voice,
            rate=self.rate,
            pitch=self.pitch,
            volume=self.volume,
            connect_timeout=EDGE_CONNECT_TIMEOUT,
            receive_timeout=EDGE_RECEIVE_TIMEOUT,
        )
        if self.use_ssml and hasattr(communicate, "text"):
            inner = tts_inner_ssml(text)
            if inner:
                communicate.text = inner
        return communicate

    async def _download_edge_mp3(self, text: str, path: Path) -> None:
        communicate = self._make_communicate(text)
        await communicate.save(str(path))
        if path.stat().st_size < 64:
            raise RuntimeError("edge-tts boş ses dosyası üretti")

    def _play_mp3(self, path: Path) -> None:
        subprocess.run(
            ["afplay", str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )

    async def _synthesize_edge(self, text: str) -> None:
        """Download MP3 via edge-tts then play with afplay.

        Long replies: parallel synthesize (bounded chunks) + short inter-phrase
        pause. SSML breaks inside each chunk slow the robotic cadence without
        extra network round-trips for every comma.
        """
        phrases = split_speech_phrases(text)
        if not phrases:
            return
        if len(phrases) == 1:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                path = Path(tmp.name)
            try:
                await self._download_edge_mp3(phrases[0], path)
                self._play_mp3(path)
            finally:
                path.unlink(missing_ok=True)
            return

        paths: list[Path] = []
        try:
            for _ in phrases:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    paths.append(Path(tmp.name))
            await asyncio.gather(
                *[self._download_edge_mp3(p, dest) for p, dest in zip(phrases, paths)]
            )
            for i, path in enumerate(paths):
                self._play_mp3(path)
                if i < len(paths) - 1 and self.phrase_gap_sec > 0:
                    await asyncio.sleep(self.phrase_gap_sec)
        finally:
            for path in paths:
                path.unlink(missing_ok=True)

    async def _speak_edge(self, text: str) -> None:
        """Backward-compatible alias used by older tests/scripts."""
        await self._synthesize_edge(text)