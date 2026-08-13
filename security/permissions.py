"""Permission levels 0–3 for JARVIS tool execution."""

from __future__ import annotations

from enum import IntEnum


class PermissionLevel(IntEnum):
    """Ascending capability / risk."""

    READ = 0
    LOCAL = 1
    SYSTEM = 2
    DANGEROUS = 3


LEVEL_LABELS = {
    PermissionLevel.READ: "read",
    PermissionLevel.LOCAL: "local",
    PermissionLevel.SYSTEM: "system",
    PermissionLevel.DANGEROUS: "dangerous",
}


class PermissionGate:
    """Allow actions whose required level is <= configured max."""

    def __init__(self, max_level: PermissionLevel = PermissionLevel.SYSTEM) -> None:
        if not isinstance(max_level, PermissionLevel):
            max_level = PermissionLevel(int(max_level))
        self.max_level = max_level

    def allows(self, required: PermissionLevel) -> bool:
        return int(required) <= int(self.max_level)

    def require(self, required: PermissionLevel) -> None:
        if not self.allows(required):
            raise PermissionError(
                f"Requires {LEVEL_LABELS[required]} (level {int(required)}); "
                f"max allowed is {LEVEL_LABELS[self.max_level]} (level {int(self.max_level)})"
            )

    def label(self) -> str:
        return LEVEL_LABELS[self.max_level]
