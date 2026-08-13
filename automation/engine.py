"""Automation engine — CRUD, background scheduler, action dispatch."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from automation.parser import ParsedAutomation, parse_automation_nl
from automation.triggers import fire_key, parse_trigger_spec, should_fire
from automation.watchers import FileWatchService
from memory.database import Database

logger = logging.getLogger(__name__)

SpeakFn = Callable[[str], None]
ActionHandler = Callable[[dict[str, Any], "AutomationRule"], Optional[str]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_now() -> datetime:
    return datetime.now().astimezone()


@dataclass
class AutomationRule:
    id: int
    name: str
    trigger_type: str
    trigger_spec: str
    action_spec: str
    enabled: bool
    last_fired_at: Optional[str] = None
    fail_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    def trigger(self) -> dict[str, Any]:
        return parse_trigger_spec(self.trigger_spec)

    def action(self) -> dict[str, Any]:
        return parse_trigger_spec(self.action_spec)


class AutomationEngine:
    """Persist and schedule automations without blocking the voice thread."""

    def __init__(
        self,
        db: Database,
        *,
        enabled: bool = False,
        tick_seconds: float = 30.0,
        max_failures: int = 3,
        action_handler: Optional[ActionHandler] = None,
        on_event: Optional[Callable[[str, dict[str, Any]], None]] = None,
        on_audit: Optional[Callable[..., None]] = None,
    ) -> None:
        self._db = db
        self.enabled = enabled
        self.tick_seconds = max(5.0, float(tick_seconds))
        self.max_failures = max(1, int(max_failures))
        self._action_handler = action_handler
        self._on_event = on_event
        self._on_audit = on_audit
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self.file_watch = FileWatchService()

    # --- CRUD ---

    def rule_count(self) -> int:
        row = self._db.fetchone("SELECT COUNT(*) AS c FROM automations")
        return int(row["c"]) if row else 0

    def create_rule(
        self,
        name: str,
        *,
        trigger_type: str = "manual",
        trigger_spec: str | dict[str, Any] = "{}",
        action_spec: str | dict[str, Any] = "{}",
        enabled: bool = True,
    ) -> int:
        now = _utc_now()
        tspec = trigger_spec if isinstance(trigger_spec, str) else json.dumps(trigger_spec)
        aspec = action_spec if isinstance(action_spec, str) else json.dumps(action_spec)
        cursor = self._db.execute(
            """
            INSERT INTO automations
                (name, trigger_type, trigger_spec, action_spec, enabled,
                 last_fired_at, fail_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, NULL, 0, ?, ?)
            """,
            (name, trigger_type, tspec, aspec, 1 if enabled else 0, now, now),
        )
        self._db.commit()
        rule_id = int(cursor.lastrowid)
        self._emit("automation.created", {"id": rule_id, "name": name})
        self._audit("automation.create", True, {"id": rule_id, "name": name})
        return rule_id

    def create_from_nl(self, text: str) -> Optional[AutomationRule]:
        parsed = parse_automation_nl(text)
        if parsed is None:
            return None
        rule_id = self.create_rule(
            parsed.name,
            trigger_type=parsed.trigger_type,
            trigger_spec=parsed.trigger_spec,
            action_spec=parsed.action_spec,
            enabled=parsed.enabled,
        )
        return self.get_rule(rule_id)

    def get_rule(self, rule_id: int) -> AutomationRule:
        row = self._db.fetchone("SELECT * FROM automations WHERE id = ?", (rule_id,))
        if row is None:
            raise KeyError(f"Automation not found: {rule_id}")
        return self._from_row(row)

    def list_rules(self, *, enabled_only: bool = False) -> list[AutomationRule]:
        if enabled_only:
            rows = self._db.fetchall(
                "SELECT * FROM automations WHERE enabled = 1 ORDER BY id"
            )
        else:
            rows = self._db.fetchall("SELECT * FROM automations ORDER BY id")
        return [self._from_row(r) for r in rows]

    def set_enabled(self, rule_id: int, enabled: bool) -> AutomationRule:
        self.get_rule(rule_id)
        self._db.execute(
            "UPDATE automations SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, _utc_now(), rule_id),
        )
        self._db.commit()
        self._audit(
            "automation.enable" if enabled else "automation.disable",
            True,
            {"id": rule_id},
        )
        return self.get_rule(rule_id)

    def delete_rule(self, rule_id: int) -> None:
        self.get_rule(rule_id)
        self._db.execute("DELETE FROM automations WHERE id = ?", (rule_id,))
        self._db.commit()
        self._emit("automation.deleted", {"id": rule_id})
        self._audit("automation.delete", True, {"id": rule_id})

    # --- Scheduler ---

    def start(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="jarvis-automation",
                daemon=True,
            )
            self._thread.start()
            logger.info("Automation scheduler started (tick=%ss)", self.tick_seconds)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("Automation tick failed (voice loop unaffected)")
            self._stop.wait(self.tick_seconds)

    def tick(self, now: Optional[datetime] = None) -> list[dict[str, Any]]:
        """Evaluate triggers once. Safe to call from tests."""
        if not self.enabled:
            return []
        now = now or _local_now()
        fired: list[dict[str, Any]] = []
        for rule in self.list_rules(enabled_only=True):
            if rule.fail_count >= self.max_failures:
                continue
            trigger = rule.trigger()
            kind = str(trigger.get("kind") or "").lower()
            if kind == "file_watch":
                try:
                    events = self.file_watch.poll(rule.id, trigger)
                except Exception:
                    logger.exception("file_watch poll failed for rule %s", rule.id)
                    continue
                for event in events:
                    # Inject file context into action for speak/tool
                    result = self._run_rule(
                        rule,
                        now=now,
                        force=True,
                        event_context={
                            "file_path": event.path,
                            "file_name": event.name,
                            "trigger": "file_watch",
                        },
                    )
                    fired.append(result)
                continue
            if not should_fire(trigger, now, last_fired_at=rule.last_fired_at):
                continue
            result = self._run_rule(rule, now=now)
            fired.append(result)
        return fired

    def run_rule_now(self, rule_id: int) -> dict[str, Any]:
        rule = self.get_rule(rule_id)
        return self._run_rule(rule, now=_local_now(), force=True)

    def _run_rule(
        self,
        rule: AutomationRule,
        *,
        now: datetime,
        force: bool = False,
        event_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        slot = fire_key(now)
        if event_context and event_context.get("file_path"):
            # Unique slot per file so multiple files can fire same minute
            slot = f"{slot}:{event_context.get('file_name')}"
        speech: Optional[str] = None
        ok = True
        error: Optional[str] = None
        try:
            action = rule.action()
            if event_context:
                # Shallow merge context for handlers
                action = dict(action)
                action["_event"] = event_context
                if action.get("type") == "speak" and "{file}" in str(action.get("text") or ""):
                    action["text"] = str(action["text"]).replace(
                        "{file}", str(event_context.get("file_name") or "")
                    )
            if self._action_handler:
                speech = self._action_handler(action, rule)
            else:
                speech = f"Automation {rule.name} fired."
            self._mark_fired(rule.id, slot, success=True)
            self._emit(
                "automation.fired",
                {
                    "id": rule.id,
                    "name": rule.name,
                    "action": action,
                    "force": force,
                    "event": event_context,
                },
            )
            self._audit(
                "automation.fire",
                True,
                {"id": rule.id, "name": rule.name, "action": action, "event": event_context},
            )
        except Exception as err:
            ok = False
            error = str(err)
            logger.exception("Automation %s failed", rule.id)
            self._mark_fired(rule.id, slot, success=False)
            self._emit(
                "automation.failed",
                {"id": rule.id, "error": error},
            )
            self._audit(
                "automation.fire",
                False,
                {"id": rule.id, "error": error},
            )
        return {
            "id": rule.id,
            "ok": ok,
            "speech": speech,
            "error": error,
            "slot": slot,
        }

    def _mark_fired(self, rule_id: int, slot: str, *, success: bool) -> None:
        if success:
            self._db.execute(
                """
                UPDATE automations
                SET last_fired_at = ?, fail_count = 0, updated_at = ?
                WHERE id = ?
                """,
                (slot, _utc_now(), rule_id),
            )
        else:
            self._db.execute(
                """
                UPDATE automations
                SET last_fired_at = ?, fail_count = fail_count + 1, updated_at = ?
                WHERE id = ?
                """,
                (slot, _utc_now(), rule_id),
            )
        self._db.commit()

    def set_action_handler(self, handler: ActionHandler) -> None:
        self._action_handler = handler

    @staticmethod
    def _from_row(row: Any) -> AutomationRule:
        # Compatibility if migration not applied yet
        keys = row.keys() if hasattr(row, "keys") else []
        last = row["last_fired_at"] if "last_fired_at" in keys else None
        fails = int(row["fail_count"]) if "fail_count" in keys else 0
        return AutomationRule(
            id=int(row["id"]),
            name=row["name"],
            trigger_type=row["trigger_type"],
            trigger_spec=row["trigger_spec"] or "{}",
            action_spec=row["action_spec"] or "{}",
            enabled=bool(row["enabled"]),
            last_fired_at=last,
            fail_count=fails,
            created_at=row["created_at"] if "created_at" in keys else "",
            updated_at=row["updated_at"] if "updated_at" in keys else "",
        )

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._on_event:
            try:
                self._on_event(event_type, payload)
            except Exception:
                logger.exception("automation event callback failed")

    def _audit(self, action: str, success: bool, details: dict[str, Any]) -> None:
        if self._on_audit:
            try:
                self._on_audit(action=action, level=1, success=success, details=details)
            except Exception:
                logger.exception("automation audit callback failed")
