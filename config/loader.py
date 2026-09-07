"""Config loader — preserves config.yaml backward compatibility."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
PERSONALITY_PATH = Path(__file__).resolve().parent / "personality.yaml"

DEFAULT_PERSONALITY = {
    "name": "J.A.R.V.I.S.",
    "persona": "iron_man",
    "style": "calm_british_butler",
    "address_style": "name_first",
    "language": "en-GB",
    "reply_language": "en",
    "understand": "tr+en",
    "voice_hint": "en-GB-RyanNeural",
    "traits": ["calm", "smart", "direct", "lightly_witty", "professional", "verify_before_claim"],
    "speech": {
        "max_chars": 280,
        "ack_short": True,
        "forbid_phrases": [
            "efendim",
            "Bakıyorum.",
            "Cursor",
            "language model",
            "chatbot",
            "at your service",
        ],
    },
    "behavior": {
        "prefer_local_tools": True,
        "confirm_after_tool_success_only": True,
        "turkish_only_replies": False,
    },
}

DEFAULT_JARVIS2 = {
    "enabled": True,
    "soft_init": True,
    "db_path": "data/jarvis.db",
    "autonomy_profile": "safe",
    # Level 3 allowed. full_autonomy auto-approves L3 with audit; catastrophic still blocked.
    "max_permission_level": 3,
    "auto_approve_level_0_1_2": True,
    "full_autonomy": False,
    "auto_approve_dangerous": False,
    "automation": True,
    "automation_tick_seconds": 30,
    "automation_max_failures": 3,
    "confirm_timeout": 60,
    "checkpoint_path": "data/plan_checkpoint.json",
    "memory_recall_limit": 3,
    "memory_recall_max_chars": 300,
    "weather_default_location": "",
    "weather_timeout": 8,
    "plan_max_retries": 1,
    "max_plan_steps": 12,
    "workspace_only": True,
    "plan_timeout_sec": 300,
    "deep_max_iterations": 8,
    "brain_start_timeout_sec": 15,
    "max_progress_updates": 3,
    "progress_interval_sec": 30,
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

DEFAULT_COST = {
    "enabled": True,
    "currency": "USD",
    "chars_per_token": 4,
    # USD per 1 million tokens — placeholders, not invoices. Fill with your Cursor rates.
    "rates": {
        "default": {"input_per_million": 0.0, "output_per_million": 0.0},
        "composer-2.5": {"input_per_million": 0.0, "output_per_million": 0.0},
    },
}

DEFAULT_SCREEN = {
    "always_watch": True,
    "poll_interval_sec": 15,
    "screenshot_on_change": True,
    "screenshot_min_interval_sec": 90,
}


def load_personality(path: Path | None = None) -> dict[str, Any]:
    """Load config/personality.yaml — never raises; falls back to defaults."""
    personality = dict(DEFAULT_PERSONALITY)
    p = path or PERSONALITY_PATH
    if not p.exists():
        return personality
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            personality.update(raw)
            speech = dict(DEFAULT_PERSONALITY.get("speech") or {})
            speech.update(raw.get("speech") or {})
            behavior = dict(DEFAULT_PERSONALITY.get("behavior") or {})
            behavior.update(raw.get("behavior") or {})
            personality["speech"] = speech
            personality["behavior"] = behavior
    except Exception:
        return dict(DEFAULT_PERSONALITY)
    return personality


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
    profile = str(j2.get("autonomy_profile") or "safe").strip().lower()
    if profile not in {"safe", "full", "readonly"}:
        profile = "safe"
    j2["autonomy_profile"] = profile
    if profile == "safe":
        j2["full_autonomy"] = False
        j2["auto_approve_dangerous"] = False
        j2["workspace_only"] = True
    elif profile == "readonly":
        j2["max_permission_level"] = min(
            int(j2.get("max_permission_level", 3)),
            1,
        )
        j2["full_autonomy"] = False
        j2["auto_approve_dangerous"] = False
    elif profile == "full":
        # Selecting this profile is itself the explicit opt-in. Catastrophic
        # shell patterns remain hard-blocked in ExecutionEngine.
        j2["full_autonomy"] = bool(incoming.get("full_autonomy", True))
    config["jarvis2"] = j2
    screen = dict(DEFAULT_SCREEN)
    screen.update(config.get("screen") or {})
    config["screen"] = screen
    cost = dict(DEFAULT_COST)
    incoming_cost = dict(config.get("cost") or {})
    rates = dict(DEFAULT_COST.get("rates") or {})
    rates.update(incoming_cost.get("rates") or {})
    cost.update(incoming_cost)
    cost["rates"] = rates
    config["cost"] = cost
    # Personality file overrides jarvis.persona / speech hints lightly
    personality = load_personality()
    config["personality"] = personality
    jarvis = dict(config.get("jarvis") or {})
    if personality.get("persona"):
        jarvis.setdefault("persona", personality["persona"])
    speech = personality.get("speech") or {}
    if speech.get("max_chars"):
        jarvis.setdefault("max_speech_chars", int(speech["max_chars"]))
    if personality.get("language"):
        jarvis.setdefault("language", personality["language"])
    config["jarvis"] = jarvis
    return config


def save_config(config: dict[str, Any], path: Path | None = None) -> None:
    config_path = path or (ROOT / "config.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)
