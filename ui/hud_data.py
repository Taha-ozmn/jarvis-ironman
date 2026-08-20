"""Command Center snapshot — real data from JarvisOS / SQLite."""

from __future__ import annotations

from typing import Any, Optional


def build_command_center(os_core: Any) -> dict[str, Any]:
    """Build HUD command-center payload from live subsystems."""
    if os_core is None:
        return {"available": False, "reason": "JARVIS 2.0 core not loaded"}

    tasks = []
    try:
        for t in os_core.tasks.list(limit=12):
            tasks.append(
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "priority": t.priority,
                    "due_at": t.due_at,
                }
            )
    except Exception as err:
        tasks = [{"error": str(err)}]

    memories = []
    try:
        for m in os_core.memory.search("", limit=8):
            memories.append(
                {
                    "id": m.id,
                    "key": m.key,
                    "content": m.content[:160],
                    "category": m.category,
                }
            )
    except Exception as err:
        memories = [{"error": str(err)}]

    projects = []
    try:
        reg = getattr(os_core, "projects", None)
        if reg is not None:
            active = reg.active()
            for p in reg.list_projects()[:12]:
                projects.append(
                    {
                        "id": p.id,
                        "key": p.key,
                        "name": p.name,
                        "path": p.path or "",
                        "description": (p.description or "")[:120],
                        "exists": p.exists,
                        "active": bool(active and active.key == p.key),
                    }
                )
        else:
            rows = os_core.db.fetchall(
                "SELECT id, name, path, description FROM projects ORDER BY id DESC LIMIT 8"
            )
            for r in rows:
                projects.append(
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "path": r["path"] or "",
                        "description": (r["description"] or "")[:120],
                    }
                )
    except Exception as err:
        projects = [{"error": str(err)}]

    automations = []
    active_automations = 0
    try:
        for a in os_core.automation.list_rules():
            if a.enabled:
                active_automations += 1
            automations.append(
                {
                    "id": a.id,
                    "name": a.name,
                    "trigger_type": a.trigger_type,
                    "enabled": a.enabled,
                    "last_fired_at": a.last_fired_at,
                    "fail_count": a.fail_count,
                }
            )
    except Exception as err:
        automations = [{"error": str(err)}]

    tools = []
    try:
        for spec in os_core.tools.list_specs():
            tools.append(
                {
                    "name": spec.name,
                    "description": spec.description[:100],
                    "level": int(spec.permission_level),
                }
            )
    except Exception as err:
        tools = [{"error": str(err)}]

    logs = []
    try:
        for e in os_core.audit.recent(limit=15):
            logs.append(
                {
                    "id": e.id,
                    "action": e.action,
                    "level": e.level,
                    "success": e.success,
                    "created_at": e.created_at,
                    "details": e.details[:200],
                }
            )
    except Exception as err:
        logs = [{"error": str(err)}]

    diagnostics: dict[str, Any] = {}
    try:
        health_fn = getattr(os_core, "health_cached", None) or os_core.health
        diagnostics = health_fn() if callable(health_fn) else os_core.health()
    except Exception as err:
        diagnostics = {"ok": False, "error": str(err)}

    pending = []
    try:
        pending = os_core.confirmation.pending_list()
    except Exception:
        pending = []

    current_task = None
    for t in tasks:
        if isinstance(t, dict) and t.get("status") == "in_progress":
            current_task = t
            break
    if current_task is None:
        for t in tasks:
            if isinstance(t, dict) and t.get("status") == "pending":
                current_task = t
                break

    j2 = (getattr(os_core, "config", None) or {}).get("jarvis2", {})
    settings = {
        "max_permission_level": int(
            getattr(getattr(os_core, "permissions", None), "max_level", 2)
        ),
        "full_autonomy": bool(getattr(os_core, "full_autonomy", False)),
        "auto_approve_dangerous": bool(
            getattr(getattr(os_core, "confirmation", None), "auto_approve", False)
        ),
        "automation": bool(getattr(os_core.automation, "enabled", False)),
        "proactive": bool(getattr(os_core, "proactive_enabled", False)),
        "db_path": str(getattr(os_core, "db_path", "")),
        "confirm_timeout": float(j2.get("confirm_timeout", 60)),
    }

    return {
        "available": True,
        "summary": {
            "current_task": current_task,
            "open_tasks": sum(
                1
                for t in tasks
                if isinstance(t, dict)
                and t.get("status") in ("pending", "in_progress")
            ),
            "active_automations": active_automations,
            "pending_confirms": len(pending),
            "diagnostics_ok": bool(diagnostics.get("ok")),
            "tool_count": len([t for t in tools if isinstance(t, dict) and "name" in t]),
        },
        "tasks": tasks,
        "memory": memories,
        "projects": projects,
        "automations": automations,
        "tools": tools,
        "logs": logs,
        "diagnostics": diagnostics,
        "settings": settings,
        "pending_confirmations": pending,
    }
