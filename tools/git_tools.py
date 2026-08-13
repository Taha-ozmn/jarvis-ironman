"""Local git tools — real subprocess output, never fake success."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult

WorkingDirFn = Callable[[], Path]


def _run_git(cwd: Path, args: list[str], *, timeout: float = 30) -> ToolResult:
    if not cwd.exists():
        return ToolResult(ok=False, error=f"Working directory missing: {cwd}")
    if not (cwd / ".git").exists() and args[0] != "init":
        # Still try — git will error honestly
        pass
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return ToolResult(ok=False, error="git binary not found on PATH")
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, error="git command timed out")
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if result.returncode != 0:
        msg = err or out or f"git exited {result.returncode}"
        return ToolResult(ok=False, error=msg[:400], data=msg)
    text = out or err or "OK"
    if len(text) > 400:
        text = text[:400] + "…"
    return ToolResult(ok=True, data=text)


class _GitBase(BaseTool):
    def __init__(self, working_dir: WorkingDirFn) -> None:
        self._working_dir = working_dir

    def _cwd(self, arguments: dict[str, Any]) -> Path:
        override = str(arguments.get("path") or "").strip()
        if override:
            return Path(override).expanduser().resolve()
        return self._working_dir()


class GitStatusTool(_GitBase):
    name = "git.status"
    description = "git status — short porcelain summary"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        return _run_git(self._cwd(arguments), ["status", "-sb"])


class GitDiffTool(_GitBase):
    name = "git.diff"
    description = "git diff (unstaged by default)"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        staged = bool(arguments.get("staged", False))
        args = ["diff", "--stat"] if not staged else ["diff", "--cached", "--stat"]
        return _run_git(self._cwd(arguments), args)


class GitBranchTool(_GitBase):
    name = "git.branch"
    description = "Show current git branch"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        return _run_git(self._cwd(arguments), ["branch", "--show-current"])


class GitLogTool(_GitBase):
    name = "git.log"
    description = "Recent git commits (oneline)"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        n = int(arguments.get("limit") or 5)
        n = max(1, min(n, 20))
        return _run_git(self._cwd(arguments), ["log", f"-{n}", "--oneline"])


class GitAddTool(_GitBase):
    name = "git.add"
    description = "git add — stages paths (default: .)"
    permission_level = PermissionLevel.SYSTEM
    input_schema: dict = {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        pathspec = str(arguments.get("pathspec") or ".").strip() or "."
        return _run_git(self._cwd(arguments), ["add", pathspec])


class GitCommitTool(_GitBase):
    name = "git.commit"
    description = "git commit — requires message"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {"message": {"type": "str", "required": True}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        message = str(arguments.get("message") or "").strip()
        if not message:
            return ToolResult(ok=False, error="Commit message required")
        return _run_git(self._cwd(arguments), ["commit", "-m", message])


class GitPushTool(_GitBase):
    name = "git.push"
    description = "git push — Level 3 dangerous (remote write). Force push is blocked."
    permission_level = PermissionLevel.DANGEROUS
    input_schema: dict = {}

    def resolve_permission(self, arguments: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.DANGEROUS

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        if bool(arguments.get("force")) or bool(arguments.get("force_with_lease")):
            return ToolResult(
                ok=False,
                error="Blocked: force push is not allowed via JARVIS tools.",
            )
        remote = str(arguments.get("remote") or "origin").strip() or "origin"
        branch = str(arguments.get("branch") or "").strip()
        args = ["push", remote] + ([branch] if branch else [])
        # Extra guard if someone smuggles -f into remote/branch strings
        joined = " ".join(args)
        if "--force" in joined or re.search(r"(^|\s)-f(\s|$)", joined):
            return ToolResult(ok=False, error="Blocked: force push flags are not allowed.")
        return _run_git(self._cwd(arguments), args, timeout=60)
