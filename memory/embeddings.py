"""Lightweight local embeddings — hashing trick, no heavy ML deps.

Offline-first. Vectors are float32 little-endian blobs stored in memories.embedding.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from typing import Iterable

DIM = 256
_TOKEN_RE = re.compile(r"[A-Za-zğüşıöçĞÜŞİÖÇ0-9]{2,}")


def embed_text(text: str, *, dim: int = DIM) -> bytes:
    """Hashing-trick bag-of-tokens embedding → float32 bytes."""
    vec = [0.0] * dim
    tokens = _TOKEN_RE.findall((text or "").lower())
    if not tokens:
        return _pack(vec)
    for tok in tokens:
        h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        sign = 1.0 if (h[4] & 1) == 0 else -1.0
        vec[idx] += sign
        # bigram with next if short
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    vec = [v / norm for v in vec]
    return _pack(vec)


def unpack(blob: bytes | memoryview | None, *, dim: int = DIM) -> list[float] | None:
    if not blob:
        return None
    raw = bytes(blob)
    expected = dim * 4
    if len(raw) != expected:
        return None
    return list(struct.unpack("<" + "f" * dim, raw))


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    aa = list(a)
    bb = list(b)
    if len(aa) != len(bb) or not aa:
        return 0.0
    dot = sum(x * y for x, y in zip(aa, bb))
    na = math.sqrt(sum(x * x for x in aa)) or 1.0
    nb = math.sqrt(sum(y * y for y in bb)) or 1.0
    return dot / (na * nb)


def _pack(vec: list[float]) -> bytes:
    return struct.pack("<" + "f" * len(vec), *vec)


def embedding_status() -> dict:
    return {
        "engine": "hashing-trick",
        "dim": DIM,
        "deps": "stdlib only",
        "note": "Local semantic similarity without sentence-transformers",
    }
