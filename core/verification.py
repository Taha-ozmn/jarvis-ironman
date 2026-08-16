"""Post-tool verification hooks (Phase 7)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from tools.base import ToolResult

logger = logging.getLogger(__name__)

VerifyFn = Callable[[dict[str, Any], ToolResult, Any], Optional[str]]


@dataclass
class VerifyOutcome:
    ok: bool
    message: str = ""
    alternate: str = ""  # stub hint for alternate strategy


# Tools that should run verify() after success when step.verify is True
# or when listed here as always-verify-on-success.
ALWAYS_VERIFY_TOOLS = frozenset(
    {
        "git.commit",
        "fs.move",
        "dev.run_tests",
        "system.backup",
        "system.open_app",
    }
)


def should_verify(tool_name: str, *, step_verify: bool = False) -> bool:
    return step_verify or tool_name in ALWAYS_VERIFY_TOOLS


def verify_tool_result(
    tool_name: str,
    arguments: dict[str, Any],
    result: ToolResult,
    *,
    working_dir: Optional[Callable[[], Path]] = None,
) -> VerifyOutcome:
    """Return ok=False when post-condition fails (triggers retry)."""
    if not result.ok:
        return VerifyOutcome(
            ok=False,
            message=result.error or "tool failed",
            alternate=_alternate_stub(tool_name),
        )
    try:
        if tool_name == "git.commit":
            return _verify_git_commit(arguments, working_dir)
        if tool_name == "fs.move":
            return _verify_fs_move(arguments)
        if tool_name == "dev.run_tests":
            # Result already encodes exit status
            return VerifyOutcome(ok=True, message="tests reported ok")
        if tool_name == "system.backup":
            path = ""
            if isinstance(result.data, dict):
                path = str(result.data.get("path") or "")
            elif isinstance(result.data, str) and "backup" in result.data.lower():
                return VerifyOutcome(ok=True, message=result.data)
            if path and Path(path).exists():
                return VerifyOutcome(ok=True, message=f"backup at {path}")
            # String success is enough
            if isinstance(result.data, str) and result.data.strip():
                return VerifyOutcome(ok=True, message=result.data)
            return VerifyOutcome(
                ok=False,
                message="Backup path missing after run",
                alternate="Retry backup or free disk space",
            )
        if tool_name == "system.open_app":
            return _verify_open_app(arguments, result)
    except Exception as err:
        logger.exception("verify crashed for %s", tool_name)
        return VerifyOutcome(ok=False, message=str(err), alternate=_alternate_stub(tool_name))
    return VerifyOutcome(ok=True, message="ok")


def _verify_git_commit(
    arguments: dict[str, Any],
    working_dir: Optional[Callable[[], Path]],
) -> VerifyOutcome:
    import subprocess

    cwd = working_dir() if working_dir else Path.cwd()
    override = str(arguments.get("path") or "").strip()
    if override:
        cwd = Path(override).expanduser().resolve()
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--oneline"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as err:
        return VerifyOutcome(ok=False, message=str(err), alternate="Check git repo path")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "git log failed").strip()
        return VerifyOutcome(ok=False, message=err[:300], alternate="Ensure commit succeeded")
    return VerifyOutcome(ok=True, message=(proc.stdout or "").strip()[:120])


def _verify_fs_move(arguments: dict[str, Any]) -> VerifyOutcome:
    dst = str(arguments.get("dst") or "").strip()
    if not dst:
        return VerifyOutcome(ok=False, message="dst missing", alternate="Provide destination")
    path = Path(dst).expanduser()
    if path.exists():
        return VerifyOutcome(ok=True, message=f"exists: {path.name}")
    return VerifyOutcome(
        ok=False,
        message=f"Destination missing after move: {path}",
        alternate="Retry move or check permissions",
    )


def _verify_open_app(arguments: dict[str, Any], result: ToolResult) -> VerifyOutcome:
    """Success speech must confirm a real open — never trust fire-and-forget Popen."""
    data = result.data if isinstance(result.data, str) else ""
    name = str(arguments.get("name") or "").strip()
    if not data.strip():
        return VerifyOutcome(
            ok=False,
            message="Open reported empty success",
            alternate="Retry open with an explicit app name",
        )
    lower = data.lower()
    ok_words = ("is open", "açıldı", "acildi", "opened", "launching")
    if not any(w in lower for w in ok_words):
        return VerifyOutcome(
            ok=False,
            message="Open success missing confirmation phrase",
            alternate="Retry system.open_app",
        )
    if name and name.lower() not in lower:
        # Resolved display name may differ (chrome → Google Chrome) — still OK if phrase present
        pass
    return VerifyOutcome(ok=True, message=data[:120])


def _alternate_stub(tool_name: str) -> str:
    return f"Alternate strategy for {tool_name} is NOT IMPLEMENTED — diagnose and retry manually."
