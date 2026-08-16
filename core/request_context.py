"""Thread-local request correlation ids (Phase 2 observability)."""

from __future__ import annotations

import threading
import uuid
from typing import Optional

_local = threading.local()


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_request_id(request_id: Optional[str]) -> str:
    rid = (request_id or "").strip() or new_request_id()
    _local.request_id = rid
    return rid


def get_request_id() -> Optional[str]:
    return getattr(_local, "request_id", None)


def clear_request_id() -> None:
    if hasattr(_local, "request_id"):
        delattr(_local, "request_id")


def set_brain_path(path: Optional[str]) -> None:
    _local.brain_path = path


def get_brain_path() -> Optional[str]:
    return getattr(_local, "brain_path", None)
