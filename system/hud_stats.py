"""Live telemetry for Iron Man HUD."""

from __future__ import annotations

import datetime
import shutil
import time
from typing import Any, Callable, Optional

# Shared with host_metrics; kept for HUD consumers / tests.
_METRICS_CACHE: dict[str, Any] = {"ts": 0.0, "cpu": 0, "mem": 0, "swap": 0}



def format_hud_model(
    jarvis_config: dict[str, Any] | None = None,
    *,
    brain_model: str | None = None,
    brain_ready: bool | None = None,
) -> str:
    """Human-readable provider label for HUD — not a stale hardcoded Gemini string."""
    cfg = jarvis_config or {}
    provider = str(cfg.get("llm_provider", "cursor")).strip().lower()
    model = (brain_model or cfg.get("model") or "composer-2.5").strip()
    if provider in ("cursor", "cursor-agent", "cursor_sdk"):
        return f"Cursor · {model}"
    if provider:
        return f"{provider} · {model}"
    return model


def format_cursor_bridge_status(*, brain_ready: bool | None = None) -> str:
    if brain_ready is True:
        return "BRIDGE OK"
    if brain_ready is False:
        return "CONNECTING"
    return "BRIDGE OK"


def get_telemetry(
    jarvis_config: dict[str, Any] | str | None = None,
    *,
    brain_model: str | None = None,
    brain_ready: bool | None = None,
) -> dict[str, Any]:
    """Build HUD telemetry snapshot.

    Accepts legacy ``model: str`` for backward compatibility.
    """
    cfg: dict[str, Any]
    if isinstance(jarvis_config, str):
        cfg = {"model": jarvis_config, "llm_provider": "cursor"}
        if brain_model is None:
            brain_model = jarvis_config
    else:
        cfg = jarvis_config or {}

    now = datetime.datetime.now()
    hour = now.hour
    if hour < 12:
        period = "MORNING"
    elif hour < 18:
        period = "AFTERNOON"
    else:
        period = "EVENING"

    from system.host_metrics import get_host_metrics

    host = get_host_metrics()
    cpu = int(host.get("cpu_pct") or 0)
    mem = int(host.get("mem_pct") or 0)
    swap_mb = int(host.get("swap_used_mb") or 0)
    _METRICS_CACHE.update(ts=time.monotonic(), cpu=cpu, mem=mem, swap=swap_mb)

    disk = shutil.disk_usage("/")
    disk_pct = int(disk.used / disk.total * 100) if disk.total else 0
    model_label = format_hud_model(
        cfg,
        brain_model=brain_model,
        brain_ready=brain_ready,
    )
    systems = "LIGHT" if host.get("light_mode") else (
        "STRESSED" if mem >= 85 or cpu >= 80 else "NOMINAL"
    )

    return {
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%d %b %Y").upper(),
        "period": period,
        "cpu": f"{cpu}%",
        "memory": f"{mem}%",
        "swap": f"{swap_mb}MB",
        "disk": f"{disk_pct}%",
        "model": model_label,
        "neural": "ONLINE" if brain_ready is not False else "CONNECTING",
        "voice": "EMEL NEURAL",
        "macos": "CONNECTED",
        "cursor": format_cursor_bridge_status(brain_ready=brain_ready),
        "systems": systems,
    }


def _cached_cpu_memory() -> tuple[int, int]:
    """Compatibility helper for tests — uses shared host metrics cache."""
    from system.host_metrics import get_host_metrics

    host = get_host_metrics()
    return int(host.get("cpu_pct") or 0), int(host.get("mem_pct") or 0)


def _memory_used() -> int:
    """Test hook — percent RAM used."""
    return _cached_cpu_memory()[1]


def make_telemetry_supplier(
    jarvis_config: dict[str, Any],
    *,
    brain_model_fn: Optional[Callable[[], str | None]] = None,
    brain_ready_fn: Optional[Callable[[], bool]] = None,
) -> Callable[[], dict[str, Any]]:
    """Factory for UI/server telemetry polling."""

    def _supply() -> dict[str, Any]:
        model = brain_model_fn() if brain_model_fn else None
        ready = brain_ready_fn() if brain_ready_fn else None
        return get_telemetry(
            jarvis_config,
            brain_model=model,
            brain_ready=ready,
        )

    return _supply
