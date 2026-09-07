"""Tests for timeout recovery, evidence, safe improvement, and daemon checks."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.evidence import make_evidence
from core.self_improvement import SelfImprovementEngine
from core.timeout_responses import TimeoutResponses
from config.loader import ensure_jarvis2_defaults
from scripts.jarvis_daemon import check_database
from tools.base import ToolResult


class TimeoutPolicyTests(unittest.TestCase):
    def test_failure_never_asks_to_retry(self) -> None:
        text = TimeoutResponses(user_name="Taha").fail(
            "build a website",
            ask_retry=True,
        )
        self.assertNotIn("shall i", text.lower())
        self.assertNotIn("try again", text.lower())
        self.assertIn("saved", text.lower())


class EvidenceTests(unittest.TestCase):
    def test_evidence_hashes_output_without_copying_arguments(self) -> None:
        evidence = make_evidence(
            "dev.run_tests",
            ToolResult(ok=True, data="Ran 10 tests: OK"),
            verified=True,
            verification_message="tests reported ok",
        )
        self.assertTrue(evidence.ok)
        self.assertTrue(evidence.output_hash)
        self.assertTrue(evidence.verified)
        self.assertNotIn("password", json.dumps(evidence.as_dict()).lower())


class SelfImprovementTests(unittest.TestCase):
    def test_proposal_is_bounded_and_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = SelfImprovementEngine(root)
            proposal = engine.propose(
                "Improve retry policy",
                "Repeated transient timeout in dev tests",
                scope="retry_policy",
            )
            self.assertEqual(proposal.status, "proposed")
            reloaded = SelfImprovementEngine(root)
            self.assertIn(proposal.proposal_id, reloaded._proposals)

    def test_unsafe_scope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                SelfImprovementEngine(Path(tmp)).propose(
                    "Change deployment",
                    "Deploy automatically",
                    scope="deploy",
                )

    def test_worktree_command_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = SelfImprovementEngine(root)
            proposal = engine.propose("Fix bug", "Observed failure")
            fake = type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            with patch("core.self_improvement.subprocess.run", return_value=fake) as run:
                prepared = engine.prepare_worktree(proposal.proposal_id)
            self.assertEqual(prepared.status, "testing")
            args = run.call_args.args[0]
            self.assertEqual(args[:4], ["git", "worktree", "add", "--detach"])


class SecurityDefaultsTests(unittest.TestCase):
    def test_safe_profile_cannot_auto_approve_dangerous_work(self) -> None:
        config = ensure_jarvis2_defaults(
            {"jarvis2": {"autonomy_profile": "safe", "full_autonomy": True}}
        )
        policy = config["jarvis2"]
        self.assertFalse(policy["full_autonomy"])
        self.assertFalse(policy["auto_approve_dangerous"])
        self.assertTrue(policy["workspace_only"])


class DaemonTests(unittest.TestCase):
    def test_missing_database_is_healthy_for_first_boot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.jarvis_daemon.ROOT", Path(tmp)):
                self.assertTrue(check_database())


if __name__ == "__main__":
    unittest.main()
