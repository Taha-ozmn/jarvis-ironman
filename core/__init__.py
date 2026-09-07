"""JARVIS 2.0 core package — event-driven Personal AI OS foundation."""

from __future__ import annotations

from core.event_bus import EventBus, Event

__all__ = ["JarvisOS", "EventBus", "Event"]


def __getattr__(name: str):
    """Load the heavyweight facade lazily to avoid system/core import cycles."""
    if name == "JarvisOS":
        from core.app import JarvisOS

        return JarvisOS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
