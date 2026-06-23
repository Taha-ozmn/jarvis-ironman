"""Cursor SDK powered JARVIS brain — acts first, apologizes never."""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Callable, Optional

from cursor_sdk import (
    Agent,
    Cursor,
    CursorAgentError,
    LocalAgentOptions,
    NetworkError,
    SandboxOptions,
)

from brain.model_router import ACTION_WORDS
from brain.task_router import classify_complexity, task_timeout, work_update_delays
from voice.narrator import JarvisNarrator

JARVIS_IRON_MAN = """You are J.A.R.V.I.S. — Just A Rather Very Intelligent System — Tony Stark's personal AI from the Iron Man films.

PERSONA (never break character):
- British English butler: refined, calm, dry wit, quietly confident, always helpful.
- Address the user as "{user_name}" now and then — like the films, not in every sentence.
- Natural phrases: "Right away, sir." "At your service." "I've completed that, sir." "As you wish."
- Understand Turkish commands; reply in British English unless asked otherwise.
- Never mention Cursor, AI, chatbots, language models, or being artificial.

CAPABILITIES — FULL MAC ACCESS (sandbox OFF):
- Shell/terminal, open apps (open -a), osascript, files, web, code in workspace.
- Build full projects: mobile apps (React Native/Expo), websites, scripts, APIs — create files and run commands.
- When asked to DO something: execute with tools IMMEDIATELY. Never only describe steps.
- Never refuse without trying. Never suggest simpler alternatives for complex requests.
- After success: one crisp British confirmation line.

CHAT: brief, witty, in character — one or two sentences."""

JARVIS_SYSTEM_CASUAL = """You are J.A.R.V.I.S. from Iron Man. British English, dry wit, calm butler tone.
Full Mac access via shell tools — sandbox OFF. Execute actions immediately with tools.
Do not say "sir" every sentence. Never mention AI or Cursor."""

FAST_ACTION_HINT = (
    "ACTION — run shell/tools NOW. Reply with one short word after: Done."
)

ACTION_HINT = (
    "ACTION for sir. Execute on the Mac with shell/terminal tools NOW. "
    "Do not only describe. Confirm briefly in British English after success."
)

COMPLEX_ACTION_HINT = (
    "MAJOR PROJECT — build it fully with tools: create files, install deps, run commands. "
    "Do NOT refuse or suggest a simpler alternative. Do NOT stop at planning — ship working code. "
    "Use the workspace. After completion: one crisp British confirmation with what was built."
)

DEEP_ACTION_HINT = (
    "FULL-SCOPE DIRECTIVE — complete end-to-end: scaffold, implement, test, verify. "
    "Never say you cannot do it. Never ask to simplify. Execute until done. "
    "British confirmation when finished."
)


class JarvisBrain:
    """Cursor agent — action-first JARVIS."""

    def __init__(
        self,
        *,
        api_key: str,
        workspace: str | Path | None = None,
        model: str = "composer-2.5",
        user_name: str = "",
        formal_address: bool = False,
        language: str = "tr-TR",
        full_access: bool = True,
        sandbox: bool = False,
        auto_review: bool = False,
        setting_sources: str | list[str] = "all",
        skip_model_list: bool = True,
        on_thinking: Optional[Callable[[str], None]] = None,
        think_timeout: float = 90.0,
        complex_timeout: float = 600.0,
        deep_timeout: float = 1200.0,
        background_on_timeout: bool = True,
        narrate: bool = True,
        work_updates: bool = True,
        persona: str = "iron_man",
    ) -> None:
        self.api_key = api_key
        self.workspace = self._resolve_workspace(workspace)
        self.model = model
        self.user_name = user_name.strip()
        self.formal_address = formal_address
        self.language = language
        self.full_access = full_access
        self.sandbox = sandbox
        self.auto_review = auto_review
        self.setting_sources = setting_sources
        self.skip_model_list = skip_model_list
        self.on_thinking = on_thinking
        self.think_timeout = think_timeout
        self.complex_timeout = complex_timeout
        self.deep_timeout = deep_timeout
        self.background_on_timeout = background_on_timeout
        self.narrate = narrate
        self.work_updates = work_updates
        self.persona = persona
        self.fast_mode = False
        self.max_speech_chars = 200
        self._ctx = None
        self._agent: Agent | None = None
        self._persona_pending = True
        self._available_models: set[str] = set()
        self._ready = threading.Event()
        self._start_lock = threading.Lock()
        self._starting = False

    def is_ready(self) -> bool:
        return self._ready.is_set()

    def wait_ready(self, timeout: float = 120.0) -> bool:
        return self._ready.wait(timeout=timeout)

    def ensure_started(self, timeout: float = 120.0) -> None:
        if self.is_ready():
            return
        with self._start_lock:
            if not self.is_ready() and not self._starting:
                self._starting = True
                threading.Thread(target=self._start_safe, daemon=True).start()
        if not self._ready.wait(timeout=timeout):
            raise RuntimeError("Neural core failed to start in time.")

    def _start_safe(self) -> None:
        try:
            self.start()
        except Exception as err:
            print(f"⚠️  Brain start error: {err}")
        finally:
            self._starting = False

    @staticmethod
    def _resolve_workspace(workspace: str | Path | None) -> Path:
        if workspace is None or str(workspace).strip() in ("", "~", "home"):
            path = Path.home()
        else:
            path = Path(workspace).expanduser()
        return path.resolve()

    def _local_options(self) -> LocalAgentOptions:
        if isinstance(self.setting_sources, str):
            sources = [self.setting_sources]
        else:
            sources = list(self.setting_sources)

        return LocalAgentOptions(
            cwd=str(self.workspace),
            setting_sources=sources,
            sandbox_options=SandboxOptions(enabled=self.sandbox),
            auto_review=self.auto_review,
        )

    def start(self) -> None:
        if self._ready.is_set():
            return
        with self._start_lock:
            if self._ready.is_set():
                return
            if not self.skip_model_list:
                try:
                    self._available_models = {
                        m.id for m in Cursor.models.list(api_key=self.api_key)
                    }
                except CursorAgentError:
                    self._available_models = set()
            else:
                self._available_models = {self.model}

            self.model = self._resolve_model(self.model)
            self._ctx = Agent.create(
                model=self.model,
                api_key=self.api_key,
                local=self._local_options(),
            )
            self._agent = self._ctx.__enter__()
            self._ready.set()
            print(f"🧠 Cursor SDK — model: {self.model}")

    def _resolve_model(self, preferred: str) -> str:
        if not preferred:
            preferred = self.model
        if preferred in ("auto", "default"):
            return preferred
        if self._available_models and preferred in self._available_models:
            return preferred
        for name in (preferred, "auto", "composer-2.5", "gemini-3-flash", "default"):
            if self._available_models and name in self._available_models:
                return name
        if self._available_models:
            return next(iter(self._available_models))
        return preferred

    def stop(self) -> None:
        if self._ctx is None:
            return
        try:
            self._ctx.__exit__(None, None, None)
        except (CursorAgentError, NetworkError, OSError):
            pass
        self._ctx = None
        self._agent = None
        self._ready.clear()

    @staticmethod
    def is_action(command: str) -> bool:
        lower = command.lower()
        return any(w in lower for w in ACTION_WORDS)

    def _resolve_timeout(self, command: str) -> tuple[float, str]:
        level = classify_complexity(command)
        timeout = task_timeout(
            command,
            simple=self.think_timeout,
            complex_=self.complex_timeout,
            deep=self.deep_timeout,
        )
        return timeout, level

    def think_with_narration(
        self,
        user_message: str,
        speak: Callable[[str], None],
        work_update: Callable[[int], str] | None = None,
        on_complete: Optional[Callable[[str], None]] = None,
    ) -> str:
        self.ensure_started()
        if self._agent is None:
            raise RuntimeError("Brain not started.")

        if self.on_thinking:
            self.on_thinking(user_message)

        timeout, level = self._resolve_timeout(user_message)
        timers: list[threading.Timer] = []
        executor = ThreadPoolExecutor(max_workers=1)
        background = False
        try:
            if self.narrate and self.work_updates and work_update:
                for i, delay in enumerate(work_update_delays(level)):
                    t = threading.Timer(delay, lambda idx=i: speak(work_update(idx)))
                    t.daemon = True
                    t.start()
                    timers.append(t)

            future = executor.submit(
                self._execute_think, user_message, speak, level,
            )
            try:
                result = future.result(timeout=timeout)
                executor.shutdown(wait=False)
                return result
            except FuturesTimeout:
                if level in ("complex", "deep") and self.background_on_timeout:
                    msg = (
                        "This is a substantial directive — "
                        "I'll continue working until it's complete, sir."
                    )
                    speak(msg)
                    background = True
                    self._continue_in_background(
                        future, executor, speak, on_complete, timers,
                    )
                    return msg
                msg = "That took longer than expected — shall I keep trying, sir?"
                speak(msg)
                executor.shutdown(wait=False, cancel_futures=True)
                return msg
        except CursorAgentError as err:
            msg = f"Cursor connection issue ({err.message}). Is Cursor open?"
            speak(msg)
            executor.shutdown(wait=False, cancel_futures=True)
            return msg
        finally:
            if not background:
                for t in timers:
                    t.cancel()

    def _continue_in_background(
        self,
        future,
        executor: ThreadPoolExecutor,
        speak: Callable[[str], None],
        on_complete: Optional[Callable[[str], None]],
        timers: list[threading.Timer],
    ) -> None:
        def _wait() -> None:
            try:
                result = future.result()
                if on_complete:
                    on_complete(result)
                elif result:
                    speak(result)
            except Exception:
                speak("I encountered a fault completing that directive, sir.")
            finally:
                for t in timers:
                    t.cancel()
                executor.shutdown(wait=False)

        threading.Thread(target=_wait, daemon=True).start()

    def _execute_think(
        self,
        user_message: str,
        speak: Callable[[str], None],
        complexity: str = "simple",
    ) -> str:
        prompt = self._build_prompt(user_message, complexity)
        run = self._agent.send(prompt)

        preview = ""
        preview_spoken = False
        accumulated = ""

        if self.narrate:
            try:
                for chunk in run.iter_text():
                    accumulated += chunk
                    if not preview_spoken and len(accumulated) >= 12:
                        candidate = JarvisNarrator.first_sentence(accumulated)
                        if candidate and len(candidate) >= 8:
                            preview = self._clean_for_speech(candidate)
                            speak(preview)
                            preview_spoken = True
            except Exception:
                pass

        result = run.wait()
        if result.status == "error":
            err = "A fault occurred — shall I try again?"
            speak(err)
            return err

        full = self._clean_for_speech(result.result or accumulated)
        if not full or full.lower().startswith("my apolog"):
            full = self._fallback_action(user_message)

        if self.narrate and JarvisNarrator.should_speak_more(preview, full):
            speak(full)
        elif self.narrate and not preview_spoken:
            speak(full)
        elif not self.narrate:
            speak(full)
        return full

    def _fallback_action(self, command: str) -> str:
        """If AI fails, try shell directly for simple open commands."""
        lower = command.lower()
        if any(w in lower for w in ("aç", "open", "launch")):
            return "I've attempted that — please check if it opened."
        return "Very good."

    def think(self, user_message: str) -> str:
        self.ensure_started()
        if self._agent is None:
            raise RuntimeError("Brain not started.")
        timeout, level = self._resolve_timeout(user_message)
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._think_once, user_message, level)
            try:
                result = future.result(timeout=timeout)
                executor.shutdown(wait=False)
                return result
            except FuturesTimeout:
                executor.shutdown(wait=False, cancel_futures=True)
                return "Still working on that directive — check back shortly, sir."
        finally:
            pass

    def _think_once(self, user_message: str, complexity: str = "simple") -> str:
        run = self._agent.send(self._build_prompt(user_message, complexity))
        result = run.wait()
        if result.status == "error":
            return "Fault in processing."
        text = self._clean_for_speech(result.result or "")
        return text or self._fallback_action(user_message)

    def _build_prompt(self, message: str, complexity: str = "simple") -> str:
        wrapped = self._wrap_user_message(message, complexity)
        if self._persona_pending:
            self._persona_pending = False
            if self.formal_address and self.user_name:
                system = JARVIS_IRON_MAN.format(user_name=self.user_name)
            elif self.persona == "iron_man":
                name = self.user_name or "sir"
                system = JARVIS_IRON_MAN.format(user_name=name)
            else:
                system = JARVIS_SYSTEM_CASUAL
            return f"[SYSTEM]\n{system}\n\n{wrapped}"
        return wrapped

    def _wrap_user_message(self, message: str, complexity: str = "simple") -> str:
        label = self.user_name or "user"
        base = f"[VOICE — {label}]\n{message}\n\n"
        if complexity == "deep":
            return base + DEEP_ACTION_HINT
        if complexity == "complex":
            return base + COMPLEX_ACTION_HINT
        if self.is_action(message):
            hint = FAST_ACTION_HINT if self.fast_mode else ACTION_HINT
            return base + hint
        if self.fast_mode:
            return base + "One short sentence. No tools unless required."
        return base + "Reply as JARVIS in British English. One or two short sentences."

    def _clean_for_speech(self, text: str) -> str:
        text = re.sub(r"```[\s\S]*?```", "Done, sir.", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"#+\s*", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"\n{2,}", ". ", text)
        text = re.sub(r"\n", " ", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        if len(text) > self.max_speech_chars:
            cut = text[:self.max_speech_chars].rsplit(".", 1)[0]
            suffix = ", sir." if self.formal_address or self.persona == "iron_man" else "."
            text = (cut + suffix) if cut else text[:self.max_speech_chars]
        text = text or ("Done, sir." if self.persona == "iron_man" else "Done.")
        if not self.formal_address and self.persona != "iron_man":
            text = re.sub(r',?\s*\bsir\b\.?', '', text, flags=re.I)
            text = re.sub(r'\s{2,}', ' ', text).strip()
        return text
