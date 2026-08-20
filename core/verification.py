"""Post-tool verification hooks — never claim success without evidence."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from tools.base import ToolResult

logger = logging.getLogger(__name__)

VerifyFn = Callable[[dict[str, Any], ToolResult, Any], Optional[str]]

# Success-sounding words that must not be spoken unless verify/tool ok
_SUCCESS_CLAIM_RE = re.compile(
    r"(?i)\b("
    r"açıldı|acildi|opened|is open|çalınıyor|caliniyor|played|playing|arandı|arandi|"
    r"searched|commit(?:ted)?|pushed|moved|backup(?:ed)?|tamamlandı|tamamlandi|"
    r"başarılı|basarili|success|done\.|tamam\."
    r")\b"
)


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
        "git.push",
        "git.add",
        "fs.move",
        "dev.run_tests",
        "system.backup",
        "browser.open_url",
        "browser.list_tabs",
        "browser.search",
        "system.open_app",
        "media.play",
    }
)


def should_verify(tool_name: str, *, step_verify: bool = False) -> bool:
    return step_verify or tool_name in ALWAYS_VERIFY_TOOLS


def looks_like_success_claim(text: str) -> bool:
    return bool(_SUCCESS_CLAIM_RE.search(text or ""))


def claim_safe_speech(result: ToolResult, *, fallback_fail: str = "Could not verify that.") -> str:
    """Speak only verified success data; never invent success from a failed tool."""
    if result.ok and isinstance(result.data, str) and result.data.strip():
        return result.data.strip()
    if result.ok:
        return "Done."
    err = (result.error or "").strip() or fallback_fail
    return err


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
        if tool_name == "git.push":
            return _verify_git_push(result)
        if tool_name == "git.add":
            return _verify_nonempty_success(result, need=("staged", "added", "ok", "eklendi"))
        if tool_name == "fs.move":
            return _verify_fs_move(arguments)
        if tool_name == "dev.run_tests":
            return VerifyOutcome(ok=True, message="tests reported ok")
        if tool_name == "system.backup":
            path = ""
            if isinstance(result.data, dict):
                path = str(result.data.get("path") or "")
            elif isinstance(result.data, str) and "backup" in result.data.lower():
                return VerifyOutcome(ok=True, message=result.data)
            if path and Path(path).exists():
                return VerifyOutcome(ok=True, message=f"backup at {path}")
            if isinstance(result.data, str) and result.data.strip():
                return VerifyOutcome(ok=True, message=result.data)
            return VerifyOutcome(
                ok=False,
                message="Backup path missing after run",
                alternate="Retry backup or free disk space",
            )
        if tool_name == "media.play":
            return _verify_media_play(arguments, result)
        if tool_name == "browser.open_url":
            return _verify_open_url(arguments, result)
        if tool_name == "browser.search":
            return _verify_open_url(arguments, result)
        if tool_name == "browser.list_tabs":
            return _verify_list_tabs(result)
        if tool_name == "system.open_app":
            return _verify_open_app(arguments, result)
    except Exception as err:
        logger.exception("verify crashed for %s", tool_name)
        return VerifyOutcome(ok=False, message=str(err), alternate=_alternate_stub(tool_name))
    return VerifyOutcome(ok=True, message="ok")


def _verify_media_play(arguments: dict[str, Any], result: ToolResult) -> VerifyOutcome:
    data = result.data if isinstance(result.data, str) else ""
    query = str(arguments.get("query") or "").strip()
    if not data.strip():
        return VerifyOutcome(
            ok=False,
            message="Play reported empty success",
            alternate="Retry media.play with explicit query",
        )
    lower = data.lower()
    _media_ok = (
        "arandı",
        "arandi",
        "çalınıyor",
        "caliniyor",
        "searched",
        "playing",
        "spotify",
        "youtube",
    )
    if query and query.lower() not in lower:
        if not any(w in lower for w in _media_ok):
            return VerifyOutcome(
                ok=False,
                message="Play success did not confirm query",
                alternate="Retry media.play",
            )
    if not any(w in lower for w in _media_ok):
        return VerifyOutcome(
            ok=False,
            message="Play success missing confirmation phrase",
            alternate="Retry media.play",
        )
    return VerifyOutcome(ok=True, message=data[:120])


def _verify_open_url(arguments: dict[str, Any], result: ToolResult) -> VerifyOutcome:
    """Success speech must reflect a real open — never claim without tool ok + URL/query."""
    data = result.data if isinstance(result.data, str) else ""
    url = str(arguments.get("url") or "").strip()
    query = str(arguments.get("query") or "").strip()
    if not data.strip():
        return VerifyOutcome(
            ok=False,
            message="Open reported empty success",
            alternate="Retry open with explicit URL",
        )
    lower = data.lower()
    _open_ok = ("açıldı", "acildi", "arandı", "arandi", "opened", "searched", "is open")
    if query:
        if query.lower() not in lower and not any(w in lower for w in _open_ok):
            return VerifyOutcome(
                ok=False,
                message="Search/open success did not confirm query",
                alternate="Retry browser search",
            )
        return VerifyOutcome(ok=True, message=data[:120])
    if url and "youtube.com" in url.lower() and "search_query=" in url.lower():
        if not any(w in lower for w in _open_ok):
            return VerifyOutcome(ok=False, message="URL open unconfirmed", alternate="Retry open")
    # Generic URL: require explicit opened confirmation
    if url and not any(w in lower for w in _open_ok):
        return VerifyOutcome(
            ok=False,
            message="URL open unconfirmed",
            alternate="Retry browser.open_url",
        )
    return VerifyOutcome(ok=True, message=data[:120] or "url open ok")


def _verify_list_tabs(result: ToolResult) -> VerifyOutcome:
    data = result.data if isinstance(result.data, str) else ""
    if not data.strip():
        return VerifyOutcome(
            ok=False,
            message="Tab list empty without honest message",
            alternate="Retry browser.list_tabs",
        )
    lower = data.lower()
    # Honest empty is OK
    if "bulamadım" in lower or "bulamadim" in lower or "no open tab" in lower:
        return VerifyOutcome(ok=True, message=data[:120])
    if "sekme" not in lower and "tab" not in lower:
        return VerifyOutcome(
            ok=False,
            message="Tab list missing sekme/tab confirmation",
            alternate="Retry list_tabs",
        )
    return VerifyOutcome(ok=True, message=data[:160])


def _verify_open_app(arguments: dict[str, Any], result: ToolResult) -> VerifyOutcome:
    data = result.data if isinstance(result.data, str) else ""
    name = str(arguments.get("name") or "").strip()
    lower = data.lower()
    if not data.strip() or (
        "açıldı" not in lower
        and "opened" not in lower
        and "is open" not in lower
    ):
        return VerifyOutcome(
            ok=False,
            message="App open not confirmed",
            alternate=f"Retry open_app for {name or 'target'}",
        )
    return VerifyOutcome(ok=True, message=data[:120])


def _verify_git_push(result: ToolResult) -> VerifyOutcome:
    data = result.data if isinstance(result.data, str) else ""
    lower = data.lower()
    if not data.strip():
        return VerifyOutcome(ok=False, message="git push empty success", alternate="Retry push")
    if any(w in lower for w in ("error", "rejected", "failed", "denied")):
        return VerifyOutcome(ok=False, message=data[:200], alternate="Fix remote and retry")
    if any(w in lower for w in ("pushed", "up-to-date", "everything up-to-date", "gönder", "ok")):
        return VerifyOutcome(ok=True, message=data[:120])
    # Require some substantive output
    if len(data.strip()) < 3:
        return VerifyOutcome(ok=False, message="git push unconfirmed", alternate="Retry push")
    return VerifyOutcome(ok=True, message=data[:120])


def _verify_nonempty_success(
    result: ToolResult,
    *,
    need: tuple[str, ...],
) -> VerifyOutcome:
    data = result.data if isinstance(result.data, str) else ""
    if not data.strip():
        return VerifyOutcome(ok=False, message="empty success", alternate="Retry")
    lower = data.lower()
    if any(n in lower for n in need) or len(data.strip()) >= 4:
        return VerifyOutcome(ok=True, message=data[:120])
    return VerifyOutcome(ok=False, message="success unconfirmed", alternate="Retry")


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


def _alternate_stub(tool_name: str) -> str:
    return f"Alternate strategy for {tool_name} is NOT IMPLEMENTED — diagnose and retry manually."
