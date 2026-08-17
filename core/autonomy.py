"""Progressive autonomy levels (master spec §71) — confirm thresholds.

Level 1 — Ask before any tool execution
Level 2 — Auto READ (0); confirm LOCAL+
Level 3 — Auto READ/LOCAL; confirm SYSTEM+
Level 4 — Auto through SYSTEM; confirm DANGEROUS only
          (auto_approve_dangerous may skip DANGEROUS confirm)

Default level 4 preserves historical JARVIS 2.0 behavior.
"""

from __future__ import annotations

from dataclasses import dataclass

from security.permissions import PermissionLevel


@dataclass(frozen=True)
class AutonomyPolicy:
    level: int
    confirm_at_or_above: int
    label: str


_LEVELS: dict[int, AutonomyPolicy] = {
    1: AutonomyPolicy(1, int(PermissionLevel.READ), "ask_all"),
    2: AutonomyPolicy(2, int(PermissionLevel.LOCAL), "auto_safe"),
    3: AutonomyPolicy(3, int(PermissionLevel.SYSTEM), "auto_medium"),
    4: AutonomyPolicy(4, int(PermissionLevel.DANGEROUS), "auto_high"),
}


def clamp_autonomy_level(raw: object, *, default: int = 4) -> int:
    try:
        level = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(1, min(4, level))


def autonomy_policy(level: object, *, default: int = 4) -> AutonomyPolicy:
    return _LEVELS[clamp_autonomy_level(level, default=default)]


def requires_confirmation(
    permission_level: int | PermissionLevel,
    policy: AutonomyPolicy,
    *,
    auto_approve_dangerous: bool = False,
) -> bool:
    """True when ExecutionEngine must block for HUD/voice confirm."""
    pl = int(permission_level)
    if pl < policy.confirm_at_or_above:
        return False
    if (
        auto_approve_dangerous
        and policy.level >= 4
        and pl >= int(PermissionLevel.DANGEROUS)
    ):
        return False
    return True


# --- Plan dry-run / step budget helpers ---

_DRY_RUN_HINTS = (
    "dry run",
    "dry-run",
    "dryrun",
    "show plan",
    "plan only",
    "sadece plan",
    "ne yapacağını göster",
    "ne yapacagini goster",
    "without executing",
    "execute etme",
    "çalıştırma",
    "calistirma",
)


def is_dry_run_request(text: str) -> bool:
    lower = (text or "").strip().lower()
    if not lower:
        return False
    return any(h in lower for h in _DRY_RUN_HINTS)


def strip_dry_run_markers(text: str) -> str:
    """Remove dry-run phrasing so the planner sees the real goal."""
    import re

    out = (text or "").strip()
    for hint in _DRY_RUN_HINTS:
        out = re.sub(re.escape(hint), " ", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out).strip(" .,;:-")
    return out or (text or "").strip()


def clamp_max_agent_steps(raw: object, *, default: int = 12) -> int:
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(1, min(64, n))
