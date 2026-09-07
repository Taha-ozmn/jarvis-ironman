"""Hybrid memory retrieval — semantic × keyword × recency × importance."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from memory.embeddings import cosine, embed_text, unpack
from memory.repository import Memory, MemoryRepository

CATEGORY_PROCEDURAL = "procedural"

_WEIGHT_SEMANTIC = 0.40
_WEIGHT_KEYWORD = 0.25
_WEIGHT_RECENCY = 0.20
_WEIGHT_IMPORTANCE = 0.15

_TEMPORAL_YESTERDAY = re.compile(
    r"\b(dün|dun|yesterday|dünkü|dunku)\b",
    re.I,
)
_TEMPORAL_TODAY = re.compile(
    r"\b(bugün|bugun|today|bugünkü|bugunku)\b",
    re.I,
)
_TEMPORAL_LAST_WEEK = re.compile(
    r"\b(geçen\s+hafta|gecen\s+hafta|last\s+week)\b",
    re.I,
)
_TEMPORAL_LAST_TIME = re.compile(
    r"\b(geçen\s+sefer|gecen\s+sefer|last\s+time|önceki|onceki)\b",
    re.I,
)


@dataclass(frozen=True)
class TemporalWindow:
    """Inclusive UTC date range for episodic filtering."""

    start: date
    end: date
    label: str


@dataclass
class ScoredMemory:
    memory: Memory
    score: float
    semantic: float = 0.0
    keyword: float = 0.0
    recency: float = 0.0
    importance: float = 0.0


def parse_temporal_window(query: str) -> Optional[TemporalWindow]:
    """Detect temporal phrases like «dün», «yesterday», «bugün»."""
    text = (query or "").strip()
    if not text:
        return None
    today = datetime.now(timezone.utc).date()
    if _TEMPORAL_YESTERDAY.search(text):
        d = today - timedelta(days=1)
        return TemporalWindow(start=d, end=d, label="yesterday")
    if _TEMPORAL_TODAY.search(text):
        return TemporalWindow(start=today, end=today, label="today")
    if _TEMPORAL_LAST_WEEK.search(text):
        start = today - timedelta(days=7)
        return TemporalWindow(start=start, end=today, label="last week")
    if _TEMPORAL_LAST_TIME.search(text):
        start = today - timedelta(days=3)
        return TemporalWindow(start=start, end=today, label="recent")
    return None


def _parse_iso_date(raw: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _recency_score(created_at: str, *, half_life_days: float = 7.0) -> float:
    d = _parse_iso_date(created_at)
    if d is None:
        return 0.3
    age_days = max(0.0, (datetime.now(timezone.utc).date() - d).days)
    return math.exp(-age_days / max(0.5, half_life_days))


def _importance_score(importance: int) -> float:
    return min(1.0, max(0.0, (int(importance or 1) - 1) / 4.0))


def _keyword_overlap(query: str, memory: Memory) -> float:
    q_tokens = {
        t.lower()
        for t in re.findall(r"[A-Za-zğüşıöçĞÜŞİÖÇ0-9]{2,}", query or "")
    }
    if not q_tokens:
        return 0.0
    hay = f"{memory.key or ''} {memory.content}".lower()
    hits = sum(1 for t in q_tokens if t in hay)
    return min(1.0, hits / len(q_tokens))


class HybridRetriever:
    """Score and rank memories with a weighted hybrid policy."""

    def __init__(self, repo: MemoryRepository) -> None:
        self.repo = repo

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 8,
        category: Optional[str] = None,
        temporal: Optional[TemporalWindow] = None,
        skip_semantic: bool = False,
    ) -> list[Memory]:
        q = (query or "").strip()
        if not q and temporal is None:
            return self.repo.search("", category=category, limit=limit)

        candidates: dict[int, ScoredMemory] = {}
        semantic_hits: dict[int, float] = {}

        if temporal is not None:
            pool_cat = category or "episodic"
            for mem in self.repo.search("", category=pool_cat, limit=limit * 6):
                mem_date = _parse_iso_date(mem.created_at)
                if mem_date is None:
                    continue
                if temporal.start <= mem_date <= temporal.end:
                    candidates[mem.id] = ScoredMemory(memory=mem, score=0.0)

        if q and not skip_semantic:
            try:
                self.repo.ensure_embeddings(limit=300)
                qvec = unpack(embed_text(q))
                if qvec is not None:
                    rows = (
                        self.repo._db.fetchall(
                            "SELECT * FROM memories WHERE category = ? AND embedding IS NOT NULL",
                            (category,),
                        )
                        if category
                        else self.repo._db.fetchall(
                            "SELECT * FROM memories WHERE embedding IS NOT NULL"
                        )
                    )
                    for row in rows:
                        vec = unpack(row["embedding"])
                        if vec is None:
                            continue
                        score = cosine(qvec, vec)
                        if score >= 0.04:
                            semantic_hits[int(row["id"])] = score
            except Exception:
                pass

        keyword_pool: list[Memory] = []
        if q:
            keyword_pool = self.repo.search(q, category=category, limit=limit * 3)
        elif temporal is not None:
            keyword_pool = self.repo.search(
                "",
                category=category or "episodic",
                limit=limit * 4,
            )

        for mem in keyword_pool:
            if mem.id not in candidates:
                candidates[mem.id] = ScoredMemory(memory=mem, score=0.0)

        for mid, sem in semantic_hits.items():
            if mid in candidates:
                candidates[mid].semantic = sem
            else:
                try:
                    mem = self.repo.get(mid)
                    if category and (mem.category or "") != category:
                        continue
                    candidates[mid] = ScoredMemory(memory=mem, score=0.0, semantic=sem)
                except KeyError:
                    continue

        now = datetime.now(timezone.utc).date()
        for item in candidates.values():
            mem = item.memory
            if temporal is not None:
                mem_date = _parse_iso_date(mem.created_at)
                if mem_date is None or not (temporal.start <= mem_date <= temporal.end):
                    item.score = -1.0
                    continue
            item.keyword = _keyword_overlap(q, mem) if q else 0.5
            item.recency = _recency_score(mem.created_at)
            item.importance = _importance_score(mem.importance)
            item.score = (
                _WEIGHT_SEMANTIC * item.semantic
                + _WEIGHT_KEYWORD * item.keyword
                + _WEIGHT_RECENCY * item.recency
                + _WEIGHT_IMPORTANCE * item.importance
            )

        ranked = sorted(
            (c for c in candidates.values() if c.score >= 0),
            key=lambda c: c.score,
            reverse=True,
        )
        return [c.memory for c in ranked[:limit]]

    def retrieve_temporal(self, query: str, *, limit: int = 6) -> list[Memory]:
        window = parse_temporal_window(query)
        if window is None:
            return []
        return self.retrieve(
            query,
            limit=limit,
            category="episodic",
            temporal=window,
        )

    def retrieve_procedural(self, query: str, *, limit: int = 4) -> list[Memory]:
        hits = self.retrieve(query, limit=limit, category=CATEGORY_PROCEDURAL)
        if hits:
            return hits
        return self.retrieve(query, limit=limit, category="fact")
