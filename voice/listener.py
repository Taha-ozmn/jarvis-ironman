"""Speech-to-text with wake word — macOS native + optional PyAudio fallback."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, Optional, Sequence

# Import structured logger
from core.structured_logger import (
    log_user_input,
    log_voice_partial,
    log_voice_final,
    log_intent_detected,
    log_error,
    LogEvent,
)
from security.speaker_verification import SpeakerVerifier

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
        recognition_languages: Optional[Sequence[str]] = None,
        energy_threshold: int = 300,
        pause_threshold: float = 1.4,
        phrase_limit: int = 15,
        listen_timeout: float = 15.0,
        native_idle_timeout: float = 1.5,
        native_silence_timeout: float = 1.4,
        ambient_seconds: float = 1.5,
        on_wake: Optional[Callable[[], None]] = None,
        on_partial: Optional[Callable[[str], None]] = None,
        on_recognizing: Optional[Callable[[], None]] = None,
        speaker_verifier: Optional[SpeakerVerifier] = None,
        on_voice_rejected: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.language = language
        configured_languages = recognition_languages or (language,)
        self.recognition_languages = tuple(
            dict.fromkeys(str(item).strip() for item in configured_languages if str(item).strip())
        ) or (language,)
        self.energy_threshold = energy_threshold
        self.pause_threshold = pause_threshold
        self.listen_timeout = listen_timeout
        self.native_idle_timeout = max(0.3, float(native_idle_timeout))
        self.native_silence_timeout = max(0.3, float(native_silence_timeout))
        self.phrase_limit = phrase_limit
        self.ambient_seconds = ambient_seconds
        self.on_wake = on_wake
        self.on_partial = on_partial
        self.on_recognizing = on_recognizing
        self.speaker_verifier = speaker_verifier
        self.on_voice_rejected = on_voice_rejected
        self._use_pyaudio = False
        self._recognizer = None
        self._ensure_listener()
        # Log listener initialization
        from core.structured_logger import structured_logger
        structured_logger.info(
            LogEvent.TASK_CREATED,
            "voice.listener",
            f"VoiceListener initialized: language={self.language}",
            status="initialized"
        )

    def _ensure_listener(self) -> None:
        needs_build = (
            SWIFT_SOURCE.exists()
            and (
                not SWIFT_LISTENER.exists()
                or SWIFT_SOURCE.stat().st_mtime > SWIFT_LISTENER.stat().st_mtime
            )
        )
        if needs_build:
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

    def _capture_native(self, timeout: float) -> Optional[Path]:
        if not SWIFT_LISTENER.exists():
            return None
        try:
            result = subprocess.run(
                [
                    str(SWIFT_LISTENER),
                    str(timeout),
                    str(self.native_idle_timeout),
                    str(self.native_silence_timeout),
                ],
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
            if not wav_path or not Path(wav_path).exists():
                return None
            return Path(wav_path)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def _listen_native(self, timeout: float) -> Optional[str]:
        wav_path = self._capture_native(timeout)
        if wav_path is None:
            return None
        return self._recognize_wav(wav_path)

    def _recognize_wav(self, wav_path: str) -> Optional[str]:
        path = Path(wav_path)
        try:
            import speech_recognition as sr
            if self.speaker_verifier is not None:
                verification = self.speaker_verifier.verify_file(path)
                if not verification.accepted:
                    if self.on_voice_rejected:
                        self.on_voice_rejected(verification.reason)
                    return None
            recognizer = self._recognizer or sr.Recognizer()
            with sr.AudioFile(str(path)) as source:
                audio = recognizer.record(source)
            # Recording is done and the audio is captured — surface immediate
            # feedback before the STT network round-trip so the HUD does not
            # look frozen while transcription resolves.
            if self.on_recognizing:
                try:
                    self.on_recognizing()
                except Exception:  # noqa: BLE001 — UI feedback must never break STT
                    pass
            text = self._recognize_audio(recognizer, audio)
            # Log the recognized text (could be partial or final, we don't know here)
            # The caller (listen_once) will differentiate via on_partial and on_wake.
            # We'll log as partial for now, but note that the final command logging happens in main.py.
            log_voice_partial("voice.listener", text)
            return text
        except ImportError:
            return None
        except sr.UnknownValueError:
            return None
        except sr.RequestError as err:
            print(f"⚠️  Google speech API: {err}")
            log_error("voice.listener", str(err), "RequestError")
            return None
        except Exception as err:
            print(f"⚠️  Speech recognition: {err}")
            log_error("voice.listener", str(err), "SpeechRecognitionError")
            return None
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _recognize_language(
        self, recognizer: object, audio: object, language: str
    ) -> tuple[Optional[tuple[str, str, float]], Optional[Exception]]:
        """Run one Google recognition pass; return (candidate, request_error)."""
        try:
            result = recognizer.recognize_google(
                audio,
                language=language,
                show_all=True,
            )
        except Exception as err:  # noqa: BLE001 — SR raises broad types
            import speech_recognition as sr

            return None, err if isinstance(err, sr.RequestError) else None
        if isinstance(result, dict):
            alternatives = result.get("alternative") or []
            if alternatives:
                best = alternatives[0]
                transcript = str(best.get("transcript") or "").strip()
                confidence = float(best.get("confidence") or 0.0)
                if transcript:
                    return (language, transcript, confidence), None
        elif isinstance(result, str) and result.strip():
            return (language, result.strip(), 0.0), None
        return None, None

    def _recognize_audio(self, recognizer: object, audio: object) -> str:
        """Recognize Turkish and English in parallel; pick strongest transcript.

        The two Google round-trips ran sequentially before, doubling the
        network latency the user saw on-screen. Running them concurrently cuts
        the wait to a single round-trip while keeping bilingual coverage.
        """
        languages = self.recognition_languages
        candidates: list[tuple[str, str, float]] = []
        request_errors: list[Exception] = []

        if len(languages) <= 1:
            candidate, error = self._recognize_language(
                recognizer, audio, languages[0] if languages else self.language
            )
            if candidate:
                candidates.append(candidate)
            elif error:
                request_errors.append(error)
        else:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FTimeout

            # A hung network call must never wedge the listen loop.
            budget = max(6.0, float(self.listen_timeout))
            with ThreadPoolExecutor(max_workers=len(languages)) as executor:
                futures = [
                    executor.submit(
                        self._recognize_language, recognizer, audio, language
                    )
                    for language in languages
                ]
                for future in futures:
                    try:
                        candidate, error = future.result(timeout=budget)
                    except _FTimeout:
                        continue
                    if candidate:
                        candidates.append(candidate)
                    elif error:
                        request_errors.append(error)

        if not candidates:
            if request_errors:
                raise request_errors[0]
            raise ValueError("Speech recognition returned no transcript")
        selected = max(candidates, key=self._candidate_score)
        return selected[1]

    @staticmethod
    def _candidate_score(candidate: tuple[str, str, float]) -> float:
        language, transcript, confidence = candidate
        lower = transcript.lower()
        turkish_markers = (
            "aç", "kapat", "ekran", "benim", "için", "nedir", "nasıl",
            "saat", "bugün", "dosya", "uygulama", "dinle", "dur",
        )
        english_markers = (
            "open", "close", "screen", "my", "please", "what", "how",
            "file", "application", "listen", "stop", "status",
        )
        marker_score = 0.0
        if any(marker in lower for marker in turkish_markers):
            marker_score += 0.16 if language.lower().startswith("tr") else 0.08
        if any(marker in lower for marker in english_markers):
            marker_score += 0.16 if language.lower().startswith("en") else 0.08
        if any(char in lower for char in "çğıöşü"):
            marker_score += 0.12
        return confidence + marker_score + min(len(lower), 120) / 10_000

    def capture_audio(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """Capture one WAV without STT, used by the guided enrollment flow."""

        capture_timeout = float(timeout or self.listen_timeout)
        wav_path = self._capture_native(capture_timeout)
        if wav_path is not None:
            try:
                return wav_path.read_bytes()
            except OSError:
                return None
            finally:
                try:
                    wav_path.unlink(missing_ok=True)
                except OSError:
                    pass

        if not self._use_pyaudio or not self._recognizer:
            return None
        try:
            import speech_recognition as sr

            with sr.Microphone() as source:
                audio = self._recognizer.listen(
                    source,
                    timeout=capture_timeout,
                    phrase_time_limit=self.phrase_limit,
                )
            return audio.get_wav_data()
        except (sr.WaitTimeoutError, sr.UnknownValueError, sr.RequestError):
            return None

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
            log_error("voice.listener", f"Swift rebuild failed: {build.stderr.strip()}", "BuildError")

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
            if self.speaker_verifier is not None:
                verification = self.speaker_verifier.verify_bytes(audio.get_wav_data())
                if not verification.accepted:
                    if self.on_voice_rejected:
                        self.on_voice_rejected(verification.reason)
                    return None
            text = self._recognize_audio(self._recognizer, audio)
            log_voice_partial("voice.listener", text)
            return text
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
        # Log that wake word was detected
        from core.structured_logger import structured_logger
        structured_logger.info(
            LogEvent.VOICE_FINAL,
            "voice.listener",
            f"Wake word detected in: {text}",
            status="detected"
        )

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