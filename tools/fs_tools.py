"""Filesystem tools — list / read / write / create / move (no recursive wipe)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable, Optional

from security.permissions import PermissionLevel
from security.risk import is_credential_path, is_dangerous_path_op
from tools.base import BaseTool, ToolResult

WorkingDirFn = Callable[[], Path]


def _expand(path: str, *, base: Optional[Path] = None) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute() and base is not None:
        p = base / p
    return p.resolve()


class FsListTool(BaseTool):
    name = "fs.list"
    description = "List files in a directory"
    permission_level = PermissionLevel.READ
    input_schema = {"path": {"type": "str", "required": False}}

    def __init__(self, working_dir: Optional[WorkingDirFn] = None) -> None:
        self._working_dir = working_dir

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raw = str(arguments.get("path") or ".").strip() or "."
        if is_credential_path(raw):
            return ToolResult(
                ok=False,
                error="Refusing to list credential/secret path (confirmation-hardened).",
            )
        base = self._working_dir() if self._working_dir else None
        path = _expand(raw, base=base)
        if not path.exists():
            return ToolResult(ok=False, error=f"Path not found: {path}")
        if not path.is_dir():
            return ToolResult(ok=False, error="Not a directory")
        names = sorted(p.name for p in path.iterdir())[:40]
        if not names:
            return ToolResult(ok=True, data=f"{path.name} is empty.")
        preview = ", ".join(names)
        if len(preview) > 200:
            preview = preview[:200] + "…"
        return ToolResult(ok=True, data=f"Contents: {preview}")


class FsReadTool(BaseTool):
    name = "fs.read"
    description = "Read a text file (active project relative paths supported)"
    permission_level = PermissionLevel.READ
    input_schema = {"path": {"type": "str", "required": True}}

    def __init__(self, working_dir: Optional[WorkingDirFn] = None) -> None:
        self._working_dir = working_dir

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raw = str(arguments.get("path") or "").strip()
        if not raw:
            return ToolResult(ok=False, error="path required")
        if is_credential_path(raw):
            return ToolResult(ok=False, error="Refusing to read credential/secret path.")
        base = self._working_dir() if self._working_dir else None
        path = _expand(raw, base=base)
        if not path.exists() or not path.is_file():
            return ToolResult(ok=False, error=f"File not found: {path}")
        max_chars = int(arguments.get("max_chars") or 4000)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            return ToolResult(ok=False, error=str(err))
        if len(text) > max_chars:
            text = text[:max_chars] + "…"
        return ToolResult(ok=True, data=text)


class FsWriteTool(BaseTool):
    name = "fs.write"
    description = "Write/overwrite a text file (Level 2 SYSTEM)"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "path": {"type": "str", "required": True},
        "content": {"type": "str", "required": True},
    }

    def __init__(self, working_dir: Optional[WorkingDirFn] = None) -> None:
        self._working_dir = working_dir

    def resolve_permission(self, arguments: dict[str, Any]) -> PermissionLevel:
        raw = str(arguments.get("path") or "")
        if is_credential_path(raw):
            return PermissionLevel.DANGEROUS
        return PermissionLevel.SYSTEM

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raw = str(arguments.get("path") or "").strip()
        content = arguments.get("content")
        if content is None:
            return ToolResult(ok=False, error="content required")
        if not raw:
            return ToolResult(ok=False, error="path required")
        if is_credential_path(raw):
            return ToolResult(ok=False, error="Refusing to write credential/secret path.")
        base = self._working_dir() if self._working_dir else None
        path = _expand(raw, base=base)
        if is_dangerous_path_op(str(path), delete=False) and str(path) in ("/",):
            return ToolResult(ok=False, error="Refusing sensitive path")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
        except OSError as err:
            return ToolResult(ok=False, error=str(err))
        return ToolResult(ok=True, data=f"Wrote {path.name} ({len(str(content))} chars).")


class FsCreateTool(BaseTool):
    name = "fs.create"
    description = "Create a file or directory"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "path": {"type": "str", "required": True},
        "kind": {"type": "str", "required": False},
    }

    def __init__(self, working_dir: Optional[WorkingDirFn] = None) -> None:
        self._working_dir = working_dir

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raw = str(arguments.get("path") or "").strip()
        kind = str(arguments.get("kind") or "file").lower()
        if not raw:
            return ToolResult(ok=False, error="path required")
        base = self._working_dir() if self._working_dir else None
        path = _expand(raw, base=base)
        if is_dangerous_path_op(str(path), delete=False) and str(path) in ("/",):
            return ToolResult(ok=False, error="Refusing sensitive path")
        try:
            if kind in ("dir", "directory", "folder"):
                path.mkdir(parents=True, exist_ok=True)
                return ToolResult(ok=True, data=f"Created folder {path.name}.")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.touch()
            return ToolResult(ok=True, data=f"Created file {path.name}.")
        except OSError as err:
            return ToolResult(ok=False, error=str(err))


class FsMoveTool(BaseTool):
    name = "fs.move"
    description = "Move or rename a file/directory"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "src": {"type": "str", "required": True},
        "dst": {"type": "str", "required": True},
    }

    def __init__(self, working_dir: Optional[WorkingDirFn] = None) -> None:
        self._working_dir = working_dir

    def resolve_permission(self, arguments: dict[str, Any]) -> PermissionLevel:
        src = str(arguments.get("src") or "")
        dst = str(arguments.get("dst") or "")
        if is_credential_path(src) or is_credential_path(dst):
            return PermissionLevel.DANGEROUS
        if is_dangerous_path_op(src) or is_dangerous_path_op(dst):
            return PermissionLevel.DANGEROUS
        return PermissionLevel.SYSTEM

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        src_raw = str(arguments.get("src") or "")
        dst_raw = str(arguments.get("dst") or "")
        if is_credential_path(src_raw) or is_credential_path(dst_raw):
            return ToolResult(
                ok=False,
                error="Refusing to move credential/secret paths without explicit Level-3 flow.",
            )
        base = self._working_dir() if self._working_dir else None
        src = _expand(src_raw, base=base)
        dst = _expand(dst_raw, base=base)
        if not src.exists():
            return ToolResult(ok=False, error=f"Source not found: {src}")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return ToolResult(ok=True, data=f"Moved to {dst.name}.")
        except OSError as err:
            return ToolResult(ok=False, error=str(err))
