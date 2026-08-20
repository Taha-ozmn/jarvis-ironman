"""Thin REST API beside the HUD WebSocket — aiohttp, FastAPI-like JSON.

Core stays callable without HUD: handlers accept JarvisOS + optional
process_command callback. Routes never require a browser client.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional
from uuid import uuid4

from aiohttp import web

from core.request_context import set_brain_path, set_request_id

logger = logging.getLogger(__name__)

CommandFn = Callable[[str], Optional[str]]
HealthFn = Callable[[], dict[str, Any]]
StateFn = Callable[[], dict[str, Any]]


def build_health(os_core: Any = None) -> dict[str, Any]:
    """Subsystem snapshot — honest optional extras (MCP / Playwright)."""
    payload: dict[str, Any] = {
        "ok": True,
        "status": "ok",
        "hud_required": False,
    }
    if os_core is None:
        payload["core"] = "not_loaded"
        return payload
    payload["core"] = "loaded"
    try:
        payload["autonomy"] = os_core.security_profile()
    except Exception as err:
        payload["autonomy"] = {"error": str(err)}
    try:
        from tools.browser_playwright import playwright_status

        payload["playwright"] = playwright_status()
    except Exception as err:
        payload["playwright"] = {"available": False, "error": str(err)}
    try:
        mcp = getattr(os_core, "mcp", None)
        payload["mcp"] = mcp.status() if mcp is not None else {"runtime": False}
    except Exception as err:
        payload["mcp"] = {"runtime": False, "error": str(err)}
    try:
        meter = getattr(os_core, "cost_meter", None)
        if meter is not None:
            payload["cost"] = meter.totals()
    except Exception:
        payload["cost"] = {}
    return payload


def build_state(os_core: Any = None) -> dict[str, Any]:
    if os_core is None:
        return {"available": False, "reason": "JARVIS core not loaded"}
    try:
        snap = os_core.state.snapshot()
        data = snap.as_dict() if hasattr(snap, "as_dict") else dict(snap)
        data["available"] = True
        return data
    except Exception as err:
        return {"available": False, "reason": str(err)}


def dispatch_command(
    text: str,
    *,
    os_core: Any = None,
    command_fn: Optional[CommandFn] = None,
) -> dict[str, Any]:
    """Run FastBrain via JarvisOS; optional JarvisCore.process_command fallback."""
    command = (text or "").strip()
    rid = uuid4().hex[:12]
    set_request_id(rid)
    if not command:
        return {"ok": False, "error": "empty command", "request_id": rid}

    speech: Optional[str] = None
    path = "unknown"
    # Full JarvisCore handler takes precedence (includes Fast + Deep + speak).
    if command_fn is not None:
        try:
            speech = command_fn(command)
            path = str(getattr(os_core, "_last_brain_path", None) or "core")
            return {
                "ok": True,
                "speech": speech or "",
                "path": path,
                "request_id": rid,
                "queued": False,
            }
        except Exception as err:
            logger.exception("REST command_fn failed")
            return {"ok": False, "error": str(err), "request_id": rid}

    if os_core is not None:
        try:
            speech = os_core.try_handle_command(command)
            path = str(getattr(os_core, "_last_brain_path", "") or "fast")
            if speech is not None:
                set_brain_path(path)
                return {
                    "ok": True,
                    "speech": speech,
                    "path": path,
                    "request_id": rid,
                    "queued": False,
                }
            return {
                "ok": False,
                "error": "no fast-path match (DeepBrain/Cursor not wired on this server)",
                "request_id": rid,
                "path": "deep",
            }
        except Exception as err:
            logger.exception("REST try_handle_command failed")
            return {
                "ok": False,
                "error": str(err),
                "request_id": rid,
                "path": "fast",
            }

    return {
        "ok": False,
        "error": "no command handler (core/HUD not wired)",
        "request_id": rid,
        "path": path,
    }


def attach_rest_routes(
    app: web.Application,
    *,
    os_core: Any = None,
    command_fn: Optional[CommandFn] = None,
    health_fn: Optional[HealthFn] = None,
    state_fn: Optional[StateFn] = None,
) -> None:
    """Register /api/health, /api/state, /api/command on an aiohttp app."""

    async def _health(_request: web.Request) -> web.Response:
        payload = health_fn() if health_fn else build_health(os_core)
        return web.json_response(payload)

    async def _state(_request: web.Request) -> web.Response:
        payload = state_fn() if state_fn else build_state(os_core)
        return web.json_response(payload)

    async def _command(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        text = str(body.get("text") or body.get("command") or "").strip()
        if not text:
            qs = request.rel_url.query
            text = str(qs.get("text") or qs.get("command") or "").strip()
        result = dispatch_command(text, os_core=os_core, command_fn=command_fn)
        status = 200 if result.get("ok") else (400 if "empty" in str(result.get("error")) else 503)
        return web.json_response(result, status=status)

    app.router.add_get("/api/health", _health)
    app.router.add_get("/api/state", _state)
    app.router.add_post("/api/command", _command)
    app.router.add_get("/api/command", _command)
