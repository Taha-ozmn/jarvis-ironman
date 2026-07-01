"""Workarounds for known cursor-sdk bridge bugs.

1. Auth tokens starting with '-' crash the bridge arg parser.
2. version("cursor-sdk") can return None, injecting a None env var that
   crashes subprocess.Popen when the bridge launches.
"""

from __future__ import annotations

import os
import secrets

_applied = False

_FALLBACK_SDK_VERSION = "0.1.8"


def _fix_bridge_version_env() -> None:
    """Ensure CURSOR_SDK_PYTHON_VERSION is a real string before bridge launch.

    The bridge sets env[CURSOR_SDK_PYTHON_VERSION] = version("cursor-sdk").
    On some installs version() returns None, which crashes Popen. Pre-setting
    the env var makes the SDK skip that lookup entirely.
    """
    try:
        from importlib.metadata import version

        resolved = version("cursor-sdk")
    except Exception:
        resolved = None

    if not isinstance(resolved, str) or not resolved:
        resolved = _FALLBACK_SDK_VERSION

    os.environ.setdefault("CURSOR_SDK_PYTHON_VERSION", resolved)
    if not os.environ.get("CURSOR_SDK_PYTHON_VERSION"):
        os.environ["CURSOR_SDK_PYTHON_VERSION"] = resolved


def apply_sdk_patch() -> None:
    """Patch cursor-sdk before Agent.create / launch_bridge."""
    global _applied
    if _applied:
        return

    _fix_bridge_version_env()

    from cursor_sdk import _store_callback, _tool_callback

    def _safe_auth_token() -> str:
        while True:
            token = secrets.token_urlsafe(32)
            if not token.startswith("-"):
                return token

    _tool_callback._new_auth_token = _safe_auth_token
    _store_callback._new_auth_token = _safe_auth_token
    _applied = True
