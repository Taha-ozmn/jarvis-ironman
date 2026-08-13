"""Brain package — lazy export to avoid requiring cursor_sdk at import time."""

from __future__ import annotations

__all__ = ["JarvisBrain"]


def __getattr__(name: str):
    if name == "JarvisBrain":
        from brain.cursor_brain import JarvisBrain

        return JarvisBrain
    raise AttributeError(name)
