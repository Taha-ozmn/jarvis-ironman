"""Memory repository — keyword search first; embedding stub for later."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from memory.database import Database
from memory.embeddings import cosine, embed_text, unpack


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Memory:
    id: int
    key: Optional[str]
    content: str
    category: str
    importance: int
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Any) -> "Memory":
        return cls(
            id=row["id"],
            key=row["key"],
            content=row["content"],
            category=row["category"] or "general",
            importance=row["importance"] or 1,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class MemoryRepository:
    """CRUD + keyword search. Embeddings column reserved (NULL for now)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        content: str,
        *,
        key: Optional[str] = None,
        category: str = "general",
        importance: int = 1,
    ) -> Memory:
        content = content.strip()
        if not content:
            raise ValueError("Memory content is required")
        now = _utc_now()
        cursor = self._db.execute(
            """
            INSERT INTO memories (key, content, category, importance, embedding, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (key, content, category, importance, embed_text(content), now, now),
        )
        self._db.commit()
        return self.get(int(cursor.lastrowid))

    def get(self, memory_id: int) -> Memory:
        row = self._db.fetchone("SELECT * FROM memories WHERE id = ?", (memory_id,))
        if row is None:
            raise KeyError(f"Memory not found: {memory_id}")
        return Memory.from_row(row)

    def update(
        self,
        memory_id: int,
        *,
        content: Optional[str] = None,
        key: Optional[str] = None,
        category: Optional[str] = None,
        importance: Optional[int] = None,
    ) -> Memory:
        mem = self.get(memory_id)
        now = _utc_now()
        new_content = content if content is not None else mem.content
        emb = embed_text(new_content) if content is not None else None
        if emb is not None:
            self._db.execute(
                """
                UPDATE memories
                SET key = ?, content = ?, category = ?, importance = ?, embedding = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    key if key is not None else mem.key,
                    new_content,
                    category if category is not None else mem.category,
                    importance if importance is not None else mem.importance,
                    emb,
                    now,
                    memory_id,
                ),
            )
        else:
            self._db.execute(
                """
                UPDATE memories
                SET key = ?, content = ?, category = ?, importance = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    key if key is not None else mem.key,
                    new_content,
                    category if category is not None else mem.category,
                    importance if importance is not None else mem.importance,
                    now,
                    memory_id,
                ),
            )
        self._db.commit()
        return self.get(memory_id)

    def delete(self, memory_id: int) -> None:
        self.get(memory_id)
        self._db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._db.commit()

    def search(
        self,
        query: str,
        *,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> list[Memory]:
        """FTS5 / keyword search; empty query returns recent memories.
        For semantic ranking use search_semantic().
        """
        q = (query or "").strip()
        if not q:
            if category:
                rows = self._db.fetchall(
                    """
                    SELECT * FROM memories
                    WHERE category = ?
                    ORDER BY importance DESC, id DESC
                    LIMIT ?
                    """,
                    (category, limit),
                )
            else:
                rows = self._db.fetchall(
                    "SELECT * FROM memories ORDER BY importance DESC, id DESC LIMIT ?",
                    (limit,),
                )
            return [Memory.from_row(r) for r in rows]

        fts_hits = self._search_fts(q, category=category, limit=limit)
        if fts_hits is not None:
            return fts_hits

        like = f"%{q}%"
        if category:
            rows = self._db.fetchall(
                """
                SELECT * FROM memories
                WHERE category = ?
                  AND (content LIKE ? OR IFNULL(key, '') LIKE ?)
                ORDER BY importance DESC, id DESC
                LIMIT ?
                """,
                (category, like, like, limit),
            )
        else:
            rows = self._db.fetchall(
                """
                SELECT * FROM memories
                WHERE content LIKE ? OR IFNULL(key, '') LIKE ?
                ORDER BY importance DESC, id DESC
                LIMIT ?
                """,
                (like, like, limit),
            )
        # Multi-token OR expansion for lightweight semantic-ish recall
        tokens = [t for t in q.split() if len(t) > 2]
        if len(tokens) > 1 and len(rows) < limit:
            seen = {int(r["id"]) for r in rows}
            for token in tokens:
                like_t = f"%{token}%"
                more = self._db.fetchall(
                    """
                    SELECT * FROM memories
                    WHERE content LIKE ? OR IFNULL(key, '') LIKE ?
                    ORDER BY importance DESC, id DESC
                    LIMIT ?
                    """,
                    (like_t, like_t, limit),
                )
                for r in more:
                    rid = int(r["id"])
                    if rid in seen:
                        continue
                    if category and (r["category"] or "") != category:
                        continue
                    seen.add(rid)
                    rows.append(r)
                    if len(rows) >= limit:
                        break
                if len(rows) >= limit:
                    break
        return [Memory.from_row(r) for r in rows]

    def _search_fts(
        self,
        query: str,
        *,
        category: Optional[str],
        limit: int,
    ) -> Optional[list[Memory]]:
        """Return None if FTS unavailable so caller can fall back."""
        try:
            exists = self._db.fetchone(
                "SELECT 1 AS ok FROM sqlite_master WHERE type='table' AND name='memories_fts'"
            )
            if not exists:
                return None
            # Sanitize FTS query: quote tokens, join with OR
            tokens = re.findall(r"[A-Za-zğüşıöçĞÜŞİÖÇ0-9]{2,}", query)
            if not tokens:
                return None
            match = " OR ".join(f'"{t}"' for t in tokens[:8])
            if category:
                rows = self._db.fetchall(
                    """
                    SELECT m.* FROM memories m
                    WHERE m.category = ?
                      AND m.id IN (
                        SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?
                      )
                    ORDER BY m.importance DESC, m.id DESC
                    LIMIT ?
                    """,
                    (category, match, limit),
                )
            else:
                rows = self._db.fetchall(
                    """
                    SELECT m.* FROM memories m
                    WHERE m.id IN (
                      SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?
                    )
                    ORDER BY m.importance DESC, m.id DESC
                    LIMIT ?
                    """,
                    (match, limit),
                )
            return [Memory.from_row(r) for r in rows]
        except Exception:
            return None

    def upsert_by_key(
        self,
        key: str,
        content: str,
        *,
        category: str = "general",
        importance: int = 1,
    ) -> Memory:
        row = self._db.fetchone("SELECT id FROM memories WHERE key = ?", (key,))
        if row:
            return self.update(
                int(row["id"]),
                content=content,
                category=category,
                importance=importance,
            )
        return self.create(content, key=key, category=category, importance=importance)

    # --- Embeddings (local hashing) ---

    def store_embedding(self, memory_id: int, vector: bytes) -> None:
        self.get(memory_id)
        self._db.execute(
            "UPDATE memories SET embedding = ?, updated_at = ? WHERE id = ?",
            (vector, _utc_now(), memory_id),
        )
        self._db.commit()

    def ensure_embeddings(self, *, limit: int = 500) -> int:
        """Backfill missing embeddings. Returns count updated."""
        rows = self._db.fetchall(
            "SELECT id, content FROM memories WHERE embedding IS NULL LIMIT ?",
            (limit,),
        )
        n = 0
        for row in rows:
            self.store_embedding(int(row["id"]), embed_text(row["content"] or ""))
            n += 1
        return n

    def search_semantic(
        self,
        query: str,
        *,
        category: Optional[str] = None,
        limit: int = 10,
        min_score: float = 0.05,
    ) -> list[Memory]:
        """Cosine similarity over local embeddings; falls back to FTS/LIKE."""
        q = (query or "").strip()
        if not q:
            return self.search("", category=category, limit=limit)
        self.ensure_embeddings(limit=200)
        qvec = unpack(embed_text(q))
        if qvec is None:
            return self.search(q, category=category, limit=limit)
        if category:
            rows = self._db.fetchall(
                "SELECT * FROM memories WHERE category = ? AND embedding IS NOT NULL",
                (category,),
            )
        else:
            rows = self._db.fetchall(
                "SELECT * FROM memories WHERE embedding IS NOT NULL"
            )
        scored: list[tuple[float, Any]] = []
        for row in rows:
            vec = unpack(row["embedding"])
            if vec is None:
                continue
            score = cosine(qvec, vec)
            if score >= min_score:
                scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored:
            return [Memory.from_row(r) for _, r in scored[:limit]]
        # FTS fallback
        return self.search(q, category=category, limit=limit)
