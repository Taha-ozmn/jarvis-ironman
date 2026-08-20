"""Thin JARVIS 2.0 OS facade — additive, does not replace JarvisCore."""

from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

from automation.engine import AutomationEngine, AutomationRule
from brain.llm_provider import CursorProvider, build_default_router
from core.agent_profiles import (
    coding_analyze_plan,
    filter_plan_steps,
    research_plan,
)
from core.backup import BackupService
from core.brain_router import BrainPath, BrainRouter
from core.command_router import CommandRouter
from core.context_manager import ContextManager, SessionContext
from core.cost_meter import CostMeter
from core.decision_engine import (
    DecisionEngine,
    decision_context_from_session,
)
from core.diagnostics import SelfDiagnostics
from core.event_bus import EventBus
from core.execution_engine import ExecutionEngine, ExecutionRequest
from core.jarvis_state import JarvisState
from core.planner import Planner, make_llm_refine
from core.task_manager import TaskManager
from core.verification import claim_safe_speech
from integrations.mcp_adapter import MCPAdapter
from memory.database import Database
from memory.extractor import extract_and_save, is_trivial_utterance
from memory.layers import MemoryLayers
from memory.repository import MemoryRepository
from projects.registry import ProjectRegistry
from proactive.briefing import BriefingGenerator
from proactive.notifier import NotificationPolicy, ProactiveNotifier
from security.audit import AuditLog
from security.confirmation import ConfirmationGate
from security.permissions import PermissionGate, PermissionLevel
from system.macos import MacOSController
from tools.bootstrap import register_phase3_tools
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SpeakFn = Callable[[str], None]


class JarvisOS:
    """Compose Phase-2/3/4 subsystems beside legacy JarvisCore."""

    def __init__(
        self,
        config: Optional[dict[str, Any]] = None,
        *,
        root: Optional[Path] = None,
        macos: Optional[MacOSController] = None,
    ) -> None:
        self.root = root or ROOT
        self.config = config or {}
        j2 = self.config.get("jarvis2", {})
        db_rel = j2.get("db_path", "data/jarvis.db")
        self.db_path = (self.root / db_rel).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        max_level = int(j2.get("max_permission_level", PermissionLevel.SYSTEM.value))
        jarvis_cfg = self.config.get("jarvis", {})
        sys_cfg = self.config.get("system", {})
        proactive_cfg = j2.get("proactive") or {}
        # full_autonomy ⇒ Level-3 auto-approve + audit; catastrophic patterns still blocked in tools
        self.full_autonomy = bool(j2.get("full_autonomy", False))
        self.auto_approve_level_0_1_2 = bool(j2.get("auto_approve_level_0_1_2", True))
        auto_approve_l3 = self.full_autonomy or bool(j2.get("auto_approve_dangerous", False))
        # dry-run mode: when True, tools will not perform actual changes
        self.dry_run = bool(j2.get("dry_run", False))

        self.bus = EventBus()
        self.context = ContextManager(
            SessionContext(
                user_name=jarvis_cfg.get("user_name", ""),
                language=jarvis_cfg.get("language", "en-GB"),
                model=jarvis_cfg.get("model", "composer-2.5"),
            ),
            max_turns=int(jarvis_cfg.get("conversation_turns", 40)),
        )
        self.db = Database(self.db_path)
        self.db.migrate()
        self.memory = MemoryRepository(self.db)
        self.memory_layers = MemoryLayers(self.memory)
        self.tasks = TaskManager(self.db)
        self.permissions = PermissionGate(PermissionLevel(max_level))
        self.confirmation = ConfirmationGate(
            auto_approve=auto_approve_l3,
            default_timeout=float(j2.get("confirm_timeout", 60)),
        )
        self.audit = AuditLog(self.db)
        self.macos = macos or MacOSController(
            full_shell_access=sys_cfg.get("full_shell_access", True),
        )
        self._speak: Optional[SpeakFn] = None
        self._brain: Any = None
        self._level_notify: Optional[Callable[[int, str, dict[str, Any]], None]] = None
        self._confirm_pending_ui: Optional[Callable[[Any], None]] = None

        self.briefing = BriefingGenerator(
            self.tasks,
            self.memory,
            self.db,
            user_name=jarvis_cfg.get("user_name", ""),
            language=jarvis_cfg.get("language", "en-GB"),
        )
        self.notifier = ProactiveNotifier(NotificationPolicy.from_config(proactive_cfg))

        auto_enabled = bool(j2.get("automation", True))
        self.automation = AutomationEngine(
            self.db,
            enabled=auto_enabled,
            tick_seconds=float(j2.get("automation_tick_seconds", 30)),
            max_failures=int(j2.get("automation_max_failures", 3)),
            on_event=self._on_automation_event,
            on_audit=self._on_automation_audit,
        )
        self.automation.set_action_handler(self._handle_automation_action)

        self.projects = ProjectRegistry(
            self.db,
            context=self.context,
        )
        self.projects.load()
        # Prefer jarvis workspace from config if present and registered
        jarvis_ws = jarvis_cfg.get("workspace")
        if jarvis_ws:
            try:
                from pathlib import Path as _P

                ws = _P(jarvis_ws).expanduser()
                if ws.exists():
                    for p in self.projects.list_projects():
                        if _P(p.path).expanduser().resolve() == ws.resolve():
                            self.projects.set_active(p.key)
                            break
            except (FileNotFoundError, PermissionError, OSError) as e:
                logger.debug("Workspace path resolution failed: %s", e)
                pass
            except Exception as e:
                logger.warning("Unexpected error setting workspace: %s", type(e).__name__)
                pass

        backup_retention = int(j2.get("backup_retention", 10))
        self.backup = BackupService(
            db_path=self.db_path,
            root=self.root,
            backup_dir=self.root / "data" / "backups",
            retention=backup_retention,
        )
        models = jarvis_cfg.get("models") or {}
        default_model = str(jarvis_cfg.get("model") or "composer-2.5")
        self.model_router = build_default_router(models, default_model)
        self.llm = CursorProvider(brain=None, router=self.model_router)
        self.mcp = MCPAdapter()
        max_plan_steps = int(j2.get("max_plan_steps", 12))
        plan_timeout_sec = float(j2.get("plan_timeout_sec", 300))
        self.deep_max_iterations = int(j2.get("deep_max_iterations", 8))
        self.planner = Planner(
            llm_refine=make_llm_refine(self.llm),
            max_steps=max_plan_steps,
        )
        max_retries = int(j2.get("plan_max_retries", 1))

        self.tools = ToolRegistry()
        register_phase3_tools(
            self.tools,
            macos=self.macos,
            memory=self.memory,
            tasks=self.tasks,
            health_fn=self.health,
            automation=self.automation,
            briefing=self.briefing,
            projects=self.projects,
            working_dir=self.projects.working_dir,
            backup=self.backup,
            plan_runner=self._run_plan_goal,
            llm=self.llm,
            jarvis2_config=j2,
            jarvis_language=str(jarvis_cfg.get("language", "en-GB")),
            on_preference_applied=self._on_preference_applied,
            screen_context_getter=self._screen_context,
            memory_layers=self.memory_layers,
            research_agent_runner=self.run_research_agent,
            coding_agent_runner=self.run_coding_analyze_agent,
            session_capture_setter=self.set_memory_capture,
        )
        # Live MCP — connect configured servers after local tools exist
        mcp_cfg = j2.get("mcp") or {}
        if bool(mcp_cfg.get("enabled", True)):
            servers = mcp_cfg.get("servers") or []
            if servers:
                try:
                    self.mcp.connect_servers(servers, self.tools)
                except Exception as e:
                    logger.warning("MCP connect_servers failed (isolated): %s", type(e).__name__)
            else:
                # Honest empty state — no crash
                self.mcp.register_server(
                    "_none",
                    tools=[],
                    transport="stdio",
                    connected=False,
                    error="no MCP servers configured",
                )
        self.execution = ExecutionEngine(
            self.tools,
            self.permissions,
            self.audit,
            self.bus,
            self.confirmation,
            on_level_notify=self._on_level_notify,
            max_retries=max_retries,
            max_plan_steps=max_plan_steps,
            plan_timeout_sec=plan_timeout_sec,
            working_dir=self.projects.working_dir,
            tasks=self.tasks,
            dry_run=self.dry_run,
        )
        self.router = CommandRouter()
        # FastBrain vs DeepBrain classifier (guides latency path; does not replace Cursor)
        self.brain_router = BrainRouter(self.router)
        self.decision_engine = DecisionEngine()
        self._last_decision_rationale = ""
        self.personality = dict(self.config.get("personality") or {})
        self._last_brain_path: Optional[str] = None
        self.cost_meter = CostMeter(
            self.root / "data" / "cost_meter.json",
            rates=self.config.get("cost") or {},
        )
        self.state = JarvisState(
            self.context,
            confirmation=self.confirmation,
            tasks=self.tasks,
            projects=self.projects,
        )
        self.diagnostics = SelfDiagnostics(self)
        self.recall_limit = int(j2.get("memory_recall_limit", 3))
        self.recall_max_chars = int(j2.get("memory_recall_max_chars", 300))
        self.proactive_enabled = bool(proactive_cfg.get("enabled", True))
        self._ready = True
        self.screen_watcher = None
        self.light_mode = None
        self._diag_cache: dict[str, Any] = {"ts": 0.0, "payload": None}
        self._health_history: deque = deque(maxlen=10)
        self._wire_screen_and_light(j2)
        self.bus.publish(
            "os.ready",
            {
                "db": str(self.db_path),
                "tools": self.tools.list_names(),
                "automation": auto_enabled,
            },
            source="jarvis_os",
        )
        logger.info(
            "JARVIS 2.0 core ready — db=%s tools=%s automation=%s",
            self.db_path,
            len(self.tools.list_names()),
            auto_enabled,
        )

    def set_ui_hooks(
        self,
        *,
        on_level_notify: Optional[Callable[[int, str, dict[str, Any]], None]] = None,
        on_confirm_pending: Optional[Callable[[Any], None]] = None,
    ) -> None:
        """Wire HUD permission notices + Level-3 confirm prompts."""
        self._level_notify = on_level_notify
        self._confirm_pending_ui = on_confirm_pending
        if on_confirm_pending is not None:
            self.confirmation.set_on_pending(self._forward_confirm_pending)

    def _forward_confirm_pending(self, pending: Any) -> None:
        if self._speak:
            try:
                self._speak(
                    "Confirmation required — say yes or no, or use the HUD."
                )
            except Exception as e:
                logger.warning("Speech failed in confirmation: %s", type(e).__name__)
        if self._confirm_pending_ui:
            try:
                self._confirm_pending_ui(pending)
            except Exception as e:
                logger.warning("Confirmation UI callback failed: %s", type(e).__name__)

    def _on_level_notify(self, level: int, tool: str, args: dict[str, Any]) -> None:
        if self._level_notify:
            try:
                self._level_notify(level, tool, args)
            except Exception as e:
                logger.warning("UI level notify failed: %s", type(e).__name__)

    def command_center(self) -> dict[str, Any]:
        from ui.hud_data import build_command_center

        return build_command_center(self)

    @property
    def ready(self) -> bool:
        return self._ready

    def health(self) -> dict[str, Any]:
        # Get base diagnostics summary
        diag = self.diagnostics.summary()
        # Get subsystem health
        subsystems = self.get_subsystem_health()
        # Determine overall OK: diagnostics ok and all subsystems ok
        diag_ok = diag.get("ok", False)
        subsystems_ok = all(
            sub.get("ok", False) for sub in subsystems.values()
        )
        overall_ok = diag_ok and subsystems_ok
        # Build result
        result = dict(diag)  # copy
        result["ok"] = overall_ok
        result["subsystems"] = subsystems
        # Add to health history for trend tracking
        self._health_history.append({
            "ts": time.time(),
            "ok": overall_ok,
            "diagnostics_ok": diag_ok,
            "subsystems_ok": subsystems_ok,
        })
        return result

    def health_cached(self, *, max_age_sec: float = 30.0) -> dict[str, Any]:
        """Throttle full subsystem diagnostics for HUD polls."""
        now = time.monotonic()
        cached = self._diag_cache.get("payload")
        if cached is not None and now - float(self._diag_cache["ts"]) < max_age_sec:
            return dict(cached)
        # Light mode: skip expensive full diagnostics
        if self.light_mode is not None and self.light_mode.active:
            payload = {
                "ok": True,
                "passed": 0,
                "total": 0,
                "checks": [],
                "light_mode": True,
                "note": "full diagnostics deferred (light mode)",
            }
        else:
            payload = self.health()
        self._diag_cache.update(ts=now, payload=payload)
        return dict(payload)

    def _get_subsystem_health(self, name: str, obj: Any) -> dict[str, Any]:
        """Get health status of a subsystem.
        Returns a dict with at least an 'ok' key.
        """
        try:
            if hasattr(obj, 'health'):
                health = obj.health()
                if isinstance(health, dict):
                    return health
                # If health returns non-dict, treat as truthy
                return {"ok": bool(health)}
            else:
                # Basic existence check
                return {"ok": obj is not None}
        except Exception as e:
            logger.debug("Health check failed for subsystem %s: %s", name, e)
            return {"ok": False, "error": "health check failed"}

    def get_subsystem_health(self) -> dict[str, Any]:
        """Get health status of all major subsystems.
        Returns a dict mapping subsystem names to their health dicts.
        """
        subsystems = [
            ("event_bus", self.bus),
            ("context", self.context),
            ("database", self.db),
            ("memory_repository", self.memory),
            ("memory_layers", self.memory_layers),
            ("task_manager", self.tasks),
            ("permissions", self.permissions),
            ("confirmation", self.confirmation),
            ("audit", self.audit),
            ("macos", self.macos),
            ("briefing", self.briefing),
            ("notifier", self.notifier),
            ("automation", self.automation),
            ("projects", self.projects),
            ("backup", self.backup),
            ("model_router", self.model_router),
            ("llm", self.llm),
            ("mcp", self.mcp),
            ("execution", self.execution),
            ("command_router", self.router),
            ("brain_router", self.brain_router),
            ("decision_engine", self.decision_engine),
            ("cost_meter", self.cost_meter),
            ("state", self.state),
            # diagnostics is already used in health()
        ]
        result = {}
        for name, obj in subsystems:
            result[name] = self._get_subsystem_health(name, obj)
        return result

    def _screen_context(self) -> dict[str, Any]:
        raw = self.context.get_extra("current_screen_context", {}) or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def _wire_screen_and_light(self, j2: dict[str, Any]) -> None:
        from system.light_mode import LightModeController
        from system.screen_watcher import ScreenWatcher

        screen_cfg = (self.config.get("screen") or {}) if isinstance(self.config, dict) else {}
        always = bool(screen_cfg.get("always_watch", True))
        poll = float(screen_cfg.get("poll_interval_sec", 15))
        on_change = bool(screen_cfg.get("screenshot_on_change", True))
        shot_min = float(screen_cfg.get("screenshot_min_interval_sec", 90))

        self.screen_watcher = ScreenWatcher(
            enabled=always,
            poll_interval_sec=poll,
            screenshot_on_change=on_change,
            screenshot_min_interval_sec=shot_min,
            set_extra=self.context.set_extra,
            get_extra=self.context.get_extra,
        )
        self.light_mode = LightModeController(
            check_interval_sec=25.0,
            pause_seconds=60.0,
        )
        self.light_mode.add_pause_hook(self.automation.pause_for)
        self.light_mode.add_pause_hook(self.screen_watcher.pause_for)

    def set_speak_callback(self, speak: Optional[SpeakFn]) -> None:
        self._speak = speak

    def _on_preference_applied(self, name: str) -> None:
        """Sync session context + bound brain when a name preference is saved."""
        try:
            self.context.update(user_name=name)
        except (AttributeError, KeyError) as e:
            logger.debug("Failed to update context with name preference: %s", e)
            pass
        except Exception as e:
            logger.warning("Unexpected error updating context with name preference: %s", type(e).__name__)
            pass
        brain = getattr(self, "_brain", None)
        if brain is not None:
            try:
                brain.user_name = name
                brain.address = name
            except Exception as e:
                logger.debug("Failed to update brain with name preference: %s", type(e).__name__)

    def bind_brain(self, brain: Any) -> None:
        """Optional Cursor brain for LLM-assisted planning/patch (offline-safe if missing)."""
        self._brain = brain
        try:
            self.llm.bind_brain(brain)
            self.planner.set_llm_refine(make_llm_refine(self.llm))
            patch = self.tools.get("dev.apply_patch")
            if patch is not None and hasattr(patch, "set_llm"):
                patch.set_llm(self.llm)
        except Exception as e:
            logger.warning("bind_brain failed: %s", type(e).__name__)

    def start_background(self) -> None:
        """Start automation scheduler + screen watcher + light-mode guard."""
        try:
            self.automation.start()
            self._ensure_default_briefing_automation()
        except Exception as e:
            logger.warning("Failed to start automation scheduler: %s", type(e).__name__)
        try:
            if self.screen_watcher is not None:
                self.screen_watcher.start()
        except Exception as e:
            logger.warning("Failed to start screen watcher: %s", type(e).__name__)
        try:
            if self.light_mode is not None:
                self.light_mode.start()
        except Exception as e:
            logger.warning("Failed to start light-mode controller: %s", type(e).__name__)

    def classify_brain(self, command: str) -> BrainPath:
        """Public Fast vs Deep hint for observability / callers."""
        decision = self.brain_router.decide(command)
        self._last_brain_path = decision.path.value
        try:
            from core.request_context import get_request_id

            self.cost_meter.record(
                command,
                brain_path=decision.path.value,
                request_id=get_request_id(),
            )
        except Exception as e:
            logger.debug("Cost metering failed in classify_brain: %s", type(e).__name__)
        return decision.path

    def _build_decision_context(self) -> Any:
        snap = self.context.snapshot()
        extras = snap.get("extras") or {}
        recent = [
            str(t.get("command") or "")
            for t in (snap.get("recent_turns") or [])
            if t.get("command")
        ]
        screen = ""
        try:
            screen = str(self._screen_context() or "")[:200]
        except Exception as e:
            logger.debug("Failed to get screen context: %s", type(e).__name__)
            screen = ""
        return decision_context_from_session(
            last_command=str(snap.get("last_command") or ""),
            last_response=str(snap.get("last_response") or ""),
            last_entity=str(snap.get("last_entity") or extras.get("last_entity") or ""),
            last_opened_app=str(extras.get("last_opened_app") or ""),
            active_topic=str(extras.get("active_topic") or ""),
            recent_user_turns=recent,
            screen_summary=screen,
        )

    def try_handle_command(self, command: str) -> Optional[str]:
        """Route NL command through tools; None = fall through to brain/legacy.

        DecisionEngine judges first (clarify / rewrite / assume), then FastBrain tools.
        """
        try:
            resolved = self.context.resolve_followup(command)
            judgment = self.decision_engine.decide(
                resolved, self._build_decision_context()
            )
            self._last_decision_rationale = judgment.rationale or ""
            if judgment.needs_clarification and judgment.clarification:
                self.context.record_turn(resolved, judgment.clarification)
                print(f"🧠 Clarify: {judgment.clarification}")
                return judgment.clarification

            resolved = judgment.rewritten or resolved
            if judgment.autonomous and judgment.speak_preamble:
                print(f"🧠 Decision: {judgment.speak_preamble}")

            decision = self.brain_router.decide(resolved)
            self._last_brain_path = decision.path.value
            try:
                from core.request_context import get_request_id, set_brain_path

                set_brain_path(decision.path.value)
                self.cost_meter.record(
                    resolved,
                    brain_path=decision.path.value,
                    request_id=get_request_id(),
                )
            except Exception as e:
                logger.debug("Failed to record metrics in try_handle_command: %s", type(e).__name__)
            if decision.path is BrainPath.DEEP or decision.match is None:
                # Stash judgment for DeepBrain prompt enrichment
                self.context.set_extra("pending_decision", {
                    "mode": judgment.mode.value,
                    "rationale": judgment.rationale,
                    "rewritten": resolved,
                    "original": judgment.original,
                })
                return None
            match = decision.match
            tool = match.request.tool_name
            args = dict(match.request.arguments)
            if tool == "media.play" and judgment.tool_overrides:
                args.update(judgment.tool_overrides)
            print(f"🔧 FastBrain: {tool} {args} ({decision.reason})")
            logger.info("fast brain tool: %s %s (%s)", tool, args, decision.reason)
            if tool == "plan.run":
                goal = str(args.get("goal") or resolved)
                background = bool(args.get("background", False))
                speech = self._run_plan_goal(goal, background=background)
                if judgment.speak_preamble:
                    speech = f"{judgment.speak_preamble} {speech}".strip()
                self.context.record_turn(resolved, speech)
                print(f"✅ Plan sonucu: {speech[:120]}")
                return speech
            result = self.execution.execute(ExecutionRequest(tool, args))
            if result.ok:
                speech = claim_safe_speech(result)
                if judgment.speak_preamble and judgment.autonomous:
                    # Avoid double-speaking rationale if tool already included it
                    if judgment.speak_preamble[:40] not in speech:
                        speech = f"{judgment.speak_preamble} {speech}".strip()
                print(f"✅ Araç çalıştı: {tool} → {speech[:120]}")
                if tool == "system.open_app":
                    self.context.record_open_action(
                        kind="open_app",
                        name=str(args.get("name") or ""),
                    )
                elif tool == "browser.open_url":
                    self.context.record_open_action(
                        kind="open_url",
                        url=str(args.get("url") or ""),
                        name="browser",
                    )
            else:
                from voice.speech_clean import speak_safe

                speech = speak_safe(
                    claim_safe_speech(result),
                    language="en-GB",
                )
                print(f"❌ Araç hata: {tool} → {speech[:120]}")
            self.context.record_turn(resolved, speech)
            return speech
        except Exception as err:
            logger.exception("try_handle_command failed")
            return f"Something went wrong: {err}"

    def run_research_agent(self, query: str, *, background: bool = True) -> str:
        """Allowlisted research plan — short ack when background."""
        plan = research_plan(query, max_steps=int(getattr(self.planner, "max_steps", 4)))
        plan = filter_plan_steps(plan, "research")
        if not plan.steps:
            return "No suitable tools for research."
        if background:
            def _done(result: Any) -> None:
                if self._speak and result.speech:
                    try:
                        self._speak(str(result.speech)[:280])
                    except Exception as e:
                        logger.warning("Research agent notify failed: %s", type(e).__name__)

            self.execution.execute_plan_background(plan, on_done=_done)
            return f"Researching: {query[:80]}. I'll report when done."
        result = self.execution.execute_plan(plan)
        return result.speech if result.ok else (result.stopped_reason or "Research failed.")

    def run_coding_analyze_agent(self, *, background: bool = True) -> str:
        """Allowlisted coding analyze — prefers background + notify."""
        plan = coding_analyze_plan(max_steps=int(getattr(self.planner, "max_steps", 4)))
        plan = filter_plan_steps(plan, "coding")
        if not plan.steps:
            return "No suitable tools for code analysis."
        if background:
            def _done(result: Any) -> None:
                if self._speak and result.speech:
                    try:
                        self._speak(str(result.speech)[:280])
                    except Exception as e:
                        logger.warning("Coding agent notify failed: %s", type(e).__name__)

            self.execution.execute_plan_background(plan, on_done=_done)
            return "Analysing the project in the background. I'll summarise when done."
        result = self.execution.execute_plan(plan)
        return result.speech if result.ok else (result.stopped_reason or "Analysis failed.")

    def _run_plan_goal(self, goal: str, *, background: bool = False) -> str:
        from core.agent_loop import run_agent_loop
        from core.agent_profiles import looks_like_coding_analyze, looks_like_research_agent

        # Long analyze / research → always background + short ack
        if looks_like_coding_analyze(goal) or looks_like_research_agent(goal):
            background = True
        return run_agent_loop(
            self,
            goal,
            max_iterations=self.deep_max_iterations,
            background=background or False,
        )

    def recall_for_prompt(self, query: str) -> str:
        """Relevant profile + episodic + semantic memories — not a full dump."""
        q = (query or "").strip()
        if not q:
            return ""
        skip_semantic = bool(self.light_mode and self.light_mode.active)
        try:
            block = self.memory_layers.retrieve_for_prompt(
                q,
                profile_limit=4,
                episodic_limit=2,
                semantic_limit=self.recall_limit,
                max_chars=self.recall_max_chars + 80,
                skip_semantic=skip_semantic,
            )
        except Exception as e:
            logger.warning("Layered recall failed: %s", type(e).__name__)
            block = ""
        screen_line = self._screen_prompt_line()
        decision_line = ""
        pending = self.context.get_extra("pending_decision")
        if isinstance(pending, dict) and pending:
            mode = pending.get("mode") or ""
            rationale = pending.get("rationale") or ""
            rewritten = pending.get("rewritten") or ""
            original = pending.get("original") or ""
            decision_line = (
                f"[DECISION ENGINE] mode={mode}. "
                f"Original: «{original}». "
                f"Acting on: «{rewritten}». "
                f"{rationale} "
                "Continue this judgment — do not restart the topic."
            )
            # one-shot
            self.context.set_extra("pending_decision", None)
        parts = [p for p in (decision_line, screen_line, block) if p]
        if not parts:
            return ""
        out = "\n".join(parts)
        if len(out) > self.recall_max_chars + 180:
            out = out[: self.recall_max_chars + 180].rsplit("\n", 1)[0] + "\n- …"
        return out

    def _screen_prompt_line(self) -> str:
        ctx = self._screen_context()
        if not ctx.get("ok"):
            return ""
        summary = str(ctx.get("summary") or "").strip()
        if not summary:
            app = str(ctx.get("app") or "").strip()
            title = str(ctx.get("title") or "").strip()
            if not app:
                return ""
            summary = f"Ön planda {app}" + (f" («{title}»)" if title else "") + "."
        return f"[SCREEN — live] {summary}"

    def ingest_conversation(self, user_text: str, assistant_text: str = "") -> list[int]:
        """Extract preferences + optional episodic note from a turn."""
        # Session opt-out: «bu konuşmayı hatırlama»
        try:
            if hasattr(self, "state") and not self.state.memory_capture:
                return []
            if self.context.get_extra("memory_capture") is False:
                return []
        except (AttributeError, KeyError) as e:
            logger.debug("Memory capture check failed: %s", e)
            pass
        except Exception as e:
            logger.warning("Unexpected error in memory capture check: %s", type(e).__name__)
            pass
        ids: list[int] = []
        try:
            ids = extract_and_save(self.memory, user_text, assistant_text)
        except Exception as e:
            logger.warning("Memory extraction failed: %s", type(e).__name__)
        try:
            if not is_trivial_utterance(user_text) and len((user_text or "").strip()) >= 24:
                from memory.extractor import is_name_preference_command

                if not is_name_preference_command(user_text):
                    snippet = (user_text or "").strip()[:200]
                    if assistant_text:
                        snippet = f"User: {snippet}"
                    mem = self.memory_layers.record_episodic(snippet, importance=2)
                    if mem is not None:
                        ids.append(mem.id)
        except Exception as e:
            logger.warning("Episodic record failed: %s", type(e).__name__)
        try:
            profile = self.memory_layers.get_profile()
            name = profile.display_name()
            if name:
                self.context.update(user_name=name)
                self.context.set_extra(
                    "user_profile_summary",
                    profile.summary_lines(max_items=4),
                )
        except (AttributeError, KeyError) as e:
            logger.debug("Profile update failed: %s", e)
            pass
        except Exception as e:
            logger.warning("Unexpected error in profile update: %s", type(e).__name__)
            pass
        return ids

    def set_memory_capture(self, enabled: bool) -> str:
        """User control: persist or skip long-term memory for this session."""
        self.state.set_memory_capture(enabled)
        if enabled:
            return "Understood — I'll remember important things from this session."
        return "Understood — I won't save this conversation to long-term memory."

    def security_profile(self) -> dict[str, Any]:
        """Honest snapshot of autonomy / confirm gates (for docs + diagnostics)."""
        return {
            "full_autonomy": bool(self.full_autonomy),
            "auto_approve_level_0_1_2": bool(self.auto_approve_level_0_1_2),
            "auto_approve_dangerous": bool(
                getattr(self.confirmation, "auto_approve", False)
            ),
            "max_permission_level": int(self.permissions.max_level),
            "confirm_pending": self.state.pending_confirmations,
            "note": (
                "When full_autonomy/auto_approve_dangerous is false, Level-3 "
                "requires HUD/voice confirmation. Catastrophic shell patterns "
                "remain hard-blocked either way. loader DEFAULT_JARVIS2 uses "
                "full_autonomy=false; config.yaml may override to true for "
                "personal single-user machines."
            ),
        }

    def _handle_automation_action(
        self,
        action: dict[str, Any],
        rule: AutomationRule,
    ) -> Optional[str]:
        atype = str(action.get("type") or "briefing").lower()
        force = bool(action.get("force"))
        if atype == "briefing":
            briefing = self.briefing.generate()
            text = briefing.voice
            self._maybe_speak(text, force=force)
            return text
        if atype == "remind_tasks":
            briefing = self.briefing.generate()
            text = briefing.voice
            if briefing.detail and "Overdue" in briefing.detail:
                text = briefing.voice
            self._maybe_speak(text, force=force)
            return text
        if atype == "speak":
            text = str(action.get("text") or f"Automation {rule.name}.").strip()
            event = action.get("_event") or {}
            if "{file}" in text and event.get("file_name"):
                text = text.replace("{file}", str(event["file_name"]))
            self._maybe_speak(text, force=force)
            return text
        if atype == "tool":
            name = str(action.get("name") or "")
            args = action.get("args") or {}
            if not name:
                return "Automation tool action missing name."
            result = self.execution.execute(ExecutionRequest(name, args, requested_by="automation"))
            text = result.data if result.ok and isinstance(result.data, str) else (
                result.error or "Tool action failed."
            )
            self._maybe_speak(str(text)[:200], force=force)
            return str(text)[:280]
        return f"Unknown automation action: {atype}"

    def _maybe_speak(self, text: str, *, force: bool = False) -> None:
        if not text or not self.proactive_enabled:
            return
        if not self.notifier.allow(force=force):
            return
        if self._speak:
            try:
                self._speak(text)
            except Exception as e:
                logger.warning("Proactive speak failed: %s", type(e).__name__)

    def _ensure_default_briefing_automation(self) -> None:
        """Optionally seed a daily briefing rule from config (idempotent by name)."""
        j2 = self.config.get("jarvis2", {})
        proactive = j2.get("proactive") or {}
        if not proactive.get("seed_daily_briefing", False):
            return
        name = "Daily briefing"
        existing = [r for r in self.automation.list_rules() if r.name == name]
        if existing:
            return
        hour = int(proactive.get("daily_briefing_hour", 9))
        minute = int(proactive.get("daily_briefing_minute", 0))
        self.automation.create_rule(
            name,
            trigger_type="daily",
            trigger_spec={"kind": "daily", "hour": hour, "minute": minute},
            action_spec={"type": "briefing"},
            enabled=True,
        )

    def _on_automation_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.bus.publish(event_type, payload, source="automation")
        try:
            import json
            from datetime import datetime, timezone

            self.db.execute(
                "INSERT INTO events (event_type, source, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    event_type,
                    "automation",
                    json.dumps(payload, default=str),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self.db.commit()
        except Exception as e:
            logger.warning("Failed to persist automation event: %s", type(e).__name__)

    def _on_automation_audit(
        self,
        *,
        action: str,
        level: int,
        success: bool,
        details: dict[str, Any],
    ) -> None:
        self.audit.write(action=action, level=level, success=success, details=details)

    def close(self) -> None:
        try:
            if self.light_mode is not None:
                self.light_mode.stop()
        except Exception as e:
            logger.debug("Failed to stop light mode: %s", type(e).__name__)
        try:
            if self.screen_watcher is not None:
                self.screen_watcher.stop()
        except Exception as e:
            logger.debug("Failed to stop screen watcher: %s", type(e).__name__)
        try:
            self.automation.stop()
        except Exception as e:
            logger.debug("Failed to stop automation: %s", type(e).__name__)
        try:
            self.mcp.close_all()
        except Exception as e:
            logger.debug("Failed to close MCP connections: %s", type(e).__name__)
        try:
            self.bus.publish("os.shutdown", {}, source="jarvis_os")
        except Exception as e:
            logger.debug("Failed to publish shutdown event: %s", type(e).__name__)
        self.db.close()
        self._ready = False


def re_split_tokens(text: str) -> list[str]:
    import re

    return [t.lower() for t in re.findall(r"[a-zA-ZğüşıöçĞÜŞİÖÇ0-9]+", text)]


def try_create_os(
    config: dict[str, Any],
    *,
    root: Optional[Path] = None,
    macos: Optional[MacOSController] = None,
) -> Optional[JarvisOS]:
    """Soft-init helper: returns None on failure so legacy path still works."""
    j2 = config.get("jarvis2", {})
    if not j2.get("enabled", True):
        print("ℹ️  JARVIS 2.0 core disabled (jarvis2.enabled=false)")
        return None
    try:
        os_core = JarvisOS(config, root=root, macos=macos)
        health = os_core.health()
        status = "OK" if health["ok"] else "DEGRADED"
        print(
            f"🧠 JARVIS 2.0 core: {status} "
            f"({health['passed']}/{health['total']} checks)"
        )
        return os_core
    except Exception as err:
        print(f"⚠️  JARVIS 2.0 core init failed (legacy path continues): {err}")
        logger.exception("JarvisOS init failed")
        return None
