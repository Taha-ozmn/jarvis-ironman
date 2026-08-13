"""Speech-to-text with wake word — macOS native + optional PyAudio fallback."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

SWIFT_LISTENER = Path(__file__).resolve().parent / "macos_listen"
SWIFT_SOURCE = Path(__file__).resolve().parent / "macos_listen.swift"


class VoiceListener:
    """Continuous microphone listener with JARVIS wake word."""

    WAKE_PATTERN = re.compile(
        r"\b(hey\s+)?(ok\s+)?jarvis\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        language: str = "tr-TR",
        energy_threshold: int = 300,
        pause_threshold: float = 0.8,
        phrase_limit: int = 12,
        listen_timeout: float = 8.0,
        ambient_seconds: float = 1.5,
        on_wake: Optional[Callable[[], None]] = None,
        on_partial: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.language = language
        self.energy_threshold = energy_threshold
        self.pause_threshold = pause_threshold
        self.listen_timeout = listen_timeout
        self.phrase_limit = phrase_limit
        self.ambient_seconds = ambient_seconds
        self.on_wake = on_wake
        self.on_partial = on_partial
        self._use_pyaudio = False
        self._recognizer = None
        self._ensure_listener()

    def _ensure_listener(self) -> None:
        if not SWIFT_LISTENER.exists() and SWIFT_SOURCE.exists():
            subprocess.run(
                ["swiftc", "-o", str(SWIFT_LISTENER), str(SWIFT_SOURCE)],
                check=False,
                capture_output=True,
            )
        if SWIFT_LISTENER.exists():
            return
        try:
            import speech_recognition as sr

            self._recognizer = sr.Recognizer()
            self._recognizer.energy_threshold = self.energy_threshold
            self._recognizer.pause_threshold = self.pause_threshold
            self._use_pyaudio = True
        except ImportError:
            pass

    def calibrate(self) -> None:
        if self._use_pyaudio and self._recognizer:
            import speech_recognition as sr

            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=self.ambient_seconds)

    def _listen_native(self, timeout: float) -> Optional[str]:
        if not SWIFT_LISTENER.exists():
            return None
        try:
            result = subprocess.run(
                [str(SWIFT_LISTENER), str(timeout)],
                capture_output=True,
                text=True,
                timeout=timeout + 8,
            )
            if result.returncode != 0:
                err = (result.stderr or "").strip()
                if err:
                    print(f"⚠️  Native mic: {err}")
                if result.returncode < 0:
                    self._rebuild_native_listener()
                return None

            wav_path = (result.stdout or "").strip()
            if not wav_path:
                return None
            return self._recognize_wav(wav_path)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def _recognize_wav(self, wav_path: str) -> Optional[str]:
        path = Path(wav_path)
        try:
            import speech_recognition as sr
        except ImportError:
            return None
        try:
            recognizer = self._recognizer or sr.Recognizer()
            with sr.AudioFile(str(path)) as source:
                audio = recognizer.record(source)
            return recognizer.recognize_google(audio, language=self.language)
        except sr.UnknownValueError:
            return None
        except sr.RequestError as err:
            print(f"⚠️  Google speech API: {err}")
            return None
        except Exception as err:
            print(f"⚠️  Speech recognition: {err}")
            return None
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _rebuild_native_listener(self) -> None:
        if not SWIFT_SOURCE.exists():
            return
        try:
            SWIFT_LISTENER.unlink(missing_ok=True)
        except OSError:
            pass
        build = subprocess.run(
            ["swiftc", "-o", str(SWIFT_LISTENER), str(SWIFT_SOURCE)],
            capture_output=True,
            text=True,
        )
        if build.returncode != 0 and build.stderr:
            print(f"⚠️  Swift rebuild failed: {build.stderr.strip()}")

    def _listen_pyaudio(self, timeout: float) -> Optional[str]:
        if not self._use_pyaudio or not self._recognizer:
            return None
        import speech_recognition as sr

        try:
            with sr.Microphone() as source:
                audio = self._recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=self.phrase_limit,
                )
            return self._recognizer.recognize_google(audio, language=self.language)
        except (sr.WaitTimeoutError, sr.UnknownValueError, sr.RequestError):
            return None

    def listen_once(self) -> Optional[str]:
        text = self._listen_native(self.listen_timeout)
        if text:
            return text
        return self._listen_pyaudio(self.listen_timeout)

    def listen_for_wake_and_command(self) -> Optional[str]:
        text = self.listen_once()
        if not text:
            return None

        if self.on_partial:
            self.on_partial(text)

        match = self.WAKE_PATTERN.search(text)
        if not match:
            return None

        if self.on_wake:
            self.on_wake()

        command = text[match.end() :].strip(" ,.-")
        if command:
            return command

        return self.listen_once()

    def extract_wake_command(self, text: str) -> Optional[str]:
        match = self.WAKE_PATTERN.search(text)
        if not match:
            return None
        command = text[match.end() :].strip(" ,.-")
        return command or None
