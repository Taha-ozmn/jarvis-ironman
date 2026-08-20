"""Thread-local request correlation for latency + audit (no heavy tracing)."""

from __future__ import annotations

import threading
from typing import Optional

_local = threading.local()


def set_request_id(request_id: Optional[str]) -> None:
    _local.request_id = (request_id or "")[:32] or None


def get_request_id() -> Optional[str]:
    return getattr(_local, "request_id", None)


def clear_request_id() -> None:
    _local.request_id = None


def set_brain_path(path: Optional[str]) -> None:
    _local.brain_path = (path or "")[:16] or None


def get_brain_path() -> Optional[str]:
    return getattr(_local, "brain_path", None)
