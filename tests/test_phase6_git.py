"""Phase 6 — git tools against a temporary repository."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.git_tools import (
    GitAddTool,
    GitBranchTool,
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitPushTool,
    GitStatusTool,
)
from security.permissions import PermissionLevel


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "jarvis@test.local"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "JARVIS Test"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


class GitToolsTests(unittest.TestCase):
    def test_status_branch_add_commit_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git_init(repo)
            (repo / "hello.txt").write_text("hello\n", encoding="utf-8")
            wd = lambda: repo

            status = GitStatusTool(wd).run({})
            self.assertTrue(status.ok, status.error)
            self.assertTrue(status.data)

            branch = GitBranchTool(wd).run({})
            # empty repo may have no current branch name on older git
            self.assertTrue(branch.ok or branch.error)

            add = GitAddTool(wd).run({"pathspec": "."})
            self.assertTrue(add.ok, add.error)

            commit = GitCommitTool(wd).run({"message": "test: initial"})
            self.assertTrue(commit.ok, commit.error)

            log = GitLogTool(wd).run({"limit": 3})
            self.assertTrue(log.ok, log.error)
            self.assertIn("test: initial", str(log.data))

            diff = GitDiffTool(wd).run({})
            self.assertTrue(diff.ok, diff.error)

    def test_git_failure_returns_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            # not a git repo
            wd = lambda: repo
            result = GitStatusTool(wd).run({})
            self.assertFalse(result.ok)
            self.assertTrue(result.error)
            self.assertNotIn("success", (result.error or "").lower())

    def test_push_is_dangerous_level(self) -> None:
        tool = GitPushTool(lambda: Path.cwd())
        self.assertEqual(tool.permission_level, PermissionLevel.DANGEROUS)
        self.assertEqual(tool.resolve_permission({}), PermissionLevel.DANGEROUS)

    def test_add_commit_are_level_two(self) -> None:
        self.assertEqual(GitAddTool(lambda: Path.cwd()).permission_level, PermissionLevel.SYSTEM)
        self.assertEqual(GitCommitTool(lambda: Path.cwd()).permission_level, PermissionLevel.SYSTEM)


if __name__ == "__main__":
    unittest.main()
