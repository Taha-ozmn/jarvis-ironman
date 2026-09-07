"""Second Brain memory layers on top of MemoryRepository (SQLite).

Categories (convention, no schema migration):
  profile | preference | episodic | fact | project
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from memory.repository import Memory, MemoryRepository
from memory.retrieval import (
    CATEGORY_PROCEDURAL,
    HybridRetriever,
    parse_temporal_window,
)

# Canonical category names used in retrieval / tools
CATEGORY_PROFILE = "profile"
CATEGORY_PREFERENCE = "preference"
CATEGORY_EPISODIC = "episodic"
CATEGORY_FACT = "fact"
CATEGORY_PROJECT = "project"
CATEGORY_PROJECT_CONTEXT = "project_context"  # legacy extractor alias

PROFILE_KEYS = (
    "user_name",
    "user_display_name",
    "user_language",
    "user_timezone",
    "user_city",
    "user_job",
    "user_notes",
)

PROFILE_ALIASES = {
    "name": "user_name",
    "display_name": "user_display_name",
    "language": "user_language",
    "timezone": "user_timezone",
    "city": "user_city",
    "job": "user_job",
    "notes": "user_notes",
}


@dataclass
class UserProfile:
    """Flattened view of profile + preference keys."""

    fields: dict[str, str]
    preferences: list[Memory]
    facts: list[Memory]

    def display_name(self) -> str:
        return (
            self.fields.get("user_display_name")
            or self.fields.get("user_name")
            or ""
        ).strip()

    def summary_lines(self, *, max_items: int = 8, include_preferences: bool = True) -> list[str]:
        lines: list[str] = []
        for key in PROFILE_KEYS:
            val = self.fields.get(key)
            if val:
                short = key.replace("user_", "")
                lines.append(f"{short}: {val}")
        if include_preferences:
            for mem in self.preferences[: max(0, max_items - len(lines))]:
                # Avoid duplicating raw profile field contents
                if mem.key and mem.key in PROFILE_KEYS:
                    continue
                lines.append(mem.content)
            for mem in self.facts[: max(0, max_items - len(lines))]:
                lines.append(mem.content)
        return lines[:max_items]


class MemoryLayers:
    """Profile / episodic / fact helpers — thin facade over MemoryRepository."""

    def __init__(self, repo: MemoryRepository) -> None:
        self.repo = repo
        self._retriever = HybridRetriever(repo)

    # --- Profile ---

    def get_profile(self) -> UserProfile:
        fields: dict[str, str] = {}
        for key in PROFILE_KEYS:
            row = self._get_by_key(key)
            if row:
                fields[key] = row.content
        prefs = self.repo.search("", category=CATEGORY_PREFERENCE, limit=20)
        facts = self.repo.search("", category=CATEGORY_FACT, limit=10)
        # Also pull preference-keyed profile fragments
        for mem in prefs:
            if mem.key and mem.key.startswith("user_") and mem.key not in fields:
                fields[mem.key] = mem.content
        return UserProfile(fields=fields, preferences=prefs, facts=facts)

    def update_profile(self, field: str, value: str, *, importance: int = 5) -> Memory:
        raw = (field or "").strip().lower()
        key = PROFILE_ALIASES.get(raw, raw)
        if not key.startswith("user_"):
            key = f"user_{key}"
        content = (value or "").strip()
        if not content:
            raise ValueError("Profile value required")
        return self.repo.upsert_by_key(
            key,
            content,
            category=CATEGORY_PROFILE,
            importance=max(1, min(5, importance)),
        )

    def profile_speech(self, *, language: str = "en-GB") -> str:
        """Spoken profile summary (English by default)."""
        profile = self.get_profile()
        lines = profile.summary_lines(max_items=6)
        if not lines:
            if str(language).lower().startswith("tr"):
                return "Henüz senin hakkında kalıcı bir notum yok."
            return "I don't have lasting notes about you yet."
        name = profile.display_name()
        body = "; ".join(lines)
        if len(body) > 240:
            body = body[:237] + "…"
        if str(language).lower().startswith("tr"):
            if name and name.lower() not in body.lower():
                return f"Şunu biliyorum, {name}: {body}."
            return f"Senin hakkında şunları biliyorum: {body}."
        if name and name.lower() not in body.lower():
            return f"Here's what I know, {name}: {body}."
        return f"About you: {body}."

    # --- Episodic ---

    def record_episodic(
        self,
        content: str,
        *,
        importance: int = 2,
        key: Optional[str] = None,
    ) -> Optional[Memory]:
        text = (content or "").strip()
        if not text or len(text) < 8:
            return None
        return self.repo.create(
            text[:400],
            key=key,
            category=CATEGORY_EPISODIC,
            importance=max(1, min(5, importance)),
        )

    def recent_episodic(self, *, limit: int = 5) -> list[Memory]:
        return self.repo.search("", category=CATEGORY_EPISODIC, limit=limit)

    # --- Procedural ---

    def record_procedural(
        self,
        content: str,
        *,
        key: Optional[str] = None,
        importance: int = 4,
    ) -> Optional[Memory]:
        """Store how-to knowledge (test commands, workflows, project habits)."""
        text = (content or "").strip()
        if not text or len(text) < 8:
            return None
        if key:
            return self.repo.upsert_by_key(
                key,
                text[:500],
                category=CATEGORY_PROCEDURAL,
                importance=max(1, min(5, importance)),
            )
        return self.repo.create(
            text[:500],
            category=CATEGORY_PROCEDURAL,
            importance=max(1, min(5, importance)),
        )

    def search_procedural(self, query: str, *, limit: int = 4) -> list[Memory]:
        return self._retriever.retrieve_procedural(query, limit=limit)

    def search_temporal(self, query: str, *, limit: int = 6) -> list[Memory]:
        return self._retriever.retrieve_temporal(query, limit=limit)

    def temporal_speech(self, query: str, *, language: str = "en-GB") -> str:
        """Answer «what did we do yesterday?» style questions."""
        window = parse_temporal_window(query)
        hits = self.search_temporal(query, limit=6)
        if not hits:
            label = window.label if window else "that period"
            if str(language).lower().startswith("tr"):
                return f"{label} için kayıtlı bir notum yok."
            return f"I have no recorded notes for {label}."
        lines = [m.content for m in hits[:4]]
        body = "; ".join(lines)
        if len(body) > 260:
            body = body[:257] + "…"
        if str(language).lower().startswith("tr"):
            return f"Kayıtlarım: {body}"
        return f"From my records: {body}"

    # --- Forget ---

    def forget(
        self,
        query: str = "",
        *,
        memory_id: Optional[int] = None,
        last_n: int = 1,
    ) -> tuple[int, str]:
        """Delete by id, query match, or most recent episodic/general. Returns (count, speech)."""
        deleted = 0
        if memory_id is not None:
            try:
                self.repo.delete(int(memory_id))
                deleted = 1
            except KeyError:
                return 0, "Bu bellek kaydı bulunamadı."
            return deleted, "Tamam, o notu unuttum."

        q = (query or "").strip()
        if q:
            hits = self.repo.search(q, limit=5)
            # Prefer non-profile critical? Allow profile forget if explicit
            for mem in hits:
                try:
                    self.repo.delete(mem.id)
                    deleted += 1
                except KeyError:
                    continue
            if deleted:
                return deleted, f"Tamam, {deleted} ilgili notu unuttum."
            return 0, "Buna uyan bir bellek bulamadım."

        # Forget last episodic (or any recent) entries
        recent = self.recent_episodic(limit=max(1, last_n))
        if not recent:
            recent = self.repo.search("", limit=max(1, last_n))
        for mem in recent[: max(1, last_n)]:
            # Protect core user_name unless explicitly queried
            if mem.key == "user_name":
                continue
            try:
                self.repo.delete(mem.id)
                deleted += 1
            except KeyError:
                continue
        if deleted:
            return deleted, "Tamam, son notu unuttum."
        return 0, "Unutacak bir şey bulamadım."

    # --- Retrieval for prompts ---

    def retrieve_for_prompt(
        self,
        query: str,
        *,
        profile_limit: int = 4,
        episodic_limit: int = 2,
        semantic_limit: int = 3,
        max_chars: int = 400,
        skip_semantic: bool = False,
    ) -> str:
        """Build a compact memory block: profile + relevant episodic/facts — not a dump."""
        lines: list[str] = []
        seen: set[int] = set()
        profile = self.get_profile()
        # Prompt profile: keyed fields only (avoid dumping all prefs every turn)
        prof_lines = profile.summary_lines(max_items=profile_limit, include_preferences=False)
        if prof_lines:
            lines.append("[USER PROFILE]")
            for pl in prof_lines:
                lines.append(f"- {pl}")

        q = (query or "").strip()
        hits: list[Memory] = []
        temporal = parse_temporal_window(q) if q else None
        try:
            hybrid = self._retriever.retrieve(
                q,
                limit=semantic_limit + episodic_limit + 2,
                temporal=temporal,
                skip_semantic=skip_semantic,
            )
            for mem in hybrid:
                if mem.id in seen:
                    continue
                if (mem.category or "") == CATEGORY_PROFILE:
                    continue
                seen.add(mem.id)
                hits.append(mem)
        except Exception:
            pass

        # Procedural hints for coding / workflow queries
        if q and any(
            tok in q.lower()
            for tok in ("test", "build", "deploy", "npm", "pytest", "çalıştır", "calistir")
        ):
            for mem in self.search_procedural(q, limit=2):
                if mem.id in seen:
                    continue
                seen.add(mem.id)
                hits.append(mem)

        # Always sprinkle recent episodic (recency) when not temporal-only
        if temporal is None:
            for mem in self.recent_episodic(limit=episodic_limit):
                if mem.id in seen:
                    continue
                seen.add(mem.id)
                hits.append(mem)

        # Prefer preference/fact/project/episodic ordering
        def _rank(m: Memory) -> tuple[int, int]:
            cat = (m.category or "").lower()
            order = {
                CATEGORY_PREFERENCE: 0,
                CATEGORY_FACT: 1,
                CATEGORY_PROJECT: 2,
                CATEGORY_PROJECT_CONTEXT: 2,
                CATEGORY_EPISODIC: 3,
            }.get(cat, 4)
            return (order, -int(m.importance or 1))

        hits = sorted(hits, key=_rank)[: semantic_limit + episodic_limit]
        if hits:
            lines.append("[LONG-TERM MEMORY — use only if relevant]")
            for mem in hits:
                cat = mem.category or "general"
                lines.append(f"- ({cat}) {mem.content}")

        if not lines:
            return ""
        block = "\n".join(lines)
        if len(block) > max_chars:
            block = block[: max_chars - 1].rsplit("\n", 1)[0] + "\n- …"
        return block

    def _get_by_key(self, key: str) -> Optional[Memory]:
        return self.repo.get_by_key(key)


def normalize_memory_category(raw: str) -> str:
    """Map free-form category strings to canonical layer names."""
    c = (raw or "general").strip().lower()
    aliases = {
        "general": CATEGORY_FACT,
        "pref": CATEGORY_PREFERENCE,
        "preferences": CATEGORY_PREFERENCE,
        "user": CATEGORY_PROFILE,
        "about": CATEGORY_PROFILE,
        "event": CATEGORY_EPISODIC,
        "session": CATEGORY_EPISODIC,
        "project_context": CATEGORY_PROJECT,
        "proj": CATEGORY_PROJECT,
    }
    return aliases.get(c, c if c in {
        CATEGORY_PROFILE,
        CATEGORY_PREFERENCE,
        CATEGORY_EPISODIC,
        CATEGORY_FACT,
        CATEGORY_PROJECT,
        CATEGORY_PROCEDURAL,
    } else CATEGORY_FACT)
