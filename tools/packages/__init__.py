"""Plugin registration hooks — add tools without editing core (Phase 3)."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

PluginFn = Callable[[ToolRegistry, dict[str, Any]], None]

_PLUGINS: dict[str, PluginFn] = {}


def register_plugin(name: str, fn: PluginFn) -> None:
    if not name or not callable(fn):
        raise ValueError("plugin name and callable required")
    _PLUGINS[name] = fn
    logger.info("plugin registered: %s", name)


def unregister_plugin(name: str) -> None:
    _PLUGINS.pop(name, None)


def list_plugins() -> list[str]:
    return sorted(_PLUGINS.keys())


def load_plugins(registry: ToolRegistry, context: Optional[dict[str, Any]] = None) -> list[str]:
    """Invoke all registered plugins. Failures are isolated."""
    ctx = context or {}
    loaded: list[str] = []
    for name, fn in list(_PLUGINS.items()):
        try:
            fn(registry, ctx)
            loaded.append(name)
        except Exception:
            logger.exception("plugin %s failed", name)
    return loaded
