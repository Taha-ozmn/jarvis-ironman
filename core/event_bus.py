"""Typed publish/subscribe event bus for JARVIS 2.0."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, DefaultDict, Optional

logger = logging.getLogger(__name__)

Handler = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    """Immutable event payload."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "system"
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """Thread-safe in-process pub/sub bus.

    Handlers run synchronously on the publisher thread by default so ordering
    stays predictable for local orchestration. Use ``async_dispatch=True`` for
    fire-and-forget background delivery.
    """

    def __init__(self, *, async_dispatch: bool = False) -> None:
        self._async = async_dispatch
        self._lock = threading.RLock()
        self._handlers: DefaultDict[str, list[Handler]] = defaultdict(list)
        self._wildcard: list[Handler] = []
        self._history: list[Event] = []
        self._max_history = 200

    def subscribe(self, event_type: str, handler: Handler) -> None:
        with self._lock:
            if event_type == "*":
                self._wildcard.append(handler)
            else:
                self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        with self._lock:
            if event_type == "*":
                if handler in self._wildcard:
                    self._wildcard.remove(handler)
                return
            handlers = self._handlers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)

    def publish(
        self,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        source: str = "system",
    ) -> Event:
        event = Event(type=event_type, payload=payload or {}, source=source)
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]
            handlers = list(self._handlers.get(event_type, [])) + list(self._wildcard)

        for handler in handlers:
            self._dispatch(handler, event)
        return event

    def _dispatch(self, handler: Handler, event: Event) -> None:
        if self._async:
            threading.Thread(
                target=self._safe_call,
                args=(handler, event),
                daemon=True,
            ).start()
        else:
            self._safe_call(handler, event)

    @staticmethod
    def _safe_call(handler: Handler, event: Event) -> None:
        try:
            handler(event)
        except Exception:
            logger.exception("Event handler failed for %s", event.type)

    def recent(self, limit: int = 20) -> list[Event]:
        with self._lock:
            return list(self._history[-limit:])

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()
