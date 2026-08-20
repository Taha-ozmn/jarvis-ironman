"""Detect elevated-risk shell / filesystem / credential operations."""

from __future__ import annotations

import re
from pathlib import Path

# Absolute block — refuse without offering execution.
BLOCKED_SHELL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\brm\s+(-[a-zA-Z]+\s+)*/\s*$",
        r"\brm\s+-rf\s+/\s*$",
        r"\brm\s+-rf\s+/\*",
        r"\brm\s+-fr\s+/\s*$",
        r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+/\s*$",
        r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\s+/\s*$",
        r"\bmkfs\b",
        r"\bdiskutil\s+(eraseDisk|eraseVolume|partitionDisk)\b",
        r"\bdiskutil\s+erase\b",
        r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;",
    )
)

# Patterns that force PermissionLevel.DANGEROUS + confirmation.
DANGEROUS_SHELL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bsudo\b",
        r"\brm\s+(-[a-zA-Z]*f|-[a-zA-Z]*r)",
        r"\brm\s+-rf\b",
        r"\bdd\s+if=",
        r"\bchmod\s+-R\s+777\b",
        r">\s*/dev/sd",
        r"\bdiskutil\s+(erase|partition)",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bcurl\b.+\|\s*(ba)?sh\b",
        r"\bwget\b.+\|\s*(ba)?sh\b",
        r"\bchown\s+-R\b",
        r"/System/",
        r"\blaunchctl\s+bootout\b",
        r"\bgit\s+push\b.*(--force|-f)\b",
        r"\bgit\s+push\s+--force\b",
        r"\bgit\s+push\s+-f\b",
    )
)

CREDENTIAL_PATH_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(^|/)\.env(\.|$)",
        r"\.pem$",
        r"(^|/)id_rsa",
        r"(^|/)id_ed25519",
        r"credentials\.json",
        r"\.aws/credentials",
        r"secrets?\.(ya?ml|json|toml|env)",
        r"api[_-]?keys?\.(ya?ml|json|txt)",
        r"\.netrc$",
        r"\.pgpass$",
        r"keystore",
        r"\.p12$",
        r"\.pfx$",
    )
)


def is_blocked_shell(command: str) -> bool:
    """Hard-refuse destructive commands (never execute)."""
    text = (command or "").strip()
    if not text:
        return False
    return any(p.search(text) for p in BLOCKED_SHELL_PATTERNS)


def is_dangerous_shell(command: str) -> bool:
    text = (command or "").strip()
    if not text:
        return False
    if is_blocked_shell(text):
        return True
    return any(p.search(text) for p in DANGEROUS_SHELL_PATTERNS)


def is_force_git_push(command: str = "", *, force_flag: bool = False) -> bool:
    if force_flag:
        return True
    text = (command or "").strip()
    if not text:
        return False
    return bool(
        re.search(r"\bgit\s+push\b.*(--force|-f)\b", text, re.I)
        or re.search(r"\bgit\s+push\s+(-f|--force)\b", text, re.I)
    )


def is_credential_path(path: str) -> bool:
    text = (path or "").strip()
    if not text:
        return False
    # Normalize for matching
    try:
        text = str(Path(text).expanduser())
    except Exception:
        pass
    return any(p.search(text) for p in CREDENTIAL_PATH_PATTERNS)


def is_dangerous_path_op(path: str, *, delete: bool = False) -> bool:
    """Flag deletes under home root or system paths as dangerous."""
    lower = (path or "").strip().lower()
    if not lower:
        return delete
    if is_credential_path(path):
        return True
    sensitive = (
        "/",
        "/system",
        "/library",
        "/applications",
        "/usr",
        "/bin",
        "/sbin",
        "/etc",
        "~",
        str(Path.home()).lower(),
    )
    if delete and lower.rstrip("/") in {s.rstrip("/") for s in sensitive}:
        return True
    if any(lower.startswith(s + "/") or lower == s for s in ("/system", "/library", "/usr")):
        return True
    return False
