"""Config loader — preserves config.yaml backward compatibility."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_JARVIS2 = {
    "enabled": True,
    "soft_init": True,
    "db_path": "data/jarvis.db",
    # Phase 6: Level 3 allowed; dangerous ops still require ConfirmationGate (auto_approve false)
    "max_permission_level": 3,
    "auto_approve_dangerous": False,
    "automation": True,
    "automation_tick_seconds": 15,
    "automation_max_failures": 3,
    "confirm_timeout": 60,
    "memory_recall_limit": 4,
    "memory_recall_max_chars": 400,
    "plan_max_retries": 1,
    "tool_max_retries": 3,
    "backup_retention": 10,
    "file_watch_enabled": True,
    "mcp": {
        "enabled": True,
        "servers": [],  # e.g. [{name, command, args, transport: stdio}]
    },
    "proactive": {
        "enabled": True,
        "quiet_hours_start": 22,
        "quiet_hours_end": 7,
        "min_interval_seconds": 1800,
        "max_per_hour": 3,
        "daily_briefing_hour": 9,
        "daily_briefing_minute": 0,
        "seed_daily_briefing": False,
    },
}


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or (ROOT / "config.yaml")
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return ensure_jarvis2_defaults(data)


def ensure_jarvis2_defaults(config: dict[str, Any]) -> dict[str, Any]:
    j2 = dict(DEFAULT_JARVIS2)
    incoming = dict(config.get("jarvis2") or {})
    proactive = dict(DEFAULT_JARVIS2.get("proactive") or {})
    proactive.update(incoming.get("proactive") or {})
    mcp = dict(DEFAULT_JARVIS2.get("mcp") or {})
    mcp.update(incoming.get("mcp") or {})
    if "servers" not in mcp:
        mcp["servers"] = []
    j2.update(incoming)
    j2["proactive"] = proactive
    j2["mcp"] = mcp
    config["jarvis2"] = j2

    # Resolve workspace: "." / missing / stale absolute → repo root
    jarvis = dict(config.get("jarvis") or {})
    ws = str(jarvis.get("workspace") or "").strip()
    ws_path = Path(ws).expanduser() if ws else None
    if not ws or ws in (".", "./") or ws_path is None or not ws_path.exists():
        jarvis["workspace"] = str(ROOT)
        config["jarvis"] = jarvis
    return config


def save_config(config: dict[str, Any], path: Path | None = None) -> None:
    config_path = path or (ROOT / "config.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)
