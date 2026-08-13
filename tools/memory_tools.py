"""Memory tools wrapping MemoryRepository."""

from __future__ import annotations

from typing import Any

from memory.repository import MemoryRepository
from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult


class MemorySearchTool(BaseTool):
    name = "memory.search"
    description = "Search long-term memories (semantic + FTS fallback)"
    permission_level = PermissionLevel.READ
    input_schema = {"query": {"type": "str", "required": True}}

    def __init__(self, repo: MemoryRepository) -> None:
        self._repo = repo

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        limit = int(arguments.get("limit") or 5)
        hits = self._repo.search_semantic(query, limit=limit)
        if not hits:
            hits = self._repo.search(query, limit=limit)
        if not hits:
            return ToolResult(ok=True, data="No matching memories.")
        lines = [f"- {m.content}" for m in hits[:limit]]
        return ToolResult(
            ok=True,
            data="I recall: " + " ".join(lines),
            error=None,
        )


class MemorySaveTool(BaseTool):
    name = "memory.save"
    description = "Save a long-term memory note"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"content": {"type": "str", "required": True}}

    def __init__(self, repo: MemoryRepository) -> None:
        self._repo = repo

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        content = str(arguments.get("content") or "").strip()
        key = arguments.get("key")
        category = str(arguments.get("category") or "general")
        if not content:
            return ToolResult(ok=False, error="Content required")
        if key:
            mem = self._repo.upsert_by_key(str(key), content, category=category)
        else:
            mem = self._repo.create(content, category=category)
        return ToolResult(ok=True, data=f"Noted. (memory #{mem.id})")


class MemoryListTool(BaseTool):
    name = "memory.list"
    description = "List recent memories"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, repo: MemoryRepository) -> None:
        self._repo = repo

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        limit = int(arguments.get("limit") or 8)
        hits = self._repo.search("", limit=limit)
        if not hits:
            return ToolResult(ok=True, data="No memories stored yet.")
        preview = "; ".join(m.content[:60] for m in hits)
        if len(preview) > 220:
            preview = preview[:220] + "…"
        return ToolResult(ok=True, data=f"Recent memories: {preview}")
