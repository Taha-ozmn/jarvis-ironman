"""Execution evidence — never claim success without recorded proof (Phase 7)."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class ExecutionEvidence:
    tool: str
    input: dict[str, Any]
    output: Any = None
    status: str = "ok"  # ok | error | cancelled | verified
    duration_ms: float = 0.0
    error: Optional[str] = None
    verified: bool = False
    request_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "verified") and not self.error


class EvidenceClock:
    """Simple timer helper for tool calls."""

    def __init__(self) -> None:
        self._t0 = time.perf_counter()

    def ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0


def claim_allowed(evidence: Optional[ExecutionEvidence], claim: str = "") -> bool:
    """True only when evidence shows verified success."""
    if evidence is None:
        return False
    if not evidence.ok:
        return False
    return True
