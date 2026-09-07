"""Structured execution evidence used to prevent false success claims."""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

from tools.base import ToolResult


@dataclass(frozen=True)
class Evidence:
    """Immutable record of what a tool actually returned."""

    tool_name: str
    ok: bool
    summary: str
    error: str = ""
    started_at: float = 0.0
    duration_ms: float = 0.0
    output_hash: str = ""
    verified: bool = False
    verification_message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_evidence(
    tool_name: str,
    result: ToolResult,
    *,
    started_at: Optional[float] = None,
    verified: bool = False,
    verification_message: str = "",
) -> Evidence:
    """Create bounded, non-secret evidence from a tool result."""
    raw = result.data if isinstance(result.data, str) else ""
    summary = raw.strip()[:500]
    error = (result.error or "").strip()[:500]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16] if raw else ""
    start = started_at or time.monotonic()
    return Evidence(
        tool_name=tool_name,
        ok=bool(result.ok),
        summary=summary,
        error=error,
        started_at=start,
        duration_ms=max(0.0, (time.monotonic() - start) * 1000.0),
        output_hash=digest,
        verified=verified,
        verification_message=(verification_message or "")[:300],
    )
