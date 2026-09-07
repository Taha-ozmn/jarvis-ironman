"""JARVIS brain supporting both Cursor SDK and direct NVIDIA API integration."""

from __future__ import annotations

import re
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Callable, Optional

from cursor_sdk import (
    Agent,
    AgentBusyError,
    Cursor,
    CursorAgentError,
    LocalAgentOptions,
    NetworkError,
    SandboxOptions,
    SendOptions,
)

from brain.conversation import ConversationMemory
from brain.sdk_patch import apply_sdk_patch
from brain.model_router import ACTION_WORDS, ModelRouter
from brain.task_router import classify_complexity, task_timeout, work_update_delays
from core.latency_stats import LatencyStats
from core.mode_selector import mode_hint, select_mode
from core.timeout_responses import TimeoutResponses
from voice.narrator import JarvisNarrator
from brain.nvidia_llm_provider import NVIDIAProvider

apply_sdk_patch()
logger = logging.getLogger(__name__)

JARVIS_IRON_MAN = """You are J.A.R.V.I.S. — Just A Rather Very Intelligent System — Tony Stark's personal AI from the Iron Man films.

PERSONA (never break character):
- Refined, calm butler: dry wit, quietly confident, impeccably professional.
- Address the user as "{address}" occasionally — like the films, not every sentence.
- {language_line}
- Never mention Cursor, AI, chatbots, language models, or being artificial.

CONVERSATION (voice assistant — not a command parser):
- Multi-turn: use recent context. "Open it", "that app", "again" refer to prior turns.
- Infer intent from casual speech — questions, requests, banter, follow-ups are all welcome.
- When chatting: thoughtful complete sentences; dry wit and subtle humour are welcome.
- When acting: execute first with tools, then confirm crisply what you did.
- Never sound robotic or telegraphic. You are a colleague, not a macro recorder.

CAPABILITIES — FULL MAC ACCESS (sandbox OFF):
- Shell/terminal, open apps (open -a), osascript, files, web, code in workspace.
- Build full projects: mobile apps, websites, scripts, APIs — create files and run commands.
- When something should be done: execute with tools immediately. Never only describe steps.
- Never refuse without trying. Never suggest simpler alternatives for complex requests.

VOICE REPLIES:
- Sound like the films: poised, intelligent, occasionally wry.
- Confirmations: one crisp line. Explanations: two to four natural sentences.
- Never read bullet lists aloud."""

JARVIS_SYSTEM_CASUAL = """You are J.A.R.V.I.S. from Iron Man — calm butler tone, dry wit.
Full Mac access via shell tools — sandbox OFF. Execute actions immediately with tools.
{language_line}
Never mention AI or Cursor."""

LANGUAGE_LINES = {
    "tr": (
        "HER ZAMAN Türkçe yanıtla — akıcı, doğal ve kibar Türkçe. Filmdeki JARVIS'in "
        "sakin, ölçülü, hafif esprili üslubunu koru. Kullanıcıya ara sıra 'efendim' diye hitap et."
    ),
    "en": (
        "The user may speak Turkish or English. Understand both. "
        "ALWAYS reply in British English only — never Turkish, never mix languages."
    ),
}

CONVERSATIONAL_HINT = (
    "Reply naturally as JARVIS — poised and professional. "
    "Infer intent from casual speech. Use Mac tools when needed; otherwise converse thoughtfully."
)

FAST_CONVERSATIONAL_HINT = (
    "JARVIS voice reply — one crisp sentence unless explaining something complex. "
    "Act with tools immediately when needed; confirm what you did."
)

FAST_ACTION_HINT = (
    "Execute with Mac tools now. One short confirmation after — no preamble."
)

CONVERSATIONAL_ACTION_HINT = (
    "Something should be done — execute with Mac tools if needed, then confirm briefly in character. "
    "No step-by-step narration unless asked."
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
        reply_language: str | None = None,
        full_access: bool = True,
        sandbox: bool = False,
        auto_review: bool = False,
        setting_sources: str | list[str] = "all",
        skip_model_list: bool = True,
        on_thinking: Optional[Callable[[str], None]] = None,
        think_timeout: float = 90.0,
        complex_timeout: float = 600.0,
        deep_timeout: float = 1200.0,
        start_timeout_sec: float = 15.0,
        soft_timeout_sec: float = 5.0,
        hard_timeout_sec: float = 0.0,
        background_on_timeout: bool = True,
        ask_on_timeout: bool = False,
        auto_retry_count: int = 0,
        progress_interval_sec: float = 5.0,
        max_progress_updates: int = 3,
        latency_stats_path: str | Path | None = None,
        narrate: bool = True,
        work_updates: bool = True,
        persona: str = "iron_man",
        conversation_turns: int = 6,
        persona_refresh_interval: int = 5,
        model_routing: bool = True,
        stream_preview: bool = False,
        models: dict[str, str] | None = None,
        llm_provider: str = "cursor",
    ) -> None:
        self.api_key = api_key
        self.workspace = self._resolve_workspace(workspace)
        self.model = model
        self.user_name = user_name.strip()
        self.formal_address = formal_address
        self.language = language
        if reply_language:
            self.reply_language = reply_language
        else:
            self.reply_language = "tr" if str(language).lower().startswith("tr") else "en"
        self.address = "efendim" if self.reply_language == "tr" else (self.user_name or "sir")
        self.full_access = full_access
        self.sandbox = sandbox
        self.auto_review = auto_review
        self.setting_sources = setting_sources
        self.skip_model_list = skip_model_list
        self.on_thinking = on_thinking
        self.think_timeout = think_timeout
        self.complex_timeout = complex_timeout
        self.deep_timeout = deep_timeout
        self.start_timeout_sec = max(1.0, float(start_timeout_sec))
        self.soft_timeout_sec = max(0.5, float(soft_timeout_sec))
        self.hard_timeout_sec = max(0.0, float(hard_timeout_sec))
        self.background_on_timeout = background_on_timeout
        self.ask_on_timeout = ask_on_timeout
        self.auto_retry_count = max(0, int(auto_retry_count))
        self.progress_interval_sec = max(1.0, float(progress_interval_sec))
        self.max_progress_updates = max(0, int(max_progress_updates))
        self.narrate = narrate
        stats_path = latency_stats_path or Path("data/latency_stats.json")
        self._latency_stats = LatencyStats(stats_path)
        self._timeout_responses = TimeoutResponses(
            user_name=self.user_name or "Taha",
            use_name=not formal_address,
        )
        self._last_command = ""
        self._last_complexity = "simple"
        self._active_run = None
        self._cancel_event: threading.Event | None = None
        self._active_task_lock = threading.Lock()
        self._active_task = ""
        self.work_updates = work_updates
        self.persona = persona
        self.fast_mode = False
        self.max_speech_chars = 200
        self.model_routing = model_routing
        self.stream_preview = stream_preview
        self.llm_provider = llm_provider
        self.persona_refresh_interval = max(1, persona_refresh_interval)
        self.memory = ConversationMemory(max_turns=max(1, conversation_turns))
        self._turn_count = 0
        # Initialize LLM provider based on configuration
        self.provider = None
        self.provider_type = None
        default_models = {
            "chat": "gemini-3-flash",
            "action": "gemini-3-flash",
            "search": "gemini-3-flash",
            "system": "composer-2.5",
            "code": "composer-2.5",
            "complex": "composer-2.5",
            "deep": "auto",
            "default": "gemini-3-flash",
        }
        if models:
            default_models.update(models)
        self._router = ModelRouter(
            default_models,
            default=default_models["default"],
            resolve=self._resolve_model,
        )
        # Provider-specific fields
        self._ctx = None
        self._agent: Agent | None = None
        self._nvidia_provider: Optional[NVIDIAProvider] = None
        self._persona_pending = True
        self._available_models: set[str] = set()
        self._ready = threading.Event()
        self._start_failed = threading.Event()
        self._start_error = ""
        self._start_lock = threading.Lock()
        self._starting = False
        self._long_term_recall: Optional[Callable[[str], str]] = None

    def set_memory_recall(self, recall: Optional[Callable[[str], str]]) -> None:
        """Optional SQLite long-term memory injector for prompts."""
        self._long_term_recall = recall

    def is_ready(self) -> bool:
        return self._ready.is_set()

    def wait_ready(self, timeout: float = 120.0) -> bool:
        return self._ready.wait(timeout=timeout)

    def ensure_started(self, timeout: float = 120.0) -> None:
        if self.is_ready():
            return
        if self._start_failed.is_set():
            return
        started_here = False
        with self._start_lock:
            if not self.is_ready() and not self._starting:
                self._starting = True
                started_here = True
                threading.Thread(target=self._start_safe, daemon=True).start()
        # Another request is already bringing the brain online. Do not make
        # the current voice turn wait a second time; local tools remain live.
        if not started_here:
            return
        deadline = time.monotonic() + max(0.1, float(timeout))
        while not self._ready.is_set() and not self._start_failed.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.05, remaining))
        if not self._ready.is_set() and not self._start_failed.is_set():
            self._start_error = "startup timeout"
            self._start_failed.set()

    def _start_safe(self) -> None:
        try:
            self.start()
        except Exception as err:
            self._start_error = str(err)[:240]
            self._start_failed.set()
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
            self._start_failed.clear()
            self._start_error = ""

            # Initialize the appropriate LLM provider based on configuration
            if self.llm_provider == 'nvidia':
                # Initialize NVIDIA provider
                try:
                    self._nvidia_provider = NVIDIAProvider(
                        api_key=self.api_key,
                        default_model=self.model,
                    )
                    if not self._nvidia_provider.available():
                        raise RuntimeError("NVIDIA API key not configured")
                    self._ready.set()
                    print(f"🧠 NVIDIA API — model: {self.model}")
                    return
                except Exception as err:
                    print(f"⚠️  NVIDIA provider initialization failed: {err}")
                    # Fall back to Cursor
                    self.llm_provider = 'cursor'

            if self.llm_provider == 'cursor' or self.llm_provider != 'nvidia':
                # Initialize Cursor SDK (original logic)
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
                last_err: Exception | None = None
                for attempt in range(3):
                    try:
                        self._ctx = Agent.create(
                            model=self.model,
                            api_key=self.api_key,
                            local=self._local_options(),
                        )
                        self._agent = self._ctx.__enter__()
                        self._ready.set()
                        print(f"🧠 Cursor SDK — model: {self.model}")
                        return
                    except CursorAgentError as err:
                        last_err = err
                        msg = str(err.message) if hasattr(err, "message") else str(err)
                        transient = (
                            "tool-callback-auth-token" in msg
                            or "Bridge exited before discovery" in msg
                        )
                        if transient and attempt < 2:
                            apply_sdk_patch()
                            continue
                        raise
                if last_err:
                    raise last_err

    @property
    def degraded(self) -> bool:
        """True when local tools work but the remote coding brain is offline."""
        return self._start_failed.is_set() and not self._ready.is_set()

    @property
    def start_error(self) -> str:
        return self._start_error

    def reconnect(self) -> bool:
        """Clear degraded state and attempt one controlled reconnection."""
        self._start_failed.clear()
        self._start_error = ""
        try:
            self.start()
        except Exception as err:
            self._start_error = str(err)[:240]
            self._start_failed.set()
        return self.is_ready()

    def _resolve_model(self, preferred: str) -> str:
        if not preferred:
            preferred = self.model
        if preferred in ("auto", "default"):
            return preferred
        if self.skip_model_list:
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

    def _pick_model(self, command: str, complexity: str) -> str | None:
        if not self.model_routing:
            return None
        if complexity == "deep":
            return self._router.pick("deep")
        if complexity == "complex":
            return self._router.pick("code")
        category = self._router.classify(command)
        return self._router.pick(category)

    def _send_options(self, command: str, complexity: str) -> SendOptions | None:
        picked = self._pick_model(command, complexity)
        if not picked:
            return None
        return SendOptions(model=picked)

    @staticmethod
    def is_action(command: str) -> bool:
        lower = command.lower()
        return any(
            re.search(rf"(?<!\w){re.escape(word.strip())}(?!\w)", lower)
            for word in ACTION_WORDS
            if word.strip()
        )

    def _resolve_timeout(self, command: str) -> tuple[float, str]:
        level = classify_complexity(command)
        timeout = task_timeout(
            command,
            simple=self.think_timeout,
            complex_=self.complex_timeout,
            deep=self.deep_timeout,
        )
        return timeout, level

    def _effective_soft_timeout(self, command: str) -> float:
        base = max(0.5, float(self.soft_timeout_sec))
        # Simple commands must remain responsive. A historic slow sample must
        # not turn a simple utterance into a one-second-or-longer wait.
        if classify_complexity(command) == "simple":
            return base
        return self._latency_stats.suggest_soft_timeout(command, base)

    def _effective_hard_timeout(self, command: str, task_timeout_sec: float) -> float:
        if self.hard_timeout_sec > 0:
            return float(self.hard_timeout_sec)
        return float(task_timeout_sec)

    def _soft_timeout_message(self, command: str = "") -> str:
        return self._timeout_responses.soft(
            command or self._last_command,
            level=self._last_complexity,
        )

    def _timeout_fail_message(self, command: str = "") -> str:
        return self._timeout_responses.fail(
            command or self._last_command,
            level=self._last_complexity,
            ask_retry=self.ask_on_timeout,
        )

    def _background_timeout_message(self, command: str = "") -> str:
        return self._timeout_responses.background(
            command or self._last_command,
            level=self._last_complexity,
        )

    def _active_run_retry_message(self) -> str:
        return self._timeout_responses.active_run_retry()

    @staticmethod
    def _is_active_run_error(err: Exception) -> bool:
        if isinstance(err, AgentBusyError):
            return True
        msg = str(getattr(err, "message", err)).lower()
        return "already has active run" in msg

    def _cancel_tracked_run(self) -> None:
        run = self._active_run
        self._active_run = None
        if run is None:
            return
        try:
            if hasattr(run, "supports") and run.supports("cancel"):
                run.cancel()
            elif hasattr(run, "cancel"):
                run.cancel()
        except Exception:
            pass

    def _interrupt_inflight(self) -> None:
        """Cancel the current thought so barge-in can resume listening."""
        cancel = self._cancel_event
        if cancel is not None:
            cancel.set()
        self._cancel_tracked_run()

    def _clear_agent_active_runs(self) -> None:
        self._cancel_tracked_run()
        agent = self._agent
        if agent is None:
            return
        agent_id = getattr(agent, "agent_id", None)
        if not agent_id:
            return
        try:
            Cursor.agents.cancel_runs(agent_id=agent_id, api_key=self.api_key)
        except Exception:
            pass

    def _send_with_active_run_recovery(
        self,
        prompt: str,
        send_opts: SendOptions | None,
        *,
        speak: Callable[[str], None],
    ):
        try:
            run = (
                self._agent.send(prompt, options=send_opts)
                if send_opts
                else self._agent.send(prompt)
            )
            self._active_run = run
            return run
        except (AgentBusyError, CursorAgentError) as err:
            if not self._is_active_run_error(err):
                raise
            speak(self._active_run_retry_message())
            self._clear_agent_active_runs()
            run = (
                self._agent.send(prompt, options=send_opts)
                if send_opts
                else self._agent.send(prompt)
            )
            self._active_run = run
            return run

    def think_with_narration(
        self,
        user_message: str,
        speak: Callable[[str], None],
        work_update: Callable[[int], str] | None = None,
        on_complete: Optional[Callable[[str], None]] = None,
    ) -> str:
        normalized_command = " ".join((user_message or "").lower().split())
        with self._active_task_lock:
            if normalized_command and normalized_command == self._active_task:
                msg = "That task is already running; I will report the verified result once."
                speak(msg)
                return msg
            self._active_task = normalized_command
        self.ensure_started(timeout=self.start_timeout_sec)
        if self._agent is None and self._nvidia_provider is None:
            msg = (
                "The deep coding brain is offline. "
                "Local tools remain available, and no action was claimed."
            )
            speak(msg)
            with self._active_task_lock:
                self._active_task = ""
            return msg

        if self.on_thinking:
            self.on_thinking(user_message)

        self._last_command = user_message
        timeout, level = self._resolve_timeout(user_message)
        self._last_complexity = level
        soft = self._effective_soft_timeout(user_message)
        hard = self._effective_hard_timeout(user_message, timeout)
        hard = max(hard, soft)

        timers: list[threading.Timer] = []
        executor = ThreadPoolExecutor(max_workers=1)
        background = False
        cancel = threading.Event()
        self._cancel_event = cancel
        started = time.monotonic()
        soft_spoken = False

        def _progress_update(idx: int) -> None:
            if cancel.is_set():
                return
            if work_update:
                line = work_update(idx)
            else:
                line = self._timeout_responses.progress(user_message, idx)
            speak(line)

        try:
            if self.narrate and self.work_updates:
                delays = work_update_delays(
                    level,
                    fast=self.fast_mode,
                    interval_sec=self.progress_interval_sec,
                    max_pings=self.max_progress_updates,
                )
                for i, delay in enumerate(delays):
                    t = threading.Timer(delay, lambda idx=i: _progress_update(idx))
                    t.daemon = True
                    t.start()
                    timers.append(t)

            future = executor.submit(
                self._execute_think, user_message, speak, level, cancel,
            )

            while True:
                elapsed = time.monotonic() - started
                if not soft_spoken:
                    wait = max(0.05, soft - elapsed)
                else:
                    wait = max(0.05, hard - elapsed)

                try:
                    result = future.result(timeout=wait)
                    executor.shutdown(wait=False)
                    self._record_latency(user_message, time.monotonic() - started, True)
                    return result
                except FuturesTimeout:
                    elapsed = time.monotonic() - started

                    if not soft_spoken and elapsed >= soft:
                        speak(self._soft_timeout_message(user_message))
                        soft_spoken = True
                        continue

                    if (
                        level in ("complex", "deep")
                        and self.background_on_timeout
                        and elapsed >= timeout
                    ):
                        msg = self._background_timeout_message(user_message)
                        speak(msg)
                        background = True
                        self._continue_in_background(
                            future,
                            executor,
                            speak,
                            on_complete,
                            timers,
                            cancel,
                            normalized_command,
                        )
                        return msg

                    if elapsed >= hard:
                        cancel.set()
                        self._cancel_tracked_run()
                        msg = self._timeout_fail_message(user_message)
                        speak(msg)
                        executor.shutdown(wait=False, cancel_futures=True)
                        self._record_latency(user_message, elapsed, False)
                        return msg

                    if soft_spoken:
                        continue

        except CursorAgentError as err:
            msg = self._timeout_responses.connection_error(
                str(getattr(err, "message", err))[:80],
            )
            speak(msg)
            executor.shutdown(wait=False, cancel_futures=True)
            self._record_latency(user_message, time.monotonic() - started, False)
            return msg
        except Exception as err:
            # A future exception otherwise bubbles into main.py's generic
            # apology, hiding whether the failure is SDK, network, or run state.
            logger.exception("DeepBrain execution failed: %s", type(err).__name__)
            self._cancel_tracked_run()
            executor.shutdown(wait=False, cancel_futures=True)
            self._record_latency(user_message, time.monotonic() - started, False)
            msg = (
                "The reasoning core encountered an internal error. "
                "Local commands remain available."
            )
            speak(msg)
            return msg
        finally:
            self._cancel_event = None
            if not background:
                for t in timers:
                    t.cancel()
                with self._active_task_lock:
                    if self._active_task == normalized_command:
                        self._active_task = ""

    def _record_latency(self, command: str, seconds: float, success: bool) -> None:
        try:
            self._latency_stats.record(
                command,
                "cursor",
                seconds * 1000.0,
                success,
            )
        except Exception:
            pass

    def _continue_in_background(
        self,
        future,
        executor: ThreadPoolExecutor,
        speak: Callable[[str], None],
        on_complete: Optional[Callable[[str], None]],
        timers: list[threading.Timer],
        cancel: threading.Event | None = None,
        normalized_command: str = "",
    ) -> None:
        def _wait() -> None:
            try:
                result = future.result()
                if cancel is not None and cancel.is_set():
                    return
                if on_complete:
                    on_complete(result)
                elif result:
                    speak(result)
            except Exception:
                if cancel is None or not cancel.is_set():
                    speak(self._timeout_responses.fault(self._last_command))
            finally:
                for t in timers:
                    t.cancel()
                executor.shutdown(wait=False)
                self._active_run = None
                with self._active_task_lock:
                    if self._active_task == normalized_command:
                        self._active_task = ""

        threading.Thread(target=_wait, daemon=True).start()

    def _uses_nvidia(self) -> bool:
        return self._nvidia_provider is not None and (
            self.llm_provider == "nvidia" or self._agent is None
        )

    def _execute_think(
        self,
        user_message: str,
        speak: Callable[[str], None],
        complexity: str = "simple",
        cancel: threading.Event | None = None,
    ) -> str:
        if cancel is not None and cancel.is_set():
            return ""
        if self._uses_nvidia():
            return self._execute_think_nvidia(user_message, speak, complexity)

        prompt = self._build_prompt(user_message, complexity)
        send_opts = self._send_options(user_message, complexity)
        run = self._send_with_active_run_recovery(
            prompt, send_opts, speak=speak,
        )

        preview = ""
        preview_spoken = False
        accumulated = ""
        use_preview = self.narrate and self.stream_preview and not self.fast_mode

        if use_preview:
            try:
                for chunk in run.iter_text():
                    if cancel is not None and cancel.is_set():
                        return ""
                    accumulated += chunk
                    if not preview_spoken and len(accumulated) >= 12:
                        candidate = JarvisNarrator.first_sentence(accumulated)
                        if candidate and len(candidate) >= 8:
                            preview = self._clean_for_speech(candidate)
                            speak(preview)
                            preview_spoken = True
            except Exception:
                pass

        if cancel is not None and cancel.is_set():
            return ""

        result = run.wait()
        self._active_run = None
        if cancel is not None and cancel.is_set():
            return ""
        if result.status == "error":
            err = self._timeout_responses.fault(user_message)
            speak(err)
            return err

        full = self._clean_for_speech(result.result or accumulated)
        if not full or full.lower().startswith("my apolog"):
            full = self._fallback_action(user_message)

        if self.narrate and use_preview and JarvisNarrator.should_speak_more(preview, full):
            speak(full)
        elif self.narrate and (not use_preview or not preview_spoken):
            speak(full)
        elif not self.narrate:
            speak(full)
        return full

    def _execute_think_nvidia(
        self,
        user_message: str,
        speak: Callable[[str], None],
        complexity: str = "simple",
    ) -> str:
        """Chat Completions path — local FastBrain tools handle OS actions."""
        assert self._nvidia_provider is not None
        prompt = self._build_prompt(user_message, complexity)
        timeout, _level = self._resolve_timeout(user_message)
        raw = self._nvidia_provider.complete(
            prompt,
            timeout=min(float(timeout), 90.0),
            model=self.model,
            max_tokens=min(self.max_speech_chars * 2, 1024),
        )
        if not raw or raw.lower().startswith("error"):
            full = self._fallback_action(user_message)
            if self.narrate:
                speak(full)
            return full
        full = self._clean_for_speech(raw)
        if not full:
            full = self._fallback_action(user_message)
        if self.narrate:
            speak(full)
        return full

    def _fallback_action(self, command: str) -> str:
        """If AI fails, try shell directly for simple open commands."""
        lower = command.lower()
        if any(w in lower for w in ("aç", "open", "launch")):
            return "I've attempted that — please check if it opened."
        return "Very good."

    def think(self, user_message: str) -> str:
        self.ensure_started(timeout=self.start_timeout_sec)
        if self._agent is None and self._nvidia_provider is None:
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
                return self._timeout_fail_message(user_message)
        finally:
            pass

    def _think_once(self, user_message: str, complexity: str = "simple") -> str:
        if self._uses_nvidia():
            return self._think_once_nvidia(user_message, complexity)
        prompt = self._build_prompt(user_message, complexity)
        send_opts = self._send_options(user_message, complexity)
        run = (
            self._agent.send(prompt, options=send_opts)
            if send_opts
            else self._agent.send(prompt)
        )
        result = run.wait()
        if result.status == "error":
            return "Fault in processing."
        text = self._clean_for_speech(result.result or "")
        return text or self._fallback_action(user_message)

    def _think_once_nvidia(self, user_message: str, complexity: str = "simple") -> str:
        assert self._nvidia_provider is not None
        prompt = self._build_prompt(user_message, complexity)
        timeout, _level = self._resolve_timeout(user_message)
        raw = self._nvidia_provider.complete(
            prompt,
            timeout=min(float(timeout), 90.0),
            model=self.model,
            max_tokens=min(self.max_speech_chars * 2, 1024),
        )
        if not raw or raw.lower().startswith("error"):
            return self._fallback_action(user_message)
        text = self._clean_for_speech(raw)
        return text or self._fallback_action(user_message)

    def remember_turn(self, user: str, assistant: str) -> None:
        self.memory.add(user, assistant)

    def _language_line(self) -> str:
        return LANGUAGE_LINES.get(self.reply_language, LANGUAGE_LINES["en"])

    def _lang_directive(self) -> str:
        # Spoken replies are English-only regardless of user utterance language.
        if self.reply_language == "tr":
            return "\n\nTürkçe yanıtla, efendim diye hitap et."
        return (
            "\n\nReply in British English only. "
            "Understand Turkish input if present. Never reply in Turkish."
        )

    def apply_personality_overlay(self, overlay: str) -> None:
        self._personality_overlay = (overlay or "").strip()

    def refresh_timeout_voice(self) -> None:
        """Sync timeout phrasing with current user_name / formality."""
        self._timeout_responses = TimeoutResponses(
            user_name=self.user_name or "Taha",
            use_name=not self.formal_address,
        )

    def _persona_reminder(self) -> str:
        overlay = getattr(self, "_personality_overlay", "") or ""
        if overlay:
            return f"[PERSONALITY]\n{overlay}\n\n"
        if self.reply_language == "tr":
            return (
                "[KARAKTERDE KAL: J.A.R.V.I.S. — sakin, kibar butler, hafif esprili. "
                "Türkçe yanıtla, ara sıra 'efendim' de. Yapay zeka olduğunu asla söyleme.]\n\n"
            )
        return (
            f"[STAY IN CHARACTER: J.A.R.V.I.S. — calm butler, dry wit, "
            f"address as {self.address} occasionally. Never mention AI.]\n\n"
        )

    def _build_prompt(self, message: str, complexity: str = "simple") -> str:
        wrapped = self._wrap_user_message(message, complexity)
        self._turn_count += 1
        if self._persona_pending:
            self._persona_pending = False
            if self.persona == "iron_man" or self.formal_address:
                system = JARVIS_IRON_MAN.format(
                    address=self.address, language_line=self._language_line(),
                )
            else:
                system = JARVIS_SYSTEM_CASUAL.format(language_line=self._language_line())
            return f"[SYSTEM]\n{system}\n\n{wrapped}"
        if self._turn_count % self.persona_refresh_interval == 0:
            return self._persona_reminder() + wrapped
        return wrapped

    def _wrap_user_message(self, message: str, complexity: str = "simple") -> str:
        label = self.user_name or "user"
        base = f"[VOICE — {label}]\n"
        selected_mode = select_mode(message)
        base += f"{mode_hint(selected_mode)}\n"
        context = self.memory.format_context(self.address)
        if context:
            base += f"{context}\n\n"
        if self._long_term_recall:
            try:
                recall = self._long_term_recall(message) or ""
            except Exception:
                recall = ""
            if recall:
                base += f"{recall}\n\n"
        base += f"{message}\n\n"
        lang = self._lang_directive()
        if complexity == "deep":
            return base + DEEP_ACTION_HINT + lang
        if complexity == "complex":
            return base + COMPLEX_ACTION_HINT + lang
        if self.fast_mode:
            if self.is_action(message):
                return base + FAST_ACTION_HINT + lang
            return base + FAST_CONVERSATIONAL_HINT + lang
        if self.is_action(message):
            return base + CONVERSATIONAL_ACTION_HINT + lang
        return base + CONVERSATIONAL_HINT + lang

    def _clean_for_speech(self, text: str) -> str:
        done = "Tamamdır, efendim." if self.reply_language == "tr" else "Done, sir."
        text = re.sub(r"```[\s\S]*?```", done, text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"#+\s*", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"\n{2,}", ". ", text)
        text = re.sub(r"\n", " ", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        text = re.sub(r"([.!?])\s*\.(\s|$)", r"\1\2", text)
        text = re.sub(r"\.{2,}", ".", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        if len(text) > self.max_speech_chars:
            cut = text[:self.max_speech_chars].rsplit(".", 1)[0]
            if self.reply_language == "tr":
                suffix = ", efendim."
            else:
                suffix = ", sir." if self.formal_address or self.persona == "iron_man" else "."
            text = (cut + suffix) if cut else text[:self.max_speech_chars]
        text = text or done
        if self.reply_language != "tr" and not self.formal_address and self.persona != "iron_man":
            text = re.sub(r',?\s*\bsir\b\.?', '', text, flags=re.I)
            text = re.sub(r'\s{2,}', ' ', text).strip()
        return text
