"""Automation package exports."""

from automation.engine import AutomationEngine, AutomationRule
from automation.parser import ParsedAutomation, parse_automation_nl
from automation.triggers import should_fire

__all__ = [
    "AutomationEngine",
    "AutomationRule",
    "ParsedAutomation",
    "parse_automation_nl",
    "should_fire",
]
