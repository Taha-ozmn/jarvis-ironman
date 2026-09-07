#!/usr/bin/env python3
"""
J.A.R.V.I.S. — Iron Man style voice assistant powered by Cursor API.

Usage:
  python main.py              # Voice mode (default)
  python main.py --text       # Text mode for testing
  python main.py --ui-only    # Launch HUD only
"""

from __future__ import annotations

import argparse
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from brain.cursor_brain import JarvisBrain
from brain.model_router import ModelRouter
from config.loader import ensure_jarvis2_defaults
from system.macos import MacOSController
from system.hud_stats import get_telemetry
from voice.listener import VoiceListener
from voice.narrator import JarvisNarrator
from voice.self_listen_guard import SelfListenGuard
from voice.speaker import VoiceSpeaker
from security.speaker_verification import SpeakerProfileError, SpeakerVerifier
from core.structured_logger import (
    log_user_input,
    log_intent_detected,
    log_tool_started,
    log_tool_completed,
    log_message,
    log_error,
    log_model_request,
    log_model_response,
)
from core.process_manager import process_manager
from core.connection_recovery import connection_recovery
from core.health_monitor import register_health_provider, start_health_monitor
from core.request_context import set_request_id, clear_request_id

load_dotenv(ROOT / ".env")

BRITISH_VOICES = ("Daniel", "Reed", "Rocko")
logger = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = ROOT / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return ensure_jarvis2_defaults(raw)


def save_config(config: dict) -> None:
    config_path = ROOT / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)


class JarvisCore:
    """Orchestrates voice, brain, system control, and UI."""

    def __init__(self, config: dict) -> None:
        self.config = config
        j = config["jarvis"]
        j2 = config.get("jarvis2", {})
        v = config["voice"]
        safe_profile = str(j2.get("autonomy_profile", "safe")).lower() == "safe"

        llm_provider = str(j.get("llm_provider", "cursor")).lower()
        if llm_provider == "nvidia":
            api_key = (
                os.environ.get("NVIDIA_API_KEY")
                or os.environ.get("CURSOR_API_KEY", "")
            )
            if not api_key or api_key.startswith("cursor_your"):
                print(
                    "\n⚠️  NVIDIA API key missing — starting in tools-only degraded mode."
                )
        else:
            api_key = os.environ.get("CURSOR_API_KEY", "")
            if not api_key or api_key.startswith("cursor_your"):
                print(
                    "\n⚠️  CURSOR_API_KEY missing — starting in tools-only degraded mode."
                )

        self.speaker = VoiceSpeaker(
            voice=os.environ.get("JARVIS_VOICE", j.get("voice", "en-GB-RyanNeural")),
            rate=v.get("speech_rate", "+10%"),
            engine=v.get("engine", "jarvis"),
            native_voice=v.get("native_voice", "Daniel"),
            native_rate=v.get("native_rate", 172),
            edge_timeout=v.get("edge_timeout", 14.0),
            cinematic=v.get("cinematic", True),
            native_first=v.get("native_first", True),
            language=os.environ.get("JARVIS_LANGUAGE", j.get("language", "en-GB")),
        )
        # Set up speaker busy callback to manage microphone during speech
        self.speaker.set_busy_callback(self._on_speaker_busy_change)
        self.listen_guard = SelfListenGuard(
            self.speaker,
            enabled=bool(v.get("self_listen_guard", True)),
            cooldown_ms=int(v.get("post_tts_cooldown_ms", 220)),
            block_while_processing=not bool(
                config.get("ui", {}).get("always_listen", True)
            ),
        )
        identity_cfg = config.get("voice_identity", {})
        identity_enabled = bool(identity_cfg.get("enabled", False))
        profile_value = str(identity_cfg.get("profile_path", "data/voice_profile.json"))
        profile_path = Path(profile_value).expanduser()
        if not profile_path.is_absolute():
            profile_path = ROOT / profile_path
        self.speaker_verifier = (
            SpeakerVerifier(
                profile_path,
                threshold=identity_cfg.get("threshold", 0.88),
                min_voiced_frames=identity_cfg.get("min_voiced_frames", 8),
                require_profile=identity_cfg.get("require_profile", True),
            )
            if identity_enabled
            else None
        )
        listen_lang = (
            os.environ.get("JARVIS_LISTEN_LANGUAGE")
            or v.get("listen_language")
            or "tr-TR"
        )
        self.listener = VoiceListener(
            language=listen_lang,
            recognition_languages=v.get(
                "listen_languages",
                (listen_lang, "en-US"),
            ),
            energy_threshold=v.get("energy_threshold", 300),
            pause_threshold=v.get("pause_threshold", 1.4),
            phrase_limit=v.get("phrase_limit", 15),
            listen_timeout=v.get("listen_timeout", 15),
            native_idle_timeout=v.get("native_idle_timeout_sec", 1.5),
            native_silence_timeout=v.get("native_silence_timeout_sec", 1.4),
            ambient_seconds=v.get("ambient_calibration_seconds", 1.5),
            on_wake=self._on_wake,
            on_partial=self._on_heard,
            on_recognizing=self._on_recognizing,
            speaker_verifier=self.speaker_verifier,
            on_voice_rejected=self._on_voice_rejected,
        )
        sys_cfg = config.get("system", {})
        self.system = MacOSController(
            full_shell_access=sys_cfg.get("full_shell_access", True),
        )
        self.brain = JarvisBrain(
            api_key=api_key,
            workspace=j.get("workspace", "~"),
            model=j.get("model", "composer-2.5"),
            user_name=os.environ.get("JARVIS_USER_NAME", j.get("user_name", "sir")),
            formal_address=j.get("formal_address", True),
            language=os.environ.get("JARVIS_LANGUAGE", j.get("language", "en-GB")),
            full_access=bool(j.get("full_access", True)) and not safe_profile,
            sandbox=bool(j.get("sandbox", False)) or safe_profile,
            auto_review=j.get("auto_review", False),
            setting_sources=j.get("setting_sources", "all"),
            skip_model_list=j.get("skip_model_list", True),
            on_thinking=self._on_thinking,
            think_timeout=j.get("think_timeout", 90.0),
            complex_timeout=j.get("complex_timeout", 600.0),
            deep_timeout=j.get("deep_timeout", 1200.0),
            start_timeout_sec=j.get("brain_start_timeout_sec", 15.0),
            soft_timeout_sec=j.get("soft_timeout_sec", 5.0),
            hard_timeout_sec=j.get("hard_timeout_sec", 0.0),
            background_on_timeout=j.get("background_on_timeout", True),
            ask_on_timeout=j.get("ask_on_timeout", False),
            auto_retry_count=j.get("auto_retry_count", 0),
            progress_interval_sec=j.get("progress_interval_sec", 5.0),
            latency_stats_path=ROOT / "data" / "latency_stats.json",
            narrate=j.get("narrate", True),
            work_updates=j.get("work_updates", True),
            max_progress_updates=j.get("max_progress_updates", 3),
            persona=j.get("persona", "iron_man"),
            conversation_turns=j.get("conversation_turns", 6),
            persona_refresh_interval=j.get("persona_refresh_interval", 5),
            model_routing=j.get("model_routing", True),
            stream_preview=j.get("stream_preview", False),
            models=j.get("models"),
            llm_provider=j.get("llm_provider", "cursor"),
        )
        # Hard-lock spoken replies to English (input may be Turkish)
        self.brain.reply_language = "en"
        self.brain.language = os.environ.get("JARVIS_LANGUAGE", j.get("language", "en-GB"))
        if str(self.brain.language).lower().startswith("tr"):
            self.brain.language = "en-GB"
        self.brain.address = self.brain.user_name or "sir"
        self.brain.fast_mode = j.get("fast_mode", True)
        self.brain.max_speech_chars = j.get("max_speech_chars", 280)
        from config.loader import load_personality
        from core.persona_engine import apply_personality_to_brain

        personality = load_personality()
        apply_personality_to_brain(self.brain, personality)
        if hasattr(self.brain, "refresh_timeout_voice"):
            self.brain.refresh_timeout_voice()
        self.speak_ack = j.get("speak_ack", False)
        self.preload_brain = j.get("preload_brain", True)
        self.ai_only = j.get("ai_only", True)
        display_name = str(personality.get("display_name") or j.get("user_name", "Taha"))
        self.narrator = JarvisNarrator(user_name=display_name)
        self.ui = None
        self.os_v2 = None  # JARVIS 2.0 core (optional soft-init)
        self._status = "idle"
        queue_size = max(
            1,
            int(config.get("ui", {}).get("command_queue_maxsize", 8)),
        )
        self._command_queue: queue.Queue[str] = queue.Queue(maxsize=queue_size)
        self._processing = threading.Lock()
        self._current_request_id: Optional[str] = None
        self._boot_greeting_sent = False
        self._listening_enabled = True
        self._speaking_busy = False
        self._tts_gate_epoch = 0

        j2 = config.get("jarvis2", {})
        if j2.get("enabled", True) and j2.get("soft_init", True):
            from core.app import try_create_os

            self.os_v2 = try_create_os(config, root=ROOT, macos=self.system)
            if self.os_v2 is not None:
                self.brain.set_memory_recall(self.os_v2.recall_for_prompt)
                self.os_v2.set_speak_callback(self._jarvis_speak)
                try:
                    self.os_v2.bind_brain(self.brain)
                except Exception:
                    pass

        # Initialize health monitoring
        try:
            # Register health providers for core systems
            register_health_provider("process_manager", lambda: process_manager.get_stats())
            register_health_provider("connection_recovery", lambda: connection_recovery.get_health())

            # Start the health monitor
            start_health_monitor()
        except Exception as e:
            # Don't let health monitor failures break the system
            print(f"⚠️  Health monitor initialization error: {e}")

    def set_mic_listening(self, enabled: bool, *, announce: bool = True) -> str:
        self._listening_enabled = enabled
        if self.ui:
            self.ui.send_mic_state(enabled)
        # Also update SessionContext in JARVIS 2.0 for consistent state reporting
        if self.os_v2 is not None:
            self.os_v2.context.set_listening_enabled(enabled)
        if enabled:
            detail = "Standing by — speak your command"
            msg = "Very good — I'm listening again, sir."
        else:
            detail = 'Mic paused — say "listen again" or press LISTEN'
            msg = "Understood — I'll remain quiet until you ask me to listen again, sir."
        self._set_status("idle", detail)
        if announce:
            self._jarvis_speak(msg)
        return msg

    def try_listen_control(self, command: str) -> Optional[str]:
        from system.listen_control import classify_listen_command

        action = classify_listen_command(command)
        if action == "pause":
            return self.set_mic_listening(False, announce=False)
        if action == "resume":
            return self.set_mic_listening(True, announce=False)
        return None

    def _should_accept_voice_command(self, command: str) -> bool:
        """Keep stop/listen controls available during TTS or task execution."""
        from system.listen_control import classify_listen_command

        if classify_listen_command(command) is not None:
            return True
        if self._is_stop_speech_phrase(command):
            return True
        return self.listen_guard.should_accept_transcript(command)

    def _is_stop_speech_phrase(self, command: str) -> bool:
        lower = (command or "").lower().strip()
        for prefix in ("hey jarvis ", "ok jarvis ", "jarvis "):
            if lower.startswith(prefix):
                lower = lower[len(prefix):].strip()
        phrases = (
            "dur", "stop", "stop talking", "stop speaking", "be quiet",
            "shut up", "sus", "kes", "sessiz ol", "konuşmayı kes",
            "konusmayi kes", "enough",
        )
        return lower in phrases or any(
            lower.startswith(p + " ") for p in phrases if len(p) > 2
        )

    def try_stop_speech(self, command: str) -> Optional[str]:
        """Interrupt TTS without shutting down JARVIS ('Jarvis dur', 'be quiet')."""
        if self._is_stop_speech_phrase(command):
            try:
                self.speaker.flush()
            except Exception:
                pass
            try:
                self.brain._interrupt_inflight()
            except Exception:
                pass
            return "Standing by."
        return None

    def _handle_mic_control(self, enabled: bool, silent: bool = False) -> None:
        if enabled == self._listening_enabled:
            return
        self.set_mic_listening(enabled, announce=not silent)

    def _continuous_listening_enabled(self) -> bool:
        return bool(self.config.get("ui", {}).get("always_listen", True))

    def _enqueue_command(self, command: str, source: str = "voice") -> bool:
        """Queue a command without silently losing it when the worker is busy."""
        text = (command or "").strip()
        if not text:
            return False
        try:
            self._command_queue.put_nowait(text)
            return True
        except queue.Full:
            detail = "Command queue full — waiting commands were preserved."
            print(f"⚠️  {detail} Source: {source}")
            self._set_status("listening", detail)
            if self.ui:
                self.ui.broadcast(
                    "status",
                    detail,
                    queue_full=True,
                    source=source,
                )
            return False

    def _start_brain_async(self) -> None:
        try:
            # Bound startup so a stalled Cursor bridge cannot block the
            # supervisor forever. Local tools, memory, and the HUD remain live
            # while the watchdog retries the neural core.
            self.brain.ensure_started(timeout=self.brain.start_timeout_sec)
            if self.ui:
                self.ui.send_telemetry(
                    get_telemetry(
                        self.config.get("jarvis", {}),
                        brain_model=self.brain.model,
                        brain_ready=self.brain.is_ready(),
                    )
                )
            if not self.brain.is_ready():
                print(
                    f"⚠️  Neural core unavailable: "
                    f"{self.brain.start_error or 'startup timeout'}"
                )
        except Exception as err:
            err_text = str(err)
            print(f"⚠️  Neural core: {err_text}")
            if "tool-callback-auth-token" in err_text or "Bridge exited" in err_text:
                print(
                    "   Bridge bağlantı hatası — JARVIS yeniden deniyor. "
                    "Sorun sürerse: ./start.sh ile yeniden başlatın."
                )
                try:
                    from brain.sdk_patch import apply_sdk_patch
                    apply_sdk_patch()
                    self.brain.stop()
                    self.brain.start()
                    if self.ui:
                        self.ui.send_telemetry(get_telemetry(self.brain.model))
                    print("✅ Neural core bağlandı.")
                    return
                except Exception as retry_err:
                    print(f"⚠️  Yeniden deneme başarısız: {retry_err}")
            self._set_status("error", str(err))

    def _send_boot_greeting(self) -> None:
        if self._boot_greeting_sent:
            return
        self._boot_greeting_sent = True
        lang = self.config.get("jarvis", {}).get("language", "en-GB")
        greeting = (
            f"{self.narrator.time_greeting(lang)} "
            "JARVIS online — all systems nominal. At your service."
        )
        if self.speaker_verifier is not None and not self.speaker_verifier.enrolled:
            greeting = (
                "Voice identity is not enrolled. Run "
                "python main.py --enroll-voice before issuing commands."
            )
        if self.os_v2 is not None:
            try:
                tip = self.os_v2.proactive_suggestion()
                if tip and len(tip) > 20:
                    greeting = f"{greeting} {tip}"
            except Exception:
                pass
        self._set_status("speaking", greeting)
        self._jarvis_speak(greeting)
        self._set_status("idle", "Standing by — speak your command")

    def _set_status(self, status: str, detail: str = "") -> None:
        self._status = status
        if self.ui:
            self.ui.broadcast(status, detail)

    def _on_wake(self) -> None:
        self._set_status("listening", "Wake word detected")
        print("\n🎙️  JARVIS dinliyor...")

    def _on_heard(self, text: str) -> None:
        self._set_status("listening", text)
        print(f"   Heard: {text}")

    def _on_recognizing(self) -> None:
        """Signal transcription is in flight without leaving the listening state.

        Using the calm "listening" state (not "thinking") keeps the reactor
        green and avoids a stuck-looking amber PROCESSING flash on the frequent
        ambient captures that Google returns with no transcript.
        """
        if self._listening_enabled:
            self._set_status("listening", "Recognizing…")

    def _on_voice_rejected(self, reason: str) -> None:
        """Report a rejected speaker without exposing biometric details."""
        del reason
        self._set_status("listening", "Voice not recognized")

    def enroll_voice_profile(self) -> bool:
        """Guide the owner through local voice-profile enrollment."""
        if self.speaker_verifier is None:
            self.speaker.speak_sync(
                "Voice identity is disabled in configuration.",
                timeout=15.0,
            )
            return False

        identity_cfg = self.config.get("voice_identity", {})
        target = max(3, min(5, int(identity_cfg.get("enrollment_samples", 4))))
        samples: list[bytes] = []
        prompts = (
            "Please say: Jarvis, open my workspace.",
            "Please say: Jarvis, what is the system status?",
            "Please say: Jarvis, remember this task.",
            "Please say: Jarvis, inspect the screen.",
            "Please say: Jarvis, continue listening.",
        )
        self.speaker.speak_sync(
            f"Voice enrollment started. I need {target} short recordings.",
            timeout=20.0,
        )
        for index in range(target):
            attempts = 0
            while attempts < 2 and len(samples) <= index:
                self.speaker.speak_sync(prompts[index], timeout=15.0)
                self.speaker.wait_until_idle(timeout=20.0)
                self._set_status("listening", f"Enrollment sample {index + 1} of {target}")
                recording = self.listener.capture_audio()
                attempts += 1
                if recording:
                    samples.append(recording)
                    break
                self.speaker.speak_sync(
                    "I did not receive a clear recording. Please repeat that sentence.",
                    timeout=15.0,
                )

        if len(samples) != target:
            self.speaker.speak_sync(
                "Voice enrollment failed. No voice profile was changed.",
                timeout=15.0,
            )
            return False
        try:
            self.speaker_verifier.enroll(samples)
        except SpeakerProfileError:
            self.speaker.speak_sync(
                "Voice enrollment failed. Please record the samples in a quieter room.",
                timeout=15.0,
            )
            return False
        self.speaker.speak_sync(
            "Voice profile saved locally. I will now accept commands only from your voice.",
            timeout=20.0,
        )
        return True

    def _on_thinking(self, text: str) -> None:
        self._set_status("thinking", text)
        if self.ui:
            self.ui.broadcast("thinking", text, thinking_trace=text)
        print(f"🧠 Processing: {text}")

    def _jarvis_speak(self, text: str) -> None:
        if not text:
            return
        self.speaker.say(text)
        if self.ui:
            self.ui.send_narration(text)

    def _on_speaker_busy_change(self, busy: bool) -> None:
        """Callback for when speaker starts/stops speaking."""
        self._speaking_busy = busy
        if busy:
            # Any native capture overlapping TTS may contain JARVIS's own voice.
            # Invalidate that capture even if it returns after playback ends.
            self._tts_gate_epoch += 1
        self.listen_guard.refresh()

    def _resume_listening_after_speech(self) -> None:
        """Wait for TTS + cooldown, then reopen mic (browser listen_gate)."""
        try:
            self.listen_guard.wait_until_accepting(timeout=35.0)
        except Exception:
            pass
        if self.ui:
            try:
                if not self._continuous_listening_enabled():
                    self.ui.flush_pending_commands()
            except Exception:
                pass
            try:
                # Explicit release — listeners may skip duplicate notify
                self.ui.send_listen_gate(False)
            except Exception:
                pass

    def boot(self) -> None:
        j = self.config.get("jarvis", {})
        fast_boot = j.get("fast_boot", True)
        boot_delay = j.get("boot_delay", 0.08 if fast_boot else 0.35)

        print("⚡ JARVIS boot sequence initiated...")
        self._set_status("booting", "Boot sequence initiated")

        brain_thread = threading.Thread(target=self._start_brain_async, daemon=True)
        brain_thread.start()

        boot_lines = (
            self.narrator.BOOT_LINES[:2]
            if fast_boot
            else self.narrator.BOOT_LINES
        )
        boot_steps = len(boot_lines)
        for i, _ in enumerate(boot_lines):
            line = self.narrator.boot_line(i)
            progress = int((i + 1) / boot_steps * (60 if fast_boot else 85))
            self._set_status("booting", line)
            if self.ui:
                self.ui.send_boot(line, progress)
            print(f"   ▸ {line}")
            time.sleep(boot_delay)

        if self.ui:
            self.ui.send_boot("JARVIS ONLINE", 100)
            self._set_status("idle", "Standing by — speak your command")

        print("✅ JARVIS hazır.\n")
        if self.ui:
            print("🎙️  Iron Man HUD aktif — doğrudan konuş")
            print(f"   http://localhost:{self.config['ui'].get('port', 8765)}\n")
        else:
            print("   Terminal modu aktif.\n")

        if self.os_v2 is not None:
            try:
                self.os_v2.start_background()
            except Exception as err:
                print(f"⚠️  Automation scheduler: {err}")

        def _finish_when_ready() -> None:
            if self.preload_brain:
                brain_thread.join(timeout=120)
            self._send_boot_greeting()

        threading.Thread(target=_finish_when_ready, daemon=True).start()
        threading.Thread(target=self._play_boot_music, daemon=True).start()

    def _play_boot_music(self) -> None:
        boot_cfg = self.config.get("boot", {})
        if not boot_cfg.get("music_enabled", True):
            return
        track = boot_cfg.get("music", {})
        title = track.get("title", "Back in Black")
        artist = track.get("artist", "AC/DC")
        player = track.get("player", "music")
        try:
            if self.system.play_track(
                title=title,
                artist=artist,
                player=player,
            ):
                print(f"🎵 Boot music (Music): {artist} — {title}")
            else:
                print("⚠️  Boot music could not start — is the Music app installed?")
        except Exception as err:
            print(f"⚠️  Boot music: {err}")

    def shutdown(self) -> None:
        try:
            self.brain.stop()
        except Exception:
            pass
        if self.os_v2 is not None:
            try:
                self.os_v2.close()
            except Exception:
                pass
        # Stop health monitoring
        try:
            stop_health_monitor()
        except Exception:
            pass
        try:
            farewell = f"Powering down, {self.brain.user_name or 'sir'}. JARVIS signing off."
            self.speaker.speak(farewell)
        except Exception:
            pass

    def jarvis2_health(self) -> Optional[dict]:
        """Self-diagnostics for Phase-2 subsystems (None if core not loaded)."""
        if self.os_v2 is None:
            return None
        return self.os_v2.health()

    def try_local_meta(self, command: str) -> Optional[str]:
        """Instant answers for meta/voice commands — skip slow AI round-trip."""
        lower = command.lower().strip()

        if any(
            p in lower
            for p in (
                "sürekli dinle",
                "continuous listen",
                "always listen",
                "dinle jarvis",
                "listen jarvis",
            )
        ):
            return "I'm always listening. Simply speak your command."

        if any(
            p in lower
            for p in (
                "dinliyor musun",
                "are you listening",
                "duyuyor musun",
            )
        ):
            return "Yes, I'm listening."

        if any(p in lower for p in ("merhaba", "hello", "hi jarvis", "hey jarvis")):
            return "Good evening. How may I assist?"

        if any(p in lower for p in ("teşekkür", "tesekkur", "thanks", "thank you")):
            return "My pleasure."

        if any(
            p in lower
            for p in (
                "güncelle",
                "guncelle",
                "update yourself",
                "self update",
                "kendini güncelle",
                "kendini guncelle",
                "güncelley",
                "guncelley",
            )
        ):
            self._schedule_restart()
            return "Done — I've upgraded my speed settings and I'm restarting now."

        if any(
            p in lower
            for p in (
                "ingilizce cevap",
                "answer in english",
                "speak english",
                "english please",
                "full ingilizce",
            )
        ) or ("ingilizce" in lower and "cevap" in lower):
            self.brain.language = "en"
            return (
                "Very good. I shall respond entirely in English — "
                "speak Turkish as you please."
            )

        if any(
            p in lower
            for p in (
                "ingilizce aksan",
                "english accent",
                "british accent",
                "british voice",
                "speak british",
            )
        ) or ("ingilizce" in lower and "aksan" in lower):
            self.brain.language = "en"
            self.speaker.voice = "Daniel"
            self.config["jarvis"]["language"] = "en"
            self.config["jarvis"]["voice"] = "Daniel"
            save_config(self.config)
            return "Very good — British English accent engaged."

        if any(p in lower for p in ("türkçe cevap", "turkish", "türkçe konuş")):
            self.brain.language = "tr-TR"
            return "Tamam, bundan sonra Türkçe yanıt vereceğim."

        if any(
            p in lower
            for p in (
                "hızlı",
                "hizli",
                "faster",
                "fast mode",
                "yavaş",
                "yavas",
                "slow",
                "geç cevap",
                "gec cevap",
                "speed",
            )
        ):
            self.brain.fast_mode = True
            return "Understood — fast mode engaged. Brief answers from here on."

        if any(
            p in lower
            for p in (
                "sesini değiştir",
                "sesini degistir",
                "ses değiştir",
                "ses degistir",
                "change voice",
                "change your voice",
                "switch voice",
                "farklı ses",
                "farkli ses",
            )
        ):
            name = self._cycle_voice()
            return f"I've switched to the {name} voice."

        switch = ModelRouter.parse_switch_command(command)
        if switch:
            return f"Single model mode — using {self.brain.model} via Cursor."

        if any(p in lower for p in ("auto model", "otomatik model", "auto mode")):
            return "Auto model is active — Cursor picks the best model per task."

        if any(p in lower for p in ("which model", "hangi model", "current model")):
            return f"Cursor model: {self.brain.model}."

        return None

    def _cycle_voice(self) -> str:
        current = self.speaker.voice
        try:
            idx = BRITISH_VOICES.index(current)
            next_voice = BRITISH_VOICES[(idx + 1) % len(BRITISH_VOICES)]
        except ValueError:
            next_voice = BRITISH_VOICES[0]
        self.speaker.voice = next_voice
        self.config["jarvis"]["voice"] = next_voice
        save_config(self.config)
        return next_voice

    def _schedule_restart(self) -> None:
        def _restart() -> None:
            time.sleep(0.8)
            import subprocess

            subprocess.Popen(
                [sys.executable, str(ROOT / "main.py")],
                cwd=str(ROOT),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os._exit(0)

        threading.Thread(target=_restart, daemon=True).start()

    def _quick_reply(self, command: str) -> Optional[str]:
        lower = command.lower().strip()
        if lower in ("merhaba", "hello", "hi", "hey", "selam"):
            return "Good evening. How may I assist?"
        return None

    def process_command(self, command: str) -> Optional[str]:
        if not command.strip():
            return "I didn't catch that."

        # Log user input
        if self._current_request_id is not None:
            log_user_input("main.core", command, task_id=self._current_request_id, execution_id=self._current_request_id)

        # Level-3 voice confirm — only when gate is waiting (interactive)
        confirm_reply = self._try_voice_confirmation(command)
        if confirm_reply is not None:
            if self._current_request_id is not None:
                log_tool_completed("main.core", "voice_confirmation", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return confirm_reply

        stop = self.try_stop_speech(command)
        if stop is not None:
            if self._current_request_id is not None:
                log_tool_completed("main.core", "stop_speech", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return stop

        shutdown = self.system.try_shutdown(command)
        if shutdown == "SHUTDOWN_JARVIS":
            if self._current_request_id is not None:
                log_tool_completed("main.core", "system_shutdown", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return shutdown

        listen = self.try_listen_control(command)
        if listen:
            if self._current_request_id is not None:
                log_tool_completed("main.core", "listen_control", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return listen

        # JARVIS 2.0 tool path — works even when ai_only is on
        tool_reply = self._try_jarvis2_tools(command)
        if tool_reply is not None:
            # Open/media failures: retry legacy macOS helpers before giving up
            if self._should_retry_local_action(command, tool_reply):
                legacy = (
                    self.system.try_direct_app(command)
                    or self.system.try_open(command)
                    or self.system.try_media(command)
                )
                if legacy:
                    if self._current_request_id is not None:
                        log_tool_completed(
                            "main.core",
                            "legacy_retry",
                            True,
                            0,
                            task_id=self._current_request_id,
                            execution_id=self._current_request_id,
                        )
                    return legacy
            if self._current_request_id is not None:
                log_tool_completed("main.core", "jarvis2_tool", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return tool_reply

        if self.ai_only:
            if self._current_request_id is not None:
                log_message("main.core", "AI-only mode, no tool match", level="info")
            return None

        meta = self.try_local_meta(command)
        if meta:
            if self._current_request_id is not None:
                log_tool_completed("main.core", "local_meta", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return meta

        quick_reply = self._quick_reply(command)
        if quick_reply:
            if self._current_request_id is not None:
                log_tool_completed("main.core", "quick_reply", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return quick_reply

        # Legacy local heuristics (v2 disabled or unmatched)
        quick = self.system.try_quick_action(command)
        if quick:
            if self._current_request_id is not None:
                log_tool_completed("main.core", "quick_action", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return quick

        direct = self.system.try_direct_app(command)
        if direct:
            if self._current_request_id is not None:
                log_tool_completed("main.core", "direct_app", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return direct

        media = self.system.try_media(command)
        if media:
            if self._current_request_id is not None:
                log_tool_completed("main.core", "media", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return media

        opened = self.system.try_open(command)
        if opened:
            if self._current_request_id is not None:
                log_tool_completed("main.core", "open", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return opened

        shell = self.system.try_shell(command)
        if shell:
            if self._current_request_id is not None:
                log_tool_completed("main.core", "shell", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return shell

        search = self.system.try_web_search(command)
        if search:
            if self._current_request_id is not None:
                log_tool_completed("main.core", "web_search", True, 0, task_id=self._current_request_id, execution_id=self._current_request_id)
            return search

        return None

    def _should_retry_local_action(self, command: str, tool_reply: str) -> bool:
        """True when FastBrain failed an open/media action that legacy may still handle."""
        lower_cmd = (command or "").lower()
        lower_reply = (tool_reply or "").lower()
        fail_markers = (
            "could not",
            "couldn't",
            "failed",
            "unable to",
            "not found",
            "timed out",
            "açılamadı",
            "acilamadi",
            "could not verify",
        )
        if not any(m in lower_reply for m in fail_markers):
            return False
        action_markers = (
            "aç",
            "ac ",
            " open",
            "open ",
            "launch",
            "başlat",
            "baslat",
            "çal",
            "cal ",
            "play",
            "spotify",
            "chrome",
            "safari",
            "youtube",
            "music",
            "müzik",
            "muzik",
        )
        return any(m in lower_cmd for m in action_markers)

    def _try_voice_confirmation(self, command: str) -> Optional[str]:
        """Resolve pending Level-3 confirm via evet/hayır without tool routing."""
        if self.os_v2 is None or not self.os_v2.confirmation.has_pending():
            return None
        from security.confirm_voice import classify_confirmation

        decision = classify_confirmation(command)
        if decision is None:
            return None
        approved = decision == "yes"
        self.os_v2.confirmation.resolve_latest(approved)
        if self.ui:
            self.ui.send_command_center()
        return "Confirmed." if approved else "Cancelled."

    def _intercept_confirmation_outside_worker(self, command: str) -> bool:
        """Used by voice loops so confirmations resolve while worker is blocked."""
        if self.os_v2 is None or not self.os_v2.confirmation.has_pending():
            return False
        from security.confirm_voice import classify_confirmation

        decision = classify_confirmation(command)
        if decision is None:
            return False
        approved = decision == "yes"
        self.os_v2.confirmation.resolve_latest(approved)
        msg = "Confirmed." if approved else "Cancelled."
        print(f"🔐 Confirm: {msg}")
        try:
            self.speaker.say(msg)
        except Exception:
            pass
        if self.ui:
            self.ui.send_response(command, msg)
            self.ui.send_command_center()
        return True

    def _try_jarvis2_tools(self, command: str) -> Optional[str]:
        if self.os_v2 is None:
            return self._try_jarvis2_diagnostics(command)
        turn = self.os_v2.handle_turn(command)
        if turn.handled:
            return turn.speech
        if turn.brain_needed:
            return None
        return turn.speech

    def _try_jarvis2_diagnostics(self, command: str) -> Optional[str]:
        """Fallback when core is disabled — only status phrases."""
        lower = command.lower().strip()
        triggers = (
            "jarvis status",
            "system status",
            "self diagnostics",
            "diagnostics",
            "core status",
        )
        if not any(t in lower for t in triggers):
            return None
        return "JARVIS 2.0 core is not loaded."

    def _run_command(self, command: str) -> None:
        if not self._processing.acquire(blocking=False):
            print(f"⏳ Still processing, skipped: {command}")
            return

        j = self.config.get("jarvis", {})
        v = self.config.get("voice", {})
        print(f"📢 Command: {command}")
        response = ""
        self.speaker.flush()
        self.listen_guard.set_processing(True)
        if self.ui:
            self.ui.send_listen_gate(
                not self._continuous_listening_enabled()
            )
        self._set_status("thinking", command)
        if self.ui:
            self.ui.broadcast("thinking", command)

        # Generate and set request ID for this turn
        request_id = uuid.uuid4().hex[:12]
        set_request_id(request_id)
        self._current_request_id = request_id

        try:
            if not command.strip():
                response = "I didn't catch that."
                self._emit_response(command, response)
                self.speaker.say(response)
            else:
                response = self.process_command(command)
                if response is None:
                    if self.speak_ack:
                        ack = self.narrator.instant_ack(command)
                        self._jarvis_speak(ack)
                        self._set_status("thinking", ack)
                    else:
                        self._set_status("thinking", "Processing…")
                    if not self.brain.is_ready():
                        self._set_status("thinking", "Neural core connecting…")
                        self.brain.wait_ready(
                            timeout=float(j.get("brain_start_timeout_sec", 15.0))
                        )
                    response = self.brain.think_with_narration(
                        command,
                        self._jarvis_speak,
                        work_update=lambda idx: self.narrator.work_update(
                            idx, command=command,
                        ),
                        on_complete=lambda result: self._on_task_complete(
                            command, result,
                        ),
                    )
                    if response and not self._is_timeout_placeholder(response):
                        self.brain.remember_turn(command, response)
                        if self.os_v2 is not None:
                            self.os_v2.ingest_conversation(command, response)
                    self._emit_response(command, response)
                    if (
                        response
                        and not self._is_timeout_placeholder(response)
                        and j.get("narrate", True)
                        and v.get("always_speak", True)
                    ):
                        # Safety net: brain may have spoken during think; dedupe skips repeats.
                        self._jarvis_speak(response)
                elif response == "SHUTDOWN_JARVIS":
                    self.speaker.say("Powering down.")
                    print("🤖 JARVIS: Powering down.\n")
                    raise KeyboardInterrupt
                else:
                    self._emit_response(command, response)
                    self.speaker.say(response)
        except KeyboardInterrupt:
            raise
        except Exception as err:
            # Never expose raw locale/thread internals to the user (English only).
            err_text = str(err)
            logger.exception("Command handling failed: %s", type(err).__name__)
            print(f"⚠️  Command handling failed: {type(err).__name__}: {err_text}")
            if "signal" in err_text.lower() and "main" in err_text.lower():
                response = (
                    "My apologies — a threading fault interrupted that action. "
                    "Please try the command again."
                )
            elif any(
                marker in err_text.lower()
                for marker in ("network", "connection", "cursor", "agent")
            ):
                response = (
                    "I couldn't reach the reasoning core for that request. "
                    "Local commands remain available."
                )
            else:
                response = (
                    "I couldn't complete that request because an internal "
                    "component failed. Local commands remain available."
                )
            self._set_status("error", "fault")
            self._emit_response(command, response)
            self.speaker.say(response)
        finally:
            clear_request_id()
            self._current_request_id = None
            self.listen_guard.set_processing(False)
            self._processing.release()

        if response == "SHUTDOWN_JARVIS":
            print("🤖 JARVIS: Powering down.\n")
            raise KeyboardInterrupt

        print(f"🤖 JARVIS: {response}\n")
        # Resume mic only after real TTS finishes (fixes one-shot listen)
        self._resume_listening_after_speech()
        self._set_status("idle", "Standing by — speak your command")

    def _is_timeout_placeholder(self, response: str) -> bool:
        """True when the reply is only a wait/fail placeholder, not a real answer."""
        if not response:
            return True
        lower = response.lower()
        markers = (
            "shall i keep trying",
            "say 'continue'",
            "timed out",
            "ran out of time",
            "exceeded my wait window",
            "took too long",
            "still working until it's complete",
            "finish in the background",
            "report back when finished",
        )
        return any(m in lower for m in markers)

    def _emit_response(self, command: str, response: str) -> None:
        if self.ui:
            self.ui.send_response(command, response)
        self._set_status("speaking", response)

    def _on_task_complete(self, command: str, response: str) -> None:
        """Called when a background task finishes after the initial timeout."""
        if not response:
            return
        self.brain.remember_turn(command, response)
        if self.os_v2 is not None:
            self.os_v2.ingest_conversation(command, response)
        self._emit_response(command, response)
        self._jarvis_speak(response)
        self._resume_listening_after_speech()
        self._set_status("idle", "Standing by — speak your command")
        print(f"🤖 JARVIS (background): {response}\n")

    def _command_worker(self) -> None:
        while True:
            command = self._command_queue.get()
            try:
                self._run_command(command)
            except KeyboardInterrupt:
                break
            except Exception as err:
                print(f"⚠️  Hata: {err}")
                self._set_status("error", str(err))

    def _ui_command_bridge(self) -> None:
        """Consume HUD commands when the native microphone loop is active."""
        if self.ui is None:
            return
        while True:
            try:
                command = self.ui.wait_for_command(timeout=0.3)
                if not command:
                    continue
                if self._intercept_confirmation_outside_worker(command):
                    continue
                if self.try_stop_speech(command) is not None:
                    print("🔇 Speech interrupted from HUD")
                    continue
                control = self.try_listen_control(command)
                if control:
                    self._emit_response(command, control)
                    self.speaker.say(control)
                    continue
                if self._should_accept_voice_command(command):
                    self._enqueue_command(command, source="hud")
            except KeyboardInterrupt:
                return
            except Exception as err:
                print(f"⚠️  HUD command bridge: {err}")
                time.sleep(0.5)

    def _native_listen_command(self) -> Optional[str]:
        capture_epoch = self._tts_gate_epoch
        if self.listen_guard.blocked:
            time.sleep(0.05)
            return None
        require_wake = self.config.get("ui", {}).get("require_wake_word", False)
        if require_wake:
            command = self.listener.listen_for_wake_and_command()
            return command if capture_epoch == self._tts_gate_epoch else None
        text = self.listener.listen_once()
        if capture_epoch != self._tts_gate_epoch:
            return None
        if not text:
            return None
        self._on_heard(text)
        command = self.listener.extract_wake_command(text)
        if not command:
            command = text.strip()
        return command or None

    def handle_desktop_voice_loop(self) -> None:
        """Desktop HUD — native macOS mic (Web Speech API blocked in pywebview)."""
        if not self.ui:
            self.handle_native_voice_loop()
            return
        self.listener._ensure_listener()
        self.listener.calibrate()
        listener_ready = (ROOT / "voice" / "macos_listen").exists() or self.listener._use_pyaudio
        if not listener_ready:
            print("⚠️  Native mic unavailable.")
            print("   Fix Swift tools: sudo xcode-select --install")
            print("   Or use PyAudio fallback (pip installs on next ./start.sh)")
            self.ui.broadcast(
                "error",
                "Mic unavailable — grant Terminal mic access or run: pip install PyAudio",
            )
            self.handle_ui_voice_loop()
            return

        self.ui.wait_ready()
        print("🎙️  Desktop — native macOS microphone active")
        self._set_status("idle", "Standing by — speak your command")

        worker = threading.Thread(target=self._command_worker, daemon=True)
        worker.start()

        paused_detail = 'Mic paused — say "listen again" or press LISTEN'
        mic_failures = 0

        while True:
            try:
                if self._listening_enabled:
                    self._set_status("listening", "Listening, sir…")
                command = self._native_listen_command()
                if not command:
                    mic_failures += 1
                    if mic_failures == 8:
                        self.ui.broadcast(
                            "error",
                            "Mic not responding — check System Settings → Privacy → Microphone for JARVIS / Terminal",
                        )
                        print(
                            "⚠️  Mikrofon yanıt vermiyor. "
                            "Sistem Ayarları → Gizlilik ve Güvenlik → Mikrofon iznini kontrol edin."
                        )
                    if self._listening_enabled:
                        self._set_status("idle", "Standing by — speak your command")
                    continue

                mic_failures = 0

                if not self._listening_enabled:
                    # Do not treat JARVIS's own mute confirmation as a real
                    # "resume" command while TTS is still playing.
                    if not self.listen_guard.should_accept_transcript(command):
                        continue
                    control = self.try_listen_control(command)
                    if control:
                        self._emit_response(command, control)
                        self.speaker.say(control)
                    self._set_status("idle", paused_detail)
                    continue

                if self._intercept_confirmation_outside_worker(command):
                    continue

                # Interrupt TTS immediately even while worker is busy
                if self.try_stop_speech(command) is not None:
                    print("🔇 Speech interrupted")
                    continue

                control = self.try_listen_control(command)
                if control:
                    self._emit_response(command, control)
                    self.speaker.say(control)
                    continue

                if not self._should_accept_voice_command(command):
                    # Drop STT echo / commands while TTS or cooldown is active
                    continue

                self._enqueue_command(command, source="native")
            except KeyboardInterrupt:
                break
            except Exception as err:
                print(f"⚠️  Error: {err}")
                self._set_status("error", str(err))
                time.sleep(1)

    def handle_ui_voice_loop(self) -> None:
        """Browser microphone via Web Speech API — always-on listening."""
        if not self.ui:
            self.handle_text_loop()
            return

        self.ui.wait_ready()
        print("🎙️  Continuous listening — speak naturally")
        print("   Examples: What time is it · Open Spotify · YouTube NBC\n")
        self._set_status("idle", "Standing by — speak your command")

        worker = threading.Thread(target=self._command_worker, daemon=True)
        worker.start()

        while True:
            try:
                command = self.ui.wait_for_command(timeout=0.3)
                if command:
                    if self._intercept_confirmation_outside_worker(command):
                        continue
                    if self.try_stop_speech(command) is not None:
                        print("🔇 Speech interrupted")
                        continue

                    control = self.try_listen_control(command)
                    if control:
                        self._emit_response(command, control)
                        self.speaker.say(control)
                        continue

                    if not self._should_accept_voice_command(command):
                        continue

                    self._enqueue_command(command, source="hud")
            except KeyboardInterrupt:
                break

    def handle_native_voice_loop(self) -> None:
        listener_ready = (ROOT / "voice" / "macos_listen").exists() or self.listener._use_pyaudio
        if not listener_ready:
            self.handle_ui_voice_loop()
            return

        require_wake = self.config.get("ui", {}).get("require_wake_word", False)
        if require_wake:
            print("👂 Native listening — say 'Jarvis'...")
            self._set_status("idle", "Awaiting wake word")
        else:
            print("👂 Native listening — speak naturally")
            self._set_status("idle", "Standing by — speak your command")

        paused_detail = 'Mic paused — say "listen again" or press LISTEN'
        worker = threading.Thread(target=self._command_worker, daemon=True)
        worker.start()
        if self.ui:
            threading.Thread(target=self._ui_command_bridge, daemon=True).start()

        while True:
            try:
                command = self._native_listen_command()
                if not command:
                    continue
                if not self._listening_enabled:
                    # Do not treat JARVIS's own mute confirmation as a real
                    # "resume" command while TTS is still playing.
                    if not self.listen_guard.should_accept_transcript(command):
                        continue
                    control = self.try_listen_control(command)
                    if control:
                        self._emit_response(command, control)
                        self.speaker.say(control)
                    self._set_status("idle", paused_detail)
                    continue
                if self._intercept_confirmation_outside_worker(command):
                    continue
                if self.try_stop_speech(command) is not None:
                    print("🔇 Speech interrupted")
                    continue

                if not self._should_accept_voice_command(command):
                    continue

                self._enqueue_command(command, source="native")
            except KeyboardInterrupt:
                break
            except Exception as err:
                print(f"⚠️  Hata: {err}")
                self._set_status("error", str(err))
                time.sleep(1)

    def handle_text_loop(self) -> None:
        print("💬 Metin modu — 'quit' ile çıkış")
        while True:
            try:
                user_input = input(f"{self.brain.user_name}> ").strip()
                if user_input.lower() in ("quit", "exit", "q", "çık"):
                    break
                if not user_input:
                    continue
                response = self.process_command(user_input)
                if response is None:
                    response = self.brain.think_with_narration(
                        user_input, self.speaker.say, self.narrator.work_update,
                    )
                print(f"JARVIS: {response}\n")
                self.speaker.say(response)
            except (KeyboardInterrupt, EOFError):
                break


def start_ui_server(
    core: JarvisCore,
    port: int,
    ui_config: dict,
    *,
    open_browser: bool = True,
    desktop_mode: bool = False,
    native_mic: bool = False,
) -> None:
    from ui.server import JarvisUI, lan_ip, resolve_bind_host

    interval = float(ui_config.get("telemetry_interval", 5 if desktop_mode else 2))
    cc_interval = float(ui_config.get("command_center_interval", 5))
    mic_cfg = {
        **ui_config,
        "listen_language": core.config.get("voice", {}).get("listen_language", "tr-TR"),
        "self_listen_guard": core.config.get("voice", {}).get("self_listen_guard", True),
        "post_tts_cooldown_ms": core.config.get("voice", {}).get("post_tts_cooldown_ms", 220),
    }

    def _data_provider() -> dict:
        if core.os_v2 is None:
            return {"available": False, "reason": "JARVIS 2.0 core not loaded"}
        return core.os_v2.command_center()

    def _on_confirm(confirm_id: str, approved: bool) -> bool:
        if core.os_v2 is None:
            return False
        return core.os_v2.confirmation.resolve(confirm_id, approved)

    core.ui = JarvisUI(
        port=port,
        mic_config=mic_cfg,
        jarvis_config=core.config.get("jarvis", {}),
        open_browser=open_browser,
        desktop_mode=desktop_mode,
        native_mic=native_mic,
        voice_identity_enabled=core.speaker_verifier is not None,
        telemetry_interval=interval,
        command_center_interval=cc_interval,
        on_confirm=_on_confirm,
        data_provider=_data_provider,
        telemetry_supplier=lambda: get_telemetry(
            core.config.get("jarvis", {}),
            brain_model=core.brain.model,
            brain_ready=core.brain.is_ready(),
        ),
        os_core=core.os_v2,
        command_enqueue=lambda text: core._enqueue_command(text, source="rest"),
        host=str(ui_config.get("host", "127.0.0.1")),
    )
    core.ui.on_mic_control = core._handle_mic_control
    core.ui.send_mic_state(core._listening_enabled)

    def _on_listen_gate(blocked: bool) -> None:
        if core.ui:
            core.ui.send_listen_gate(blocked)

    core.listen_guard.add_listener(_on_listen_gate)
    core.ui.set_voice_accept_fn(core._should_accept_voice_command)

    if core.os_v2 is not None:
        def _level_notify(level: int, tool: str, args: dict) -> None:
            detail = str(args)[:120]
            if core.ui:
                core.ui.send_permission_notice(level=level, tool=tool, detail=detail)
                if level >= 2:
                    core.ui.broadcast(
                        "thinking",
                        f"L{level} {tool}",
                    )

        def _confirm_pending(pending) -> None:
            if core.ui:
                core.ui.send_confirm_request(pending.to_dict())
                core.ui.send_command_center()

        core.os_v2.set_ui_hooks(
            on_level_notify=_level_notify,
            on_confirm_pending=_confirm_pending,
        )

        def _thinking_trace(payload: dict) -> None:
            label = str(payload.get("label") or payload.get("message") or "")
            if core.ui and label:
                core.ui.broadcast(
                    "thinking",
                    label,
                    thinking_trace=label,
                    thinking_phase=str(payload.get("phase") or ""),
                )

        core.os_v2.set_thinking_callback(_thinking_trace)

    thread = threading.Thread(target=core.ui.run, daemon=True)
    thread.start()
    core.ui.wait_ready()
    if desktop_mode:
        print("🖥️  JARVIS Desktop HUD hazır")
    else:
        bind = resolve_bind_host(str(ui_config.get("host", "127.0.0.1")))
        print(f"🖥️  HUD: http://localhost:{port}")
        if bind == "0.0.0.0":
            phone_ip = lan_ip()
            if phone_ip:
                print(f"📱  iPhone / iPad (same Wi‑Fi): http://{phone_ip}:{port}")
                print(f"📱  Mobile app (install): http://{phone_ip}:{port}/mobile")
                print(f"📱  QR / copy link: http://{phone_ip}:{port}/connect")


def main() -> None:
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. — Cursor-powered voice assistant")
    parser.add_argument("--text", action="store_true", help="Terminal text mode")
    parser.add_argument("--native-voice", action="store_true", help="Native mic (needs Xcode)")
    parser.add_argument("--no-ui", action="store_true", help="Disable Iron Man HUD")
    parser.add_argument("--browser", action="store_true", help="Open HUD in browser instead of desktop app")
    parser.add_argument("--ui-only", action="store_true", help="Launch HUD only")
    parser.add_argument(
        "--enroll-voice",
        action="store_true",
        help="Guided local enrollment for the trusted speaker",
    )
    args = parser.parse_args()

    config = load_config()
    ui_cfg = config.get("ui", {})
    ui_mode = ui_cfg.get("mode", "browser")
    use_desktop = (
        ui_cfg.get("enabled", True)
        and not args.no_ui
        and not args.browser
        and ui_mode == "desktop"
        and not args.ui_only
    )

    if args.ui_only:
        from ui.server import JarvisUI, lan_ip, resolve_bind_host

        desktop = ui_cfg.get("mode", "desktop") == "desktop"
        ui = JarvisUI(
            port=ui_cfg["port"],
            mic_config=ui_cfg,
            jarvis_config=config.get("jarvis", {}),
            open_browser=not desktop,
            desktop_mode=desktop,
            telemetry_interval=float(ui_cfg.get("telemetry_interval", 5)),
            host=str(ui_cfg.get("host", "127.0.0.1")),
        )
        if desktop:
            import webview

            thread = threading.Thread(target=ui.run, daemon=True)
            thread.start()
            ui.wait_ready()
            webview.create_window(
                "J.A.R.V.I.S. — Stark OS",
                f"http://127.0.0.1:{ui_cfg['port']}",
                width=1280,
                height=820,
                background_color="#020810",
            )
            webview.start(gui="cocoa")
        else:
            ui.run()
        return

    core = JarvisCore(config)

    if args.enroll_voice:
        try:
            core.enroll_voice_profile()
        finally:
            core.shutdown()
        return

    if ui_cfg.get("enabled", True) and not args.no_ui:
        start_ui_server(
            core,
            ui_cfg["port"],
            ui_cfg,
            open_browser=not use_desktop,
            desktop_mode=use_desktop,
            native_mic=args.native_voice,
        )

    try:
        if use_desktop:
            from ui.desktop import run_desktop_window

            run_desktop_window(
                core,
                port=ui_cfg["port"],
                width=int(ui_cfg.get("window_width", 1280)),
                height=int(ui_cfg.get("window_height", 820)),
            )
        else:
            core.boot()
            if args.text:
                core.handle_text_loop()
            elif args.native_voice or core.speaker_verifier is not None:
                core.handle_native_voice_loop()
            else:
                core.handle_ui_voice_loop()
    finally:
        core.shutdown()


if __name__ == "__main__":
    main()