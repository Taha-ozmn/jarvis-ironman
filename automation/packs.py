"""Load automation YAML packs into AutomationEngine (Phase 8+)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _load_yaml(path: Path) -> Optional[dict[str, Any]]:
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning("PyYAML not installed — skip automation pack %s", path.name)
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("failed to parse automation pack %s", path)
        return None
    return data if isinstance(data, dict) else None


def load_automation_packs(
    automation: Any,
    packs_dir: Path,
    *,
    enabled_default: bool = False,
) -> list[str]:
    """Create rules from *.yaml in packs_dir. Idempotent by rule name."""
    if not packs_dir.is_dir():
        return []
    existing = {r.name for r in automation.list_rules()}
    loaded: list[str] = []
    for path in sorted(packs_dir.glob("*.yaml")) + sorted(packs_dir.glob("*.yml")):
        data = _load_yaml(path)
        if not data:
            continue
        name = str(data.get("name") or path.stem).strip()
        if not name or name in existing:
            continue
        trigger = data.get("trigger") or {}
        action = data.get("action") or {}
        if not isinstance(trigger, dict):
            trigger = {}
        if not isinstance(action, dict):
            action = {}
        trigger_type = str(trigger.get("type") or data.get("trigger_type") or "manual")
        enabled = bool(data.get("enabled", enabled_default))
        try:
            automation.create_rule(
                name,
                trigger_type=trigger_type,
                trigger_spec=trigger,
                action_spec=action,
                enabled=enabled,
            )
            loaded.append(name)
            existing.add(name)
        except Exception:
            logger.exception("failed to create automation from pack %s", path.name)
    return loaded
