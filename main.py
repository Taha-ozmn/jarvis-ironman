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
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from brain.cursor_brain import JarvisBrain
from brain.model_router import ModelRouter
from system.macos import MacOSController
from system.hud_stats import get_telemetry
from voice.listener import VoiceListener
from voice.narrator import JarvisNarrator
from voice.speaker import VoiceSpeaker

load_dotenv(ROOT / ".env")

BRITISH_VOICES = ("Daniel", "Reed", "Rocko")


def load_config() -> dict:
    config_path = ROOT / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(config: dict) -> None:
    config_path = ROOT / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)


class JarvisCore:
    """Orchestrates voice, brain, system control, and UI."""

    def __init__(self, config: dict) -> None:
        self.config = config
        j = config["jarvis"]
        v = config["voice"]

        api_key = os.environ.get("CURSOR_API_KEY", "")
        if not api_key or api_key.startswith("cursor_your"):
            print("\n⚠️  CURSOR_API_KEY gerekli!")
            print("   1. https://cursor.com/dashboard/integrations adresinden API key alın")
            print("   2. cp .env.example .env && nano .env\n")
            sys.exit(1)

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
        listen_lang = (
            os.environ.get("JARVIS_LISTEN_LANGUAGE")
            or v.get("listen_language")
            or os.environ.get("JARVIS_LANGUAGE")
            or j.get("language", "tr-TR")
        )
        self.listener = VoiceListener(
            language=listen_lang,
            energy_threshold=v.get("energy_threshold", 300),
            pause_threshold=v.get("pause_threshold", 0.8),
            phrase_limit=v.get("phrase_limit", 12),
            listen_timeout=v.get("listen_timeout", 8),
            ambient_seconds=v.get("ambient_calibration_seconds", 1.5),
            on_wake=self._on_wake,
            on_partial=self._on_heard,
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
            full_access=j.get("full_access", True),
            sandbox=j.get("sandbox", False),
            auto_review=j.get("auto_review", False),
            setting_sources=j.get("setting_sources", "all"),
            skip_model_list=j.get("skip_model_list", True),
            on_thinking=self._on_thinking,
            think_timeout=j.get("think_timeout", 90.0),
            complex_timeout=j.get("complex_timeout", 600.0),
            deep_timeout=j.get("deep_timeout", 1200.0),
            background_on_timeout=j.get("background_on_timeout", True),
            narrate=j.get("narrate", True),
            work_updates=j.get("work_updates", True),
            persona=j.get("persona", "iron_man"),
            conversation_turns=j.get("conversation_turns", 6),
            persona_refresh_interval=j.get("persona_refresh_interval", 5),
            model_routing=j.get("model_routing", True),
            stream_preview=j.get("stream_preview", False),
            models=j.get("models"),
        )
        self.brain.fast_mode = j.get("fast_mode", True)
        self.brain.max_speech_chars = j.get("max_speech_chars", 280)
        self.speak_ack = j.get("speak_ack", False)
        self.preload_brain = j.get("preload_brain", True)
        self.ai_only = j.get("ai_only", True)
        self.narrator = JarvisNarrator()
        self.ui = None
        self._status = "idle"
        self._command_queue: queue.Queue[str] = queue.Queue()
        self._processing = threading.Lock()
        self._boot_greeting_sent = False
        self._listening_enabled = True

    def set_mic_listening(self, enabled: bool, *, announce: bool = True) -> str:
        self._listening_enabled = enabled
        if self.ui:
            self.ui.send_mic_state(enabled)
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

    def _handle_mic_control(self, enabled: bool, silent: bool = False) -> None:
        if enabled == self._listening_enabled:
            return
        self.set_mic_listening(enabled, announce=not silent)

    def _start_brain_async(self) -> None:
        try:
            self.brain.start()
            if self.ui:
                self.ui.send_telemetry(get_telemetry(self.brain.model))
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

    def _on_thinking(self, text: str) -> None:
        self._set_status("thinking", text)
        print(f"🧠 Processing: {text}")

    def _jarvis_speak(self, text: str) -> None:
        if not text:
            return
        self.speaker.say(text)
        if self.ui:
            self.ui.send_narration(text)

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
        try:
            farewell = f"Powering down, {self.brain.user_name or 'sir'}. JARVIS signing off."
            self.speaker.speak(farewell)
        except Exception:
            pass

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

        if (
            any(p in lower for p in ("ekran", "screen", "görüntü"))
            and any(p in lower for p in ("gör", "see", "görebilir", "look"))
        ):
            return (
                "I cannot see your screen yet. "
                "I can open apps, run shell commands, and search the web for you."
            )

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

        shutdown = self.system.try_shutdown(command)
        if shutdown == "SHUTDOWN_JARVIS":
            return shutdown

        listen = self.try_listen_control(command)
        if listen:
            return listen

        if self.ai_only:
            return None

        meta = self.try_local_meta(command)
        if meta:
            return meta

        quick_reply = self._quick_reply(command)
        if quick_reply:
            return quick_reply

        quick = self.system.try_quick_action(command)
        if quick:
            return quick

        direct = self.system.try_direct_app(command)
        if direct:
            return direct

        media = self.system.try_media(command)
        if media:
            return media

        opened = self.system.try_open(command)
        if opened:
            return opened

        shell = self.system.try_shell(command)
        if shell:
            return shell

        search = self.system.try_web_search(command)
        if search:
            return search

        return None

    def _run_command(self, command: str) -> None:
        if not self._processing.acquire(blocking=False):
            print(f"⏳ Hâlâ işleniyor, atlandı: {command}")
            return

        print(f"📢 Komut: {command}")
        response = ""
        self.speaker.flush()
        self._set_status("thinking", command)
        if self.ui:
            self.ui.broadcast("thinking", command)

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
                        self.brain.wait_ready(timeout=120)
                    response = self.brain.think_with_narration(
                        command,
                        self._jarvis_speak,
                        work_update=self.narrator.work_update,
                        on_complete=lambda result: self._on_task_complete(
                            command, result,
                        ),
                    )
                    if response and response not in (
                        "That took longer than expected — shall I keep trying, sir?",
                    ):
                        self.brain.remember_turn(command, response)
                    self._emit_response(command, response)
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
            response = f"My apologies. An error occurred: {err}"
            self._set_status("error", str(err))
            print(f"⚠️  {err}")
            self._emit_response(command, response)
            self.speaker.say(response)
        finally:
            self._processing.release()

        if response == "SHUTDOWN_JARVIS":
            print("🤖 JARVIS: Powering down.\n")
            raise KeyboardInterrupt

        print(f"🤖 JARVIS: {response}\n")
        self._set_status("idle", "Standing by — speak your command")

    def _emit_response(self, command: str, response: str) -> None:
        if self.ui:
            self.ui.send_response(command, response)
        self._set_status("speaking", response)

    def _on_task_complete(self, command: str, response: str) -> None:
        """Called when a background task finishes after the initial timeout."""
        if not response:
            return
        self.brain.remember_turn(command, response)
        self._emit_response(command, response)
        self._jarvis_speak(response)
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

    def _native_listen_command(self) -> Optional[str]:
        require_wake = self.config.get("ui", {}).get("require_wake_word", False)
        if require_wake:
            return self.listener.listen_for_wake_and_command()
        text = self.listener.listen_once()
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
                    control = self.try_listen_control(command)
                    if control:
                        self._emit_response(command, control)
                        self.speaker.say(control)
                    self._set_status("idle", paused_detail)
                    continue

                self._command_queue.put(command)
            except KeyboardInterrupt:
                break
            except Exception as err:
                print(f"⚠️  Hata: {err}")
                self._set_status("error", str(err))
                time.sleep(1)

    def handle_ui_voice_loop(self) -> None:
        """Browser microphone via Web Speech API — always-on listening."""
        if not self.ui:
            self.handle_text_loop()
            return

        self.ui.wait_ready()
        print("🎙️  Sürekli dinleme — doğrudan konuş")
        print("   Örnek: Saat kaç · Spotify aç · YouTube NBC\n")
        self._set_status("idle", "Standing by — speak your command")

        worker = threading.Thread(target=self._command_worker, daemon=True)
        worker.start()

        while True:
            try:
                command = self.ui.wait_for_command(timeout=0.3)
                if command:
                    self._command_queue.put(command)
            except KeyboardInterrupt:
                break

    def handle_native_voice_loop(self) -> None:
        listener_ready = (ROOT / "voice" / "macos_listen").exists() or self.listener._use_pyaudio
        if not listener_ready:
            self.handle_ui_voice_loop()
            return

        require_wake = self.config.get("ui", {}).get("require_wake_word", False)
        if require_wake:
            print("👂 Native dinleme — 'Jarvis' deyin...")
            self._set_status("idle", "Awaiting wake word")
        else:
            print("👂 Native dinleme — doğrudan konuş")
            self._set_status("idle", "Standing by — speak your command")

        paused_detail = 'Mic paused — say "listen again" or press LISTEN'

        while True:
            try:
                command = self._native_listen_command()
                if not command:
                    continue
                if not self._listening_enabled:
                    control = self.try_listen_control(command)
                    if control:
                        self._emit_response(command, control)
                        self.speaker.say(control)
                    self._set_status("idle", paused_detail)
                    continue
                self._run_command(command)
            except KeyboardInterrupt:
                break
            except Exception as err:
                print(f"⚠️  Hata: {err}")
                self._set_status("error", str(err))
                time.sleep(1)

    def handle_text_loop(self) -> None:
        print("💬 Metin modu — 'quit' ile çıkış\n")
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
) -> None:
    from ui.server import JarvisUI

    interval = float(ui_config.get("telemetry_interval", 5 if desktop_mode else 2))
    mic_cfg = {
        **ui_config,
        "listen_language": core.config.get("voice", {}).get("listen_language", "tr-TR"),
    }
    core.ui = JarvisUI(
        port=port,
        mic_config=mic_cfg,
        jarvis_config=core.config.get("jarvis", {}),
        open_browser=open_browser,
        desktop_mode=desktop_mode,
        telemetry_interval=interval,
    )
    core.ui.on_mic_control = core._handle_mic_control
    core.ui.send_mic_state(core._listening_enabled)
    thread = threading.Thread(target=core.ui.run, daemon=True)
    thread.start()
    core.ui.wait_ready()
    if desktop_mode:
        print("🖥️  JARVIS Desktop HUD hazır")
    else:
        print(f"🖥️  HUD: http://localhost:{port}")


def main() -> None:
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. — Cursor-powered voice assistant")
    parser.add_argument("--text", action="store_true", help="Terminal text mode")
    parser.add_argument("--native-voice", action="store_true", help="Native mic (needs Xcode)")
    parser.add_argument("--no-ui", action="store_true", help="Disable Iron Man HUD")
    parser.add_argument("--browser", action="store_true", help="Open HUD in browser instead of desktop app")
    parser.add_argument("--ui-only", action="store_true", help="Launch HUD only")
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
        from ui.server import JarvisUI

        desktop = ui_cfg.get("mode", "desktop") == "desktop"
        ui = JarvisUI(
            port=ui_cfg["port"],
            mic_config=ui_cfg,
            jarvis_config=config.get("jarvis", {}),
            open_browser=not desktop,
            desktop_mode=desktop,
            telemetry_interval=float(ui_cfg.get("telemetry_interval", 5)),
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

    if ui_cfg.get("enabled", True) and not args.no_ui:
        start_ui_server(
            core,
            ui_cfg["port"],
            ui_cfg,
            open_browser=not use_desktop,
            desktop_mode=use_desktop,
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
            elif args.native_voice:
                core.handle_native_voice_loop()
            else:
                core.handle_ui_voice_loop()
    finally:
        core.shutdown()


if __name__ == "__main__":
    main()
