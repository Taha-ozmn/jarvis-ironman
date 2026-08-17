"""Developer tools — analyze repo, run tests/commands in project dir."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from security.permissions import PermissionLevel
from security.risk import is_dangerous_shell
from tools.base import BaseTool, ToolResult

WorkingDirFn = Callable[[], Path]

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".next",
    "target",
}

KEY_FILES = (
    "README.md",
    "readme.md",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "Dockerfile",
    "main.py",
    "app.py",
)


class AnalyzeRepoTool(BaseTool):
    name = "dev.analyze_repo"
    description = "List repo structure and key files for the active project"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, working_dir: WorkingDirFn) -> None:
        self._working_dir = working_dir

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        override = str(arguments.get("path") or "").strip()
        root = Path(override).expanduser().resolve() if override else self._working_dir()
        if not root.exists():
            return ToolResult(ok=False, error=f"Path missing: {root}")
        top = sorted(
            p.name + ("/" if p.is_dir() else "")
            for p in root.iterdir()
            if p.name not in SKIP_DIRS and not p.name.startswith(".")
        )[:30]
        keys = [name for name in KEY_FILES if (root / name).exists()]
        # shallow file count
        file_count = 0
        for p in root.rglob("*"):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.is_file():
                file_count += 1
            if file_count > 5000:
                break
        summary = (
            f"Repo {root.name}: {file_count}+ files. "
            f"Top: {', '.join(top[:12]) or '(empty)'}. "
            f"Key: {', '.join(keys) or 'none'}."
        )
        if len(summary) > 280:
            summary = summary[:280] + "…"
        return ToolResult(
            ok=True,
            data=summary,
        )


class RunTestsTool(BaseTool):
    name = "dev.run_tests"
    description = "Run project tests (unittest/pytest/npm test heuristic)"
    permission_level = PermissionLevel.SYSTEM
    input_schema: dict = {}

    def __init__(self, working_dir: WorkingDirFn) -> None:
        self._working_dir = working_dir

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        root = self._working_dir()
        if not root.exists():
            return ToolResult(ok=False, error=f"Path missing: {root}")
        cmd = str(arguments.get("command") or "").strip()
        if not cmd:
            py = sys.executable or "python3"
            if (root / "pytest.ini").exists() or (root / "tests").exists():
                cmd = f"{py} -m unittest discover -s tests -q"
            elif (root / "package.json").exists():
                cmd = "npm test --silent"
            else:
                cmd = f"{py} -m unittest discover -s tests -q"
        timeout = float(arguments.get("timeout") or 45)
        return _run_cmd(root, cmd, timeout=timeout)


class DevRunCommandTool(BaseTool):
    name = "dev.run_command"
    description = "Run a shell command in the active project directory"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {"command": {"type": "str", "required": True}}

    def __init__(self, working_dir: WorkingDirFn) -> None:
        self._working_dir = working_dir

    def resolve_permission(self, arguments: dict[str, Any]) -> PermissionLevel:
        cmd = str(arguments.get("command") or "")
        if is_dangerous_shell(cmd):
            return PermissionLevel.DANGEROUS
        return PermissionLevel.SYSTEM

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        cmd = str(arguments.get("command") or "").strip()
        if not cmd:
            return ToolResult(ok=False, error="command required")
        root = self._working_dir()
        return _run_cmd(root, cmd, timeout=float(arguments.get("timeout") or 60))


def _run_cmd(cwd: Path, cmd: str, *, timeout: float) -> ToolResult:
    if not cwd.exists():
        return ToolResult(ok=False, error=f"Path missing: {cwd}")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, error="Command timed out")
    except Exception as err:
        return ToolResult(ok=False, error=str(err))
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if result.returncode != 0:
        msg = err or out or f"exit {result.returncode}"
        return ToolResult(ok=False, error=msg[:400], data=msg)
    text = out or err or "OK"
    if len(text) > 400:
        text = text[:400] + "…"
    return ToolResult(ok=True, data=text)


class FixCycleTool(BaseTool):
    """Multi-step: analyze → locate key files → run_tests (patch is optional/manual)."""

    name = "dev.fix_cycle"
    description = (
        "Developer fix cycle: analyze_repo → list key files → run_tests. "
        "Does not auto-patch unless arguments.patch_path+content provided."
    )
    permission_level = PermissionLevel.SYSTEM
    input_schema: dict = {}

    def __init__(self, working_dir: WorkingDirFn) -> None:
        self._working_dir = working_dir

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        root = self._working_dir()
        if not root.exists():
            return ToolResult(ok=False, error=f"Path missing: {root}")
        parts: list[str] = []
        analyze = AnalyzeRepoTool(self._working_dir).run({})
        if analyze.ok:
            parts.append(str(analyze.data))
        else:
            parts.append(f"analyze failed: {analyze.error}")

        # Locate: surface first few source files
        located: list[str] = []
        for name in KEY_FILES:
            if (root / name).exists():
                located.append(name)
        for p in sorted(root.rglob("*.py")):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            located.append(str(p.relative_to(root)))
            if len(located) >= 8:
                break
        parts.append("Located: " + (", ".join(located[:8]) or "none"))

        # Optional explicit patch
        patch_path = str(arguments.get("patch_path") or "").strip()
        patch_content = arguments.get("patch_content")
        if patch_path and patch_content is not None:
            from tools.fs_tools import FsWriteTool

            write = FsWriteTool(self._working_dir).run(
                {"path": patch_path, "content": str(patch_content)}
            )
            if write.ok:
                parts.append(str(write.data))
            else:
                return ToolResult(
                    ok=False,
                    error=f"Patch failed: {write.error}",
                    data=" | ".join(parts),
                )

        tests = RunTestsTool(self._working_dir).run({})
        if not tests.ok:
            return ToolResult(
                ok=False,
                error=tests.error or "tests failed",
                data=" | ".join(parts + [str(tests.error)]),
            )
        parts.append(str(tests.data))
        speech = " | ".join(parts)
        if len(speech) > 320:
            speech = speech[:317] + "…"
        return ToolResult(ok=True, data=speech)
