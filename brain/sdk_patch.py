"""Workarounds for known cursor-sdk bridge bugs.

1. Auth tokens starting with '-' crash the bridge arg parser.
2. version("cursor-sdk") can return None, injecting a None env var that
   crashes subprocess.Popen when the bridge launches.
3. Default unary/read timeouts are too aggressive on slow Agent.create —
   bump connect/read budgets so brain start does not fail with empty
   ReadTimeout spam.
"""

from __future__ import annotations

import os
import secrets

_applied = False

_FALLBACK_SDK_VERSION = "0.1.8"

# Bridge HTTP (Agent.create / unary RPCs) — seconds
DEFAULT_UNARY_TIMEOUT_SEC = 120.0
DEFAULT_STREAM_TIMEOUT_SEC = 900.0
DEFAULT_BRIDGE_DISCOVERY_SEC = 60.0


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


def _patch_sdk_timeouts() -> None:
    """Increase Cursor SDK HTTP / bridge discovery timeouts when possible."""
    try:
        import cursor_sdk._connect as connect

        connect.DEFAULT_UNARY_TIMEOUT_SECONDS = float(
            os.environ.get(
                "JARVIS_BRIDGE_UNARY_TIMEOUT",
                str(DEFAULT_UNARY_TIMEOUT_SEC),
            )
        )
        connect.DEFAULT_STREAM_TIMEOUT_SECONDS = float(
            os.environ.get(
                "JARVIS_BRIDGE_STREAM_TIMEOUT",
                str(DEFAULT_STREAM_TIMEOUT_SEC),
            )
        )
    except Exception:
        pass

    try:
        import cursor_sdk._bridge as bridge_mod

        _orig_launch = bridge_mod.Bridge.launch.__func__  # type: ignore[attr-defined]

        def _launch_with_longer_discovery(cls, *args, **kwargs):
            discovery = float(
                os.environ.get(
                    "JARVIS_BRIDGE_DISCOVERY_TIMEOUT",
                    str(DEFAULT_BRIDGE_DISCOVERY_SEC),
                )
            )
            current = kwargs.get("timeout")
            if current is None:
                kwargs["timeout"] = discovery
            else:
                try:
                    if float(current) <= 30.0:
                        kwargs["timeout"] = discovery
                except (TypeError, ValueError):
                    kwargs["timeout"] = discovery
            return _orig_launch(cls, *args, **kwargs)

        bridge_mod.Bridge.launch = classmethod(_launch_with_longer_discovery)  # type: ignore[method-assign]
    except Exception:
        pass


def apply_sdk_patch() -> None:
    """Patch cursor-sdk before Agent.create / launch_bridge."""
    global _applied
    if _applied:
        return

    _fix_bridge_version_env()
    _patch_sdk_timeouts()

    try:
        from cursor_sdk import _store_callback, _tool_callback
    except ImportError:
        # Incomplete/mock SDK (tests) — version env fix above is still applied.
        _applied = True
        return

    def _safe_auth_token() -> str:
        while True:
            token = secrets.token_urlsafe(32)
            if not token.startswith("-"):
                return token

    _tool_callback._new_auth_token = _safe_auth_token
    _store_callback._new_auth_token = _safe_auth_token
    _applied = True
