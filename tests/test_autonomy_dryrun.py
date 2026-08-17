"""N-01 autonomy · N-02 dry-run · N-03 max_agent_steps · N-05 language."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.app import JarvisOS
from core.autonomy import (
    autonomy_policy,
    clamp_max_agent_steps,
    is_dry_run_request,
    requires_confirmation,
    strip_dry_run_markers,
)
from core.language import check_language_alignment
from core.planner import Plan, PlanStep
from security.permissions import PermissionLevel
from tools.base import StubTool, ToolResult


class AutonomyPolicyTests(unittest.TestCase):
    def test_levels_map_confirm_thresholds(self) -> None:
        self.assertEqual(autonomy_policy(1).confirm_at_or_above, 0)
        self.assertEqual(autonomy_policy(2).confirm_at_or_above, 1)
        self.assertEqual(autonomy_policy(3).confirm_at_or_above, 2)
        self.assertEqual(autonomy_policy(4).confirm_at_or_above, 3)

    def test_level4_auto_approve_dangerous_skips(self) -> None:
        p = autonomy_policy(4)
        self.assertTrue(requires_confirmation(3, p, auto_approve_dangerous=False))
        self.assertFalse(requires_confirmation(3, p, auto_approve_dangerous=True))
        # Lower autonomy never skips via auto_approve_dangerous
        self.assertTrue(
            requires_confirmation(0, autonomy_policy(1), auto_approve_dangerous=True)
        )

    def test_autonomy_level1_blocks_read_without_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {
                    "jarvis2": {
                        "db_path": "data/aut1.db",
                        "autonomy_level": 1,
                        "auto_approve_dangerous": False,
                        "confirm_timeout": 0.15,
                    }
                },
                root=Path(tmp),
            )
            os_core.tools.register(StubTool("demo.read", "r", PermissionLevel.READ))
            from core.execution_engine import ExecutionRequest

            result = os_core.execution.execute(ExecutionRequest("demo.read", {}))
            self.assertFalse(result.ok)
            self.assertIn("confirmation", (result.error or "").lower())
            os_core.close()


class DryRunTests(unittest.TestCase):
    def test_detect_and_strip(self) -> None:
        self.assertTrue(is_dry_run_request("dry run plan and backup"))
        self.assertTrue(is_dry_run_request("ne yapacağını göster: plan and fix"))
        cleaned = strip_dry_run_markers("dry run plan and backup then test")
        self.assertNotIn("dry run", cleaned.lower())

    def test_plan_dry_run_zero_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {
                    "jarvis2": {
                        "db_path": "data/dry.db",
                        "auto_approve_dangerous": True,
                    }
                },
                root=Path(tmp),
            )
            calls: list[str] = []

            class Counting(StubTool):
                def run(self, arguments):  # type: ignore[no-untyped-def]
                    calls.append(self.name)
                    return ToolResult(ok=True, data="ran")

            os_core.tools.register(Counting("demo.a", "a", PermissionLevel.READ))
            speech = os_core._run_plan_goal("dry run plan and analyze and fix cycle")
            self.assertIn("DRY RUN", speech)
            self.assertEqual(calls, [])
            os_core.close()


class MaxAgentStepsTests(unittest.TestCase):
    def test_clamp(self) -> None:
        self.assertEqual(clamp_max_agent_steps(0), 1)
        self.assertEqual(clamp_max_agent_steps(100), 64)
        self.assertEqual(clamp_max_agent_steps("12"), 12)

    def test_plan_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {
                    "jarvis2": {
                        "db_path": "data/steps.db",
                        "max_agent_steps": 2,
                        "auto_approve_dangerous": True,
                    }
                },
                root=Path(tmp),
            )
            calls: list[str] = []

            class Counting(StubTool):
                def run(self, arguments):  # type: ignore[no-untyped-def]
                    calls.append(self.name)
                    return ToolResult(ok=True, data="ok")

            os_core.tools.register(Counting("demo.a", "a", PermissionLevel.READ))
            os_core.tools.register(Counting("demo.b", "b", PermissionLevel.READ))
            os_core.tools.register(Counting("demo.c", "c", PermissionLevel.READ))
            plan = Plan(
                goal="triple",
                steps=[
                    PlanStep("demo.a", {}),
                    PlanStep("demo.b", {}),
                    PlanStep("demo.c", {}),
                ],
            )
            result = os_core.execution.execute_plan(plan)
            self.assertTrue(result.ok)
            self.assertEqual(calls, ["demo.a", "demo.b"])
            self.assertEqual(result.total, 2)
            os_core.close()


class LanguageAlignTests(unittest.TestCase):
    def test_mismatch_warning(self) -> None:
        info = check_language_alignment(
            {
                "jarvis": {"language": "en-GB"},
                "voice": {"listen_language": "tr-TR"},
            }
        )
        self.assertFalse(info.aligned)
        self.assertIn("differ", info.warning)

    def test_dual_locale_complete(self) -> None:
        info = check_language_alignment(
            {
                "jarvis": {"language": "en-GB"},
                "voice": {"listen_language": "tr-TR", "dual_locale": True},
            }
        )
        self.assertFalse(info.aligned)
        self.assertTrue(info.dual_locale)
        self.assertEqual(info.warning, "")

    def test_aligned(self) -> None:
        info = check_language_alignment(
            {
                "jarvis": {"language": "tr-TR"},
                "voice": {"listen_language": "tr-TR"},
            }
        )
        self.assertTrue(info.aligned)


if __name__ == "__main__":
    unittest.main()
