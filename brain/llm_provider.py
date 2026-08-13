"""LLM provider protocol — central routing without rewriting Cursor brain."""

from __future__ import annotations

from typing import Mapping, Optional, Protocol, runtime_checkable

from brain.model_router import ModelRouter


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal text completion surface for planner / extract hooks."""

    def complete(
        self,
        prompt: str,
        *,
        category: str = "chat",
        timeout: float = 20.0,
    ) -> str:
        ...

    def available(self) -> bool:
        ...


class NullProvider:
    """Offline / unavailable brain — always empty."""

    def complete(
        self,
        prompt: str,
        *,
        category: str = "chat",
        timeout: float = 20.0,
    ) -> str:
        _ = (prompt, category, timeout)
        return ""

    def available(self) -> bool:
        return False


class CursorProvider:
    """Thin wrapper around JarvisBrain when present; never raises into callers."""

    def __init__(self, brain: object | None = None, router: ModelRouter | None = None) -> None:
        self._brain = brain
        self._router = router

    def bind_brain(self, brain: object | None) -> None:
        self._brain = brain

    def available(self) -> bool:
        brain = self._brain
        if brain is None:
            return False
        return bool(getattr(brain, "ready", False) or getattr(brain, "_agent", None))

    def pick_model(self, category: str) -> Optional[str]:
        if self._router is None:
            return None
        try:
            return self._router.pick(category)
        except Exception:
            return None

    def complete(
        self,
        prompt: str,
        *,
        category: str = "chat",
        timeout: float = 20.0,
    ) -> str:
        brain = self._brain
        if brain is None or not prompt.strip():
            return ""
        # Prefer a lightweight sync think hook if exposed
        fn = getattr(brain, "think_sync", None) or getattr(brain, "quick_complete", None)
        if callable(fn):
            try:
                out = fn(prompt, timeout=timeout)
                return str(out or "").strip()
            except Exception:
                return ""
        # Fallback: no safe sync API — stay offline for planner
        _ = (category, timeout)
        return ""


def build_default_router(models: Mapping[str, str] | None, default: str) -> ModelRouter:
    models = dict(models or {})
    return ModelRouter(models, default, resolve=lambda x: x)
