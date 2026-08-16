"""Hybrid memory retrieval — semantic × keyword × recency × importance (Phase 5)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from memory.embeddings import cosine, embed_text, unpack
from memory.repository import Memory, MemoryRepository

_TOKEN = re.compile(r"[A-Za-zğüşıöçĞÜŞİÖÇ0-9]{2,}")


@dataclass
class RankedMemory:
    memory: Memory
    score: float
    reasons: list[str]


def _parse_ts(raw: str) -> float:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _recency_score(created_at: str, *, now: Optional[float] = None) -> float:
    ts = _parse_ts(created_at)
    if ts <= 0:
        return 0.2
    age_hours = max(0.0, ((now or datetime.now(timezone.utc).timestamp()) - ts) / 3600.0)
    # Half-life ~72h
    return math.exp(-age_hours / 72.0)


def _keyword_score(query: str, content: str) -> float:
    q_tokens = set(_TOKEN.findall((query or "").lower()))
    if not q_tokens:
        return 0.0
    c_tokens = set(_TOKEN.findall((content or "").lower()))
    if not c_tokens:
        return 0.0
    overlap = len(q_tokens & c_tokens)
    return overlap / max(1, len(q_tokens))


def hybrid_retrieve(
    repo: MemoryRepository,
    query: str,
    *,
    limit: int = 5,
    category: Optional[str] = None,
    since_hours: Optional[float] = None,
) -> list[RankedMemory]:
    """Rank memories with hybrid score; never dump the full store."""
    q = (query or "").strip()
    limit = max(1, min(int(limit), 20))
    candidates: dict[int, Memory] = {}

    # Keyword / FTS
    for mem in repo.search(q, category=category, limit=limit * 3):
        candidates[mem.id] = mem
    # Semantic
    try:
        for mem in repo.search_semantic(q, limit=limit * 3):
            candidates[mem.id] = mem
    except Exception:
        pass
    # Temporal: recent episodic window
    if since_hours is not None and since_hours > 0:
        cutoff = datetime.now(timezone.utc).timestamp() - since_hours * 3600
        for mem in repo.search("", category=category or "episodic", limit=40):
            if _parse_ts(mem.created_at) >= cutoff:
                candidates[mem.id] = mem

    if not candidates:
        return []

    q_vec = unpack(embed_text(q)) if q else None
    now = datetime.now(timezone.utc).timestamp()
    ranked: list[RankedMemory] = []

    for mem in candidates.values():
        reasons: list[str] = []
        imp = max(1, min(5, int(mem.importance or 1))) / 5.0
        rec = _recency_score(mem.created_at, now=now)
        kw = _keyword_score(q, mem.content)
        if kw > 0:
            reasons.append("keyword")
        sem = 0.0
        if q_vec is not None:
            try:
                row = repo._db.fetchone(  # noqa: SLF001 — intentional for embedding blob
                    "SELECT embedding FROM memories WHERE id = ?",
                    (mem.id,),
                )
                vec = unpack(row["embedding"]) if row else None
                if vec:
                    sem = max(0.0, cosine(q_vec, vec))
                    if sem > 0.15:
                        reasons.append("semantic")
            except Exception:
                pass
        if rec > 0.5:
            reasons.append("recent")
        if imp >= 0.6:
            reasons.append("important")

        # Weighted hybrid
        score = 0.35 * sem + 0.30 * kw + 0.20 * rec + 0.15 * imp
        if since_hours and "recent" in reasons:
            score += 0.1
        ranked.append(RankedMemory(memory=mem, score=score, reasons=reasons or ["fallback"]))

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:limit]


def format_recall_block(ranked: list[RankedMemory], *, max_chars: int = 400) -> str:
    if not ranked:
        return ""
    lines = ["[LONG-TERM MEMORY — use only if relevant]"]
    for item in ranked:
        cat = item.memory.category or "general"
        why = ",".join(item.reasons[:2])
        lines.append(f"- ({cat}/{why}) {item.memory.content}")
    block = "\n".join(lines)
    if len(block) > max_chars:
        block = block[:max_chars].rsplit("\n", 1)[0] + "\n- …"
    return block


def temporal_query_hours(text: str) -> Optional[float]:
    """Map phrases like 'dün' / 'yesterday' to a recency window."""
    lower = (text or "").lower()
    if any(w in lower for w in ("dün", "dun", "yesterday")):
        return 36.0
    if any(w in lower for w in ("bugün", "bugun", "today")):
        return 18.0
    if any(w in lower for w in ("geçen hafta", "gecen hafta", "last week")):
        return 24.0 * 8
    return None
