"""Automation + briefing tools."""

from __future__ import annotations

from typing import Any, Callable, Optional

from automation.engine import AutomationEngine
from automation.parser import parse_automation_nl
from proactive.briefing import BriefingGenerator
from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult


class AutomationCreateTool(BaseTool):
    name = "automation.create"
    description = "Create an automation from natural language or structured fields"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"text": {"type": "str", "required": False}}

    def __init__(self, engine: AutomationEngine) -> None:
        self._engine = engine

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        text = str(arguments.get("text") or "").strip()
        if text:
            rule = self._engine.create_from_nl(text)
            if rule is None:
                return ToolResult(
                    ok=False,
                    error=(
                        "Could not parse automation. Try: every morning briefing "
                        "or «İndirilenlere PDF gelince söyle …»"
                    ),
                )
            return ToolResult(
                ok=True,
                data=f"Automation #{rule.id} scheduled: {rule.name}.",
            )
        name = str(arguments.get("name") or "").strip()
        if not name:
            return ToolResult(ok=False, error="text or name required")
        trigger = arguments.get("trigger_spec") or {"kind": "daily", "hour": 9, "minute": 0}
        action = arguments.get("action_spec") or {"type": "briefing"}
        rule_id = self._engine.create_rule(
            name,
            trigger_type=str(arguments.get("trigger_type") or "daily"),
            trigger_spec=trigger,
            action_spec=action,
            enabled=bool(arguments.get("enabled", True)),
        )
        return ToolResult(ok=True, data=f"Automation #{rule_id} created: {name}.")


class AutomationListTool(BaseTool):
    name = "automation.list"
    description = "List automations"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, engine: AutomationEngine) -> None:
        self._engine = engine

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        rules = self._engine.list_rules()
        if not rules:
            return ToolResult(ok=True, data="No automations.")
        parts = [
            f"#{r.id} [{'on' if r.enabled else 'off'}] {r.name}"
            for r in rules
        ]
        text = "; ".join(parts)
        if len(text) > 220:
            text = text[:220] + "…"
        return ToolResult(ok=True, data=f"Automations: {text}")


class AutomationEnableTool(BaseTool):
    name = "automation.enable"
    description = "Enable an automation by id"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"rule_id": {"type": "int", "required": True}}

    def __init__(self, engine: AutomationEngine) -> None:
        self._engine = engine

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            rule = self._engine.set_enabled(int(arguments["rule_id"]), True)
        except (KeyError, TypeError, ValueError):
            return ToolResult(ok=False, error="Automation not found")
        return ToolResult(ok=True, data=f"Automation #{rule.id} enabled.")


class AutomationDisableTool(BaseTool):
    name = "automation.disable"
    description = "Disable an automation by id"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"rule_id": {"type": "int", "required": True}}

    def __init__(self, engine: AutomationEngine) -> None:
        self._engine = engine

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            rule = self._engine.set_enabled(int(arguments["rule_id"]), False)
        except (KeyError, TypeError, ValueError):
            return ToolResult(ok=False, error="Automation not found")
        return ToolResult(ok=True, data=f"Automation #{rule.id} disabled.")


class AutomationDeleteTool(BaseTool):
    name = "automation.delete"
    description = "Delete an automation by id"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {"rule_id": {"type": "int", "required": True}}

    def __init__(self, engine: AutomationEngine) -> None:
        self._engine = engine

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            rid = int(arguments["rule_id"])
            self._engine.delete_rule(rid)
        except (KeyError, TypeError, ValueError):
            return ToolResult(ok=False, error="Automation not found")
        return ToolResult(ok=True, data=f"Automation #{rid} deleted.")


class AutomationRunTool(BaseTool):
    name = "automation.run"
    description = "Run an automation immediately"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"rule_id": {"type": "int", "required": True}}

    def __init__(self, engine: AutomationEngine) -> None:
        self._engine = engine

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            result = self._engine.run_rule_now(int(arguments["rule_id"]))
        except (KeyError, TypeError, ValueError):
            return ToolResult(ok=False, error="Automation not found")
        if not result.get("ok"):
            return ToolResult(ok=False, error=result.get("error") or "Run failed")
        speech = result.get("speech") or "Automation complete."
        return ToolResult(ok=True, data=speech)


class BriefingTool(BaseTool):
    name = "proactive.briefing"
    description = "Generate a short daily briefing from local data"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(
        self,
        generator: BriefingGenerator,
        *,
        include_detail: bool = False,
    ) -> None:
        self._gen = generator
        self._include_detail = include_detail

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        detail = bool(arguments.get("detail", self._include_detail))
        briefing = self._gen.generate()
        if detail:
            text = f"{briefing.voice} {briefing.detail}"
            if len(text) > 280:
                text = text[:280] + "…"
            return ToolResult(ok=True, data=text)
        return ToolResult(ok=True, data=briefing.voice)


class SuggestionsTool(BaseTool):
    name = "proactive.suggestions"
    description = "Contextual proactive suggestions based on tasks and session state"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, runner: Any) -> None:
        self._runner = runner

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        last_command = str(arguments.get("last_command") or "").strip()
        try:
            speech = self._runner(last_command=last_command)
        except Exception as err:
            return ToolResult(ok=False, error=str(err))
        return ToolResult(ok=True, data=speech)
