"""Thin JARVIS 2.0 OS facade — additive, does not replace JarvisCore."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from automation.engine import AutomationEngine, AutomationRule
from brain.llm_provider import CursorProvider, build_default_router
from core.backup import BackupService
from core.command_router import CommandRouter
from core.context_manager import ContextManager, SessionContext
from core.diagnostics import SelfDiagnostics
from core.event_bus import EventBus
from core.execution_engine import ExecutionEngine, ExecutionRequest
from core.planner import Planner, make_llm_refine
from core.task_manager import TaskManager
from integrations.mcp_adapter import MCPAdapter
from memory.database import Database
from memory.extractor import extract_and_save
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

        self.bus = EventBus()
        self.context = ContextManager(
            SessionContext(
                user_name=jarvis_cfg.get("user_name", "sir"),
                language=jarvis_cfg.get("language", "en-GB"),
                model=jarvis_cfg.get("model", "gemini-3-flash"),
            )
        )
        self.db = Database(self.db_path)
        self.db.migrate()
        self.memory = MemoryRepository(self.db)
        self.tasks = TaskManager(self.db)
        self.permissions = PermissionGate(PermissionLevel(max_level))
        self.confirmation = ConfirmationGate(
            auto_approve=bool(j2.get("auto_approve_dangerous", False)),
            default_timeout=float(j2.get("confirm_timeout", 60)),
        )
        self.audit = AuditLog(self.db)
        self.macos = macos or MacOSController(
            full_shell_access=sys_cfg.get("full_shell_access", True),
        )
        self._speak: Optional[SpeakFn] = None
        self._level_notify: Optional[Callable[[int, str, dict[str, Any]], None]] = None
        self._confirm_pending_ui: Optional[Callable[[Any], None]] = None

        self.briefing = BriefingGenerator(
            self.tasks,
            self.memory,
            self.db,
            user_name=jarvis_cfg.get("user_name", "sir"),
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
            except Exception:
                pass

        backup_retention = int(j2.get("backup_retention", 10))
        self.backup = BackupService(
            db_path=self.db_path,
            root=self.root,
            backup_dir=self.root / "data" / "backups",
            retention=backup_retention,
        )
        models = jarvis_cfg.get("models") or {}
        default_model = str(jarvis_cfg.get("model") or "gemini-3-flash")
        self.model_router = build_default_router(models, default_model)
        self.llm = CursorProvider(brain=None, router=self.model_router)
        self.mcp = MCPAdapter()
        self.planner = Planner(llm_refine=make_llm_refine(self.llm))
        max_retries = int(j2.get("plan_max_retries", 1))
        tool_max_retries = int(j2.get("tool_max_retries", 3))

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
        )
        # Optional plugins (Phase 3) — failures isolated
        try:
            from tools.packages import load_plugins

            load_plugins(
                self.tools,
                {"root": str(self.root), "config": self.config},
            )
        except Exception:
            logger.exception("plugin load failed (isolated)")
        # Live MCP — connect configured servers after local tools exist
        mcp_cfg = j2.get("mcp") or {}
        if bool(mcp_cfg.get("enabled", True)):
            servers = mcp_cfg.get("servers") or []
            if servers:
                try:
                    self.mcp.connect_servers(servers, self.tools)
                except Exception:
                    logger.exception("MCP connect_servers failed (isolated)")
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
            tool_max_retries=tool_max_retries,
            working_dir=self.projects.working_dir,
            tasks=self.tasks,
        )
        self.router = CommandRouter()
        self.diagnostics = SelfDiagnostics(self)
        self.recall_limit = int(j2.get("memory_recall_limit", 4))
        self.recall_max_chars = int(j2.get("memory_recall_max_chars", 400))
        self.proactive_enabled = bool(proactive_cfg.get("enabled", True))
        self.plan_speech_min_interval = float(j2.get("plan_speech_min_interval", 8.0))
        self._last_plan_speech_at: float = 0.0
        self._ready = True
        self._last_turn = None
        self._last_complexity = None
        self._last_request_id = None
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
            except Exception:
                pass
        if self._confirm_pending_ui:
            self._confirm_pending_ui(pending)

    def _on_level_notify(self, level: int, tool: str, args: dict[str, Any]) -> None:
        if self._level_notify:
            try:
                self._level_notify(level, tool, args)
            except Exception:
                logger.exception("UI level notify failed")

    def command_center(self) -> dict[str, Any]:
        from ui.hud_data import build_command_center

        return build_command_center(self)

    @property
    def ready(self) -> bool:
        return self._ready

    def health(self) -> dict[str, Any]:
        return self.diagnostics.summary()

    def set_speak_callback(self, speak: Optional[SpeakFn]) -> None:
        self._speak = speak

    def bind_brain(self, brain: Any) -> None:
        """Optional Cursor brain for LLM-assisted planning/patch (offline-safe if missing)."""
        try:
            self.llm.bind_brain(brain)
            self.planner.set_llm_refine(make_llm_refine(self.llm))
            patch = self.tools.get("dev.apply_patch")
            if patch is not None and hasattr(patch, "set_llm"):
                patch.set_llm(self.llm)
        except Exception:
            logger.exception("bind_brain failed")

    def start_background(self) -> None:
        """Start automation scheduler (daemon). Safe if already started."""
        try:
            self._load_automation_packs()
            self.automation.start()
            self._ensure_default_briefing_automation()
        except Exception:
            logger.exception("Failed to start automation scheduler")

    def _load_automation_packs(self) -> None:
        j2 = self.config.get("jarvis2", {})
        packs_rel = j2.get("automation_packs_dir", "config/automation_packs")
        packs_dir = (self.root / str(packs_rel)).resolve()
        try:
            from automation.packs import load_automation_packs

            loaded = load_automation_packs(self.automation, packs_dir)
            if loaded:
                logger.info("automation packs loaded: %s", ", ".join(loaded))
        except Exception:
            logger.exception("automation pack load failed (isolated)")

    def handle_turn(
        self,
        command: str,
        *,
        meta_fn: Optional[Callable[[str], Optional[str]]] = None,
        quick_fn: Optional[Callable[[str], Optional[str]]] = None,
        legacy_fn: Optional[Callable[[str], Optional[str]]] = None,
        request_id: Optional[str] = None,
    ) -> "TurnResult":
        """Single OS entry for one user turn (Phase 2).

        CHAT/SIMPLE never set allow_cursor. Tool/meta/legacy run first.
        """
        from core.complexity import (
            TaskComplexity,
            allows_cursor,
            classify_task_complexity,
            local_fallback_speech,
        )
        from core.request_context import (
            clear_request_id,
            set_brain_path,
            set_request_id,
        )
        from core.turn_result import TurnResult

        rid = set_request_id(request_id)
        complexity = classify_task_complexity(command)
        cursor_ok = allows_cursor(complexity)
        self._last_complexity = complexity
        self._last_request_id = rid

        def _done(
            speech: Optional[str],
            *,
            brain_path: str,
            reason: str,
            allow: Optional[bool] = None,
        ) -> TurnResult:
            allow_c = cursor_ok if allow is None else allow
            # If we already have speech, Cursor is not needed
            if speech is not None:
                allow_c = False
            set_brain_path(brain_path)
            result = TurnResult(
                speech=speech,
                allow_cursor=allow_c and speech is None,
                complexity=complexity,
                request_id=rid,
                brain_path=brain_path,
                reason=reason,
            )
            self._last_turn = result
            try:
                self.audit.write(
                    action="turn.classified",
                    level=0,
                    success=True,
                    details={
                        "complexity": complexity.value,
                        "brain_path": brain_path,
                        "allow_cursor": result.allow_cursor,
                        "reason": reason,
                        "command": (command or "")[:120],
                    },
                )
            except Exception:
                logger.exception("turn audit failed")
            return result

        try:
            # 1) Fast tools
            tool_speech = self.try_handle_command(command)
            if tool_speech is not None:
                return _done(tool_speech, brain_path="fast", reason="tool")

            # 2) Meta / quick (voice preferences, greetings)
            if meta_fn is not None:
                try:
                    meta = meta_fn(command)
                except Exception as err:
                    logger.exception("meta_fn failed")
                    meta = None
                    del err
                if meta:
                    return _done(meta, brain_path="meta", reason="meta")

            if quick_fn is not None:
                try:
                    quick = quick_fn(command)
                except Exception:
                    logger.exception("quick_fn failed")
                    quick = None
                if quick:
                    return _done(quick, brain_path="meta", reason="quick")

            # 3) Legacy macOS heuristics for action-like misses
            if legacy_fn is not None:
                try:
                    legacy = legacy_fn(command)
                except Exception:
                    logger.exception("legacy_fn failed")
                    legacy = None
                if legacy:
                    return _done(legacy, brain_path="legacy", reason="legacy")

            # 4) Cursor gate — degraded mode blocks Cursor (local tools still work)
            from core.degraded import get_degraded_mode

            if not get_degraded_mode().allow_cursor():
                speech = local_fallback_speech(complexity, command)
                if not speech:
                    speech = (
                        "I'm in offline mode — local tools only. "
                        "Try a direct command, or restore the model connection."
                    )
                return _done(
                    speech,
                    brain_path="degraded",
                    reason="degraded_mode",
                    allow=False,
                )

            if not cursor_ok:
                speech = local_fallback_speech(complexity, command)
                return _done(
                    speech,
                    brain_path="blocked",
                    reason=f"gate:{complexity.value}",
                    allow=False,
                )

            return _done(
                None,
                brain_path="deep",
                reason=f"cursor_fallback:{complexity.value}",
                allow=True,
            )
        except Exception as err:
            logger.exception("handle_turn failed")
            from core.recovery import user_safe_speech

            return _done(
                user_safe_speech(str(err)),
                brain_path="blocked",
                reason="error",
                allow=False,
            )
        finally:
            # Keep request_id for nested audit during the turn; clearer clears in main
            pass

    def try_handle_command(self, command: str) -> Optional[str]:
        """Route NL command through tools; None = fall through to brain/legacy.

        Tool/plan failures are isolated — never raise into the voice loop.
        """
        try:
            resolved = self.context.resolve_followup(command)
            match = self.router.route(resolved)
            if match is None:
                return None
            if match.request.tool_name == "plan.run":
                goal = str(match.request.arguments.get("goal") or resolved)
                background = bool(match.request.arguments.get("background", False))
                speech = self._run_plan_goal(goal, background=background)
                self.context.record_turn(resolved, speech)
                return speech
            result = self.execution.execute(match.request)
            if result.ok:
                speech = (
                    result.data.strip()
                    if isinstance(result.data, str) and result.data.strip()
                    else "Done."
                )
            else:
                from voice.speech_clean import speak_safe

                speech = speak_safe(
                    (result.error or "That didn't work.").strip(),
                    language=str(
                        self.config.get("jarvis", {}).get("language", "en-GB")
                    ),
                )
            self.context.record_turn(resolved, speech)
            return speech
        except Exception as err:
            logger.exception("try_handle_command failed")
            from core.recovery import user_safe_speech

            return user_safe_speech(str(err))

    def _run_plan_goal(self, goal: str, *, background: bool = False) -> str:
        plan = self.planner.create(goal)
        if not plan.steps:
            # Not complex enough — fall through hint
            return (
                "That looks like a simple request — try a direct command, "
                "or say «plan and …» for multi-step work."
            )
        if background or len(plan.steps) >= 4:
            def _done(result: Any) -> None:
                self._speak_plan_result(result)

            msg = self.execution.execute_plan_background(plan, on_done=_done)
            preview = plan.summary(max_chars=160)
            return f"{msg} {preview}"
        result = self.execution.execute_plan(plan)
        return result.speech

    def _speak_plan_result(self, result: Any) -> None:
        """Background plan completion speech — throttled short summary (P-02)."""
        import time

        if not self._speak:
            return
        now = time.time()
        if now - self._last_plan_speech_at < self.plan_speech_min_interval:
            logger.info("plan speech throttled (%.1fs gap)", self.plan_speech_min_interval)
            return
        self._last_plan_speech_at = now
        ok = bool(getattr(result, "ok", False))
        completed = int(getattr(result, "completed", 0) or 0)
        total = int(getattr(result, "total", 0) or 0)
        if ok:
            text = f"Plan complete — {completed}/{total} steps."
        else:
            reason = str(getattr(result, "stopped_reason", "") or "stopped")[:120]
            text = f"Plan stopped at {completed}/{total}: {reason}"
        try:
            self._speak(text[:200])
        except Exception:
            logger.exception("plan background speak failed")

    def recall_for_prompt(self, query: str) -> str:
        """Relevant long-term memories for LLM context — hybrid rank, not a dump."""
        from memory.retrieval import format_recall_block, hybrid_retrieve, temporal_query_hours

        q = (query or "").strip()
        if not q:
            return ""
        try:
            ranked = hybrid_retrieve(
                self.memory,
                q,
                limit=self.recall_limit,
                since_hours=temporal_query_hours(q),
            )
            return format_recall_block(ranked, max_chars=self.recall_max_chars)
        except Exception:
            logger.exception("hybrid recall failed — empty context")
            return ""

    def cancel_active_plan(self, reason: str = "user_cancel") -> bool:
        """Cancel in-flight plan (voice «dur» / stop)."""
        try:
            return bool(self.execution.cancel_active_plan(reason))
        except Exception:
            logger.exception("cancel_active_plan failed")
            return False

    def resume_paused_plan(self) -> Optional[str]:
        """Resume a plan paused for Level-3 confirmation."""
        try:
            result = self.execution.resume_paused_plan()
        except Exception:
            logger.exception("resume_paused_plan failed")
            return None
        if result is None:
            return None
        return result.speech

    def enter_degraded_mode(self, reason: str = "model_unavailable") -> None:
        from core.degraded import get_degraded_mode

        get_degraded_mode().enter(reason)
        try:
            self.audit.write(
                action="mode.degraded",
                level=0,
                success=True,
                details={"reason": reason},
            )
        except Exception:
            pass

    def exit_degraded_mode(self) -> None:
        from core.degraded import get_degraded_mode

        get_degraded_mode().exit()

    def ingest_conversation(self, user_text: str, assistant_text: str = "") -> list[int]:
        """Extract and store safe memories from a turn."""
        try:
            return extract_and_save(self.memory, user_text, assistant_text)
        except Exception:
            logger.exception("memory extraction failed")
            return []

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
            except Exception:
                logger.exception("proactive speak failed")

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
        except Exception:
            logger.exception("failed to persist automation event")

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
            self.automation.stop()
        except Exception:
            pass
        try:
            self.mcp.close_all()
        except Exception:
            pass
        try:
            self.bus.publish("os.shutdown", {}, source="jarvis_os")
        except Exception:
            pass
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
