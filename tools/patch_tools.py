"""LLM-assisted safe code patch loop (analyze → propose → write L2 → test → verify)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Optional

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult
from tools.dev_tools import AnalyzeRepoTool, RunTestsTool, SKIP_DIRS
from tools.fs_tools import FsReadTool, FsWriteTool

logger = logging.getLogger(__name__)

WorkingDirFn = Callable[[], Path]


def parse_patch_json(raw: str) -> Optional[dict[str, str]]:
    """Expect {\"path\": \"rel/path.py\", \"content\": \"...\", \"rationale\": \"...\"}."""
    text = (raw or "").strip()
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    path = str(data.get("path") or "").strip()
    content = data.get("content")
    if not path or content is None:
        return None
    # Safety: no absolute escapes outside project
    if path.startswith("/") or ".." in Path(path).parts:
        return None
    return {
        "path": path,
        "content": str(content),
        "rationale": str(data.get("rationale") or "")[:200],
    }


class ApplyPatchTool(BaseTool):
    """Safe patch loop — never silent; write is Level 2 SYSTEM (confirm via gate when required)."""

    name = "dev.apply_patch"
    description = (
        "LLM-assisted patch: analyze → propose → fs.write → run_tests → verify. "
        "Requires LLMProvider when auto-proposing; or pass path+content explicitly."
    )
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "goal": {"type": "str", "required": False},
        "path": {"type": "str", "required": False},
        "content": {"type": "str", "required": False},
        "dry_run": {"type": "bool", "required": False},
    }

    def __init__(
        self,
        working_dir: WorkingDirFn,
        *,
        llm: Any = None,
    ) -> None:
        self._working_dir = working_dir
        self._llm = llm

    def set_llm(self, llm: Any) -> None:
        self._llm = llm

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        root = self._working_dir()
        goal = str(arguments.get("goal") or "fix failing tests").strip()
        dry = bool(arguments.get("dry_run", False))
        path = str(arguments.get("path") or "").strip()
        content = arguments.get("content")

        steps: list[str] = []
        analyze = AnalyzeRepoTool(self._working_dir).run({})
        steps.append(str(analyze.data if analyze.ok else analyze.error))

        # Explicit patch overrides LLM
        patch: Optional[dict[str, str]] = None
        if path and content is not None:
            if path.startswith("/") or ".." in Path(path).parts:
                return ToolResult(ok=False, error="Refusing unsafe patch path")
            patch = {"path": path, "content": str(content), "rationale": "explicit"}
        else:
            patch = self._propose_with_llm(goal, root, analyze.data if analyze.ok else "")
            if patch is None:
                return ToolResult(
                    ok=False,
                    error=(
                        "No patch proposed — LLM unavailable or invalid JSON. "
                        "Pass path+content explicitly, or bind a brain with think_sync."
                    ),
                    data=" | ".join(steps),
                )
            steps.append(f"Proposed {patch['path']}: {patch.get('rationale') or 'ok'}")

        if dry:
            return ToolResult(
                ok=True,
                data=f"Dry-run patch for {patch['path']} ({len(patch['content'])} chars). "
                + " | ".join(steps),
            )

        write = FsWriteTool(self._working_dir).run(
            {"path": patch["path"], "content": patch["content"]}
        )
        if not write.ok:
            return ToolResult(
                ok=False,
                error=f"Write failed: {write.error}",
                data=" | ".join(steps),
            )
        steps.append(str(write.data))

        tests = RunTestsTool(self._working_dir).run({})
        if not tests.ok:
            return ToolResult(
                ok=False,
                error=f"Tests failed after patch: {tests.error}",
                data=" | ".join(steps),
            )
        steps.append("tests ok")

        # Verify file exists with content length
        target = (root / patch["path"]).resolve()
        if not target.exists():
            return ToolResult(ok=False, error="Verify failed: patched file missing")
        speech = f"Patched {patch['path']} and tests passed. " + " | ".join(steps)
        if len(speech) > 360:
            speech = speech[:357] + "…"
        return ToolResult(ok=True, data=speech)

    def _propose_with_llm(self, goal: str, root: Path, analyze: Any) -> Optional[dict[str, str]]:
        llm = self._llm
        if llm is None or not getattr(llm, "available", lambda: False)():
            return None
        # Gather a small snippet from a key file for context
        snippet = ""
        for name in ("main.py", "app.py", "README.md"):
            p = root / name
            if p.exists() and p.is_file():
                try:
                    snippet = p.read_text(encoding="utf-8", errors="replace")[:1200]
                except OSError:
                    snippet = ""
                break
        prompt = (
            "You are a careful coding assistant. Return ONLY JSON: "
            '{"path":"relative/file.py","content":"full new file content","rationale":"..."}. '
            "Do not escape the project. Prefer minimal edits.\n"
            f"Goal: {goal}\nAnalyze: {analyze}\nSnippet:\n{snippet}\n"
        )
        try:
            raw = llm.complete(prompt, category="code", timeout=25.0)
        except Exception:
            logger.exception("LLM patch propose failed")
            return None
        return parse_patch_json(raw)
