"""Memory tools wrapping MemoryRepository."""

from __future__ import annotations

from typing import Any, Callable, Optional

from memory.extractor import parse_name_preference
from memory.layers import MemoryLayers, normalize_memory_category
from memory.preference import preference_ack
from memory.repository import MemoryRepository
from memory.extractor import looks_like_secret, redact_secrets
from memory.retrieval import HybridRetriever
from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult


class MemorySearchTool(BaseTool):
    name = "memory.search"
    description = "Search long-term memories (semantic + FTS fallback)"
    permission_level = PermissionLevel.READ
    input_schema = {"query": {"type": "str", "required": True}}

    def __init__(self, repo: MemoryRepository) -> None:
        self._repo = repo
        self._retriever = HybridRetriever(repo)

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        limit = int(arguments.get("limit") or 5)
        hits = self._retriever.retrieve(query, limit=limit)
        if not hits:
            hits = self._repo.search(query, limit=limit)
        if not hits:
            return ToolResult(ok=True, data="No matching memories.")
        lines = [f"- {m.content}" for m in hits[:limit]]
        return ToolResult(
            ok=True,
            data="What I remember: " + " ".join(lines),
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
        raw_content = str(arguments.get("content") or "").strip()
        if looks_like_secret(raw_content):
            return ToolResult(ok=False, error="Refusing to store a credential or secret.")
        content = redact_secrets(raw_content).strip()
        key = arguments.get("key")
        category = normalize_memory_category(
            str(arguments.get("category") or "fact")
        )
        importance = int(arguments.get("importance") or 2)
        if not content:
            return ToolResult(ok=False, error="Content required")
        if key:
            mem = self._repo.upsert_by_key(
                str(key),
                content,
                category=category,
                importance=importance,
            )
        else:
            mem = self._repo.create(
                content,
                category=category,
                importance=importance,
            )
        return ToolResult(ok=True, data=f"Noted. (memory #{mem.id})")


class PreferenceApplyTool(BaseTool):
    name = "preference.apply"
    description = "Apply user name / address preference (fast path)"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"text": {"type": "str", "required": True}}

    def __init__(
        self,
        repo: MemoryRepository,
        *,
        language: str = "en-GB",
        on_applied: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._repo = repo
        self._language = language
        self._on_applied = on_applied
        self._layers = MemoryLayers(repo)

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        text = str(arguments.get("text") or "").strip()
        parsed = parse_name_preference(text)
        if not parsed:
            return ToolResult(ok=False, error="Not a name preference command.")
        name, content = parsed
        try:
            self._layers.update_profile("name", name, importance=5)
            self._repo.upsert_by_key(
                "preference:address",
                content,
                category="preference",
                importance=5,
            )
            self._repo.upsert_by_key(
                f"preference:name:{name.lower()}",
                f"User name is {name}",
                category="preference",
                importance=4,
            )
        except Exception as err:
            return ToolResult(ok=False, error=str(err))
        if self._on_applied:
            try:
                self._on_applied(name)
            except Exception:
                pass
        return ToolResult(ok=True, data=preference_ack(name, language=self._language))


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


class MemoryAboutUserTool(BaseTool):
    name = "memory.about_user"
    description = "Summarize what JARVIS knows about the user (profile + prefs)"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, layers: MemoryLayers, *, language: str = "en-GB") -> None:
        self._layers = layers
        self._language = language

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        return ToolResult(
            ok=True,
            data=self._layers.profile_speech(language=self._language),
        )


class MemoryForgetTool(BaseTool):
    name = "memory.forget"
    description = "Forget a memory by query, id, or most recent"
    permission_level = PermissionLevel.LOCAL
    input_schema: dict = {
        "query": {"type": "str", "required": False},
        "memory_id": {"type": "int", "required": False},
    }

    def __init__(self, layers: MemoryLayers) -> None:
        self._layers = layers

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        mid = arguments.get("memory_id")
        query = str(arguments.get("query") or "").strip()
        memory_id = int(mid) if mid is not None and str(mid).isdigit() else None
        count, speech = self._layers.forget(query, memory_id=memory_id, last_n=1)
        return ToolResult(ok=True, data=speech)


class MemoryTemporalRecallTool(BaseTool):
    name = "memory.temporal_recall"
    description = "Recall episodic memories from a time window (yesterday, today, last week)"
    permission_level = PermissionLevel.READ
    input_schema = {"query": {"type": "str", "required": True}}

    def __init__(self, layers: MemoryLayers, *, language: str = "en-GB") -> None:
        self._layers = layers
        self._language = language

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="Query required")
        return ToolResult(
            ok=True,
            data=self._layers.temporal_speech(query, language=self._language),
        )


class MemorySessionCaptureTool(BaseTool):
    name = "memory.session_capture"
    description = "Enable/disable long-term memory capture for this voice session"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"enabled": {"type": "bool", "required": True}}

    def __init__(self, setter: Callable[[bool], str]) -> None:
        self._setter = setter

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        enabled = bool(arguments.get("enabled", True))
        try:
            speech = self._setter(enabled)
        except Exception as err:
            return ToolResult(ok=False, error=str(err))
        return ToolResult(ok=True, data=speech)
