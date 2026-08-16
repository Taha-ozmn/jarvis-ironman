"""Self-diagnostics for JARVIS 2.0 subsystems."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DiagnosticResult:
    name: str
    ok: bool
    detail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


class SelfDiagnostics:
    """Report which new subsystems are healthy."""

    def __init__(self, os_instance: Any) -> None:
        self._os = os_instance

    def run(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        results.append(self._check_event_bus())
        results.append(self._check_database())
        results.append(self._check_memory())
        results.append(self._check_tasks())
        results.append(self._check_permissions())
        results.append(self._check_tools())
        results.append(self._check_audit())
        results.append(self._check_automation())
        results.append(self._check_projects())
        results.append(self._check_backup())
        results.append(self._check_planner())
        results.append(self._check_execution())
        results.append(self._check_degraded())
        results.append(self._check_browser())
        results.append(self._check_vision())
        results.append(self._check_embeddings())
        results.append(self._check_mcp())
        results.append(self._check_language())
        results.append(self._check_autonomy())
        return results

    def summary(self) -> dict[str, Any]:
        items = self.run()
        ok_count = sum(1 for i in items if i.ok)
        degraded = False
        try:
            from core.degraded import get_degraded_mode

            degraded = bool(get_degraded_mode().active)
        except Exception:
            pass
        return {
            "ok": ok_count == len(items) and not degraded,
            "ready": bool(getattr(self._os, "ready", False)),
            "degraded": degraded,
            "passed": ok_count,
            "total": len(items),
            "version": _version_payload(),
            "checks": [
                {"name": i.name, "ok": i.ok, "detail": i.detail, "meta": i.meta}
                for i in items
            ],
        }

    def _check_event_bus(self) -> DiagnosticResult:
        bus = getattr(self._os, "bus", None)
        if bus is None:
            return DiagnosticResult("event_bus", False, "not initialized")
        probe = bus.publish("diagnostics.probe", {"ping": True}, source="diagnostics")
        return DiagnosticResult(
            "event_bus",
            True,
            "publish ok",
            {"event_id": probe.event_id},
        )

    def _check_database(self) -> DiagnosticResult:
        db = getattr(self._os, "db", None)
        if db is None:
            return DiagnosticResult("database", False, "not initialized")
        try:
            row = db.fetchone("SELECT 1 AS ok")
            ok = row is not None and int(row["ok"]) == 1
            return DiagnosticResult("database", ok, str(db.path))
        except Exception as err:
            return DiagnosticResult("database", False, str(err))

    def _check_memory(self) -> DiagnosticResult:
        repo = getattr(self._os, "memory", None)
        if repo is None:
            return DiagnosticResult("memory", False, "not initialized")
        try:
            count = len(repo.search("", limit=1))
            return DiagnosticResult("memory", True, f"search ok (sample={count})")
        except Exception as err:
            return DiagnosticResult("memory", False, str(err))

    def _check_tasks(self) -> DiagnosticResult:
        tasks = getattr(self._os, "tasks", None)
        if tasks is None:
            return DiagnosticResult("tasks", False, "not initialized")
        try:
            items = tasks.list(limit=1)
            return DiagnosticResult("tasks", True, f"list ok (n={len(items)})")
        except Exception as err:
            return DiagnosticResult("tasks", False, str(err))

    def _check_permissions(self) -> DiagnosticResult:
        gate = getattr(self._os, "permissions", None)
        if gate is None:
            return DiagnosticResult("permissions", False, "not initialized")
        return DiagnosticResult(
            "permissions",
            True,
            f"max_level={gate.max_level.value}",
        )

    def _check_tools(self) -> DiagnosticResult:
        registry = getattr(self._os, "tools", None)
        if registry is None:
            return DiagnosticResult("tools", False, "not initialized")
        names = registry.list_names()
        return DiagnosticResult("tools", True, f"registered={len(names)}", {"tools": names})

    def _check_audit(self) -> DiagnosticResult:
        audit = getattr(self._os, "audit", None)
        if audit is None:
            return DiagnosticResult("audit", False, "not initialized")
        try:
            recent = audit.recent(limit=1)
            return DiagnosticResult("audit", True, f"recent={len(recent)}")
        except Exception as err:
            return DiagnosticResult("audit", False, str(err))

    def _check_automation(self) -> DiagnosticResult:
        engine = getattr(self._os, "automation", None)
        if engine is None:
            return DiagnosticResult("automation", False, "not initialized")
        return DiagnosticResult(
            "automation",
            True,
            f"enabled={engine.enabled} rules={engine.rule_count()}",
        )

    def _check_projects(self) -> DiagnosticResult:
        reg = getattr(self._os, "projects", None)
        if reg is None:
            return DiagnosticResult("projects", False, "not initialized")
        items = reg.list_projects()
        available = sum(1 for p in items if p.exists)
        active = reg.active()
        return DiagnosticResult(
            "projects",
            True,
            f"total={len(items)} available={available} active={active.key if active else None}",
            {
                "browser": "urllib+open (no Playwright)",
                "active": active.key if active else None,
            },
        )

    def _check_backup(self) -> DiagnosticResult:
        svc = getattr(self._os, "backup", None)
        if svc is None:
            return DiagnosticResult("backup", False, "not initialized")
        path = getattr(svc, "backup_dir", None)
        exists = bool(path and path.exists()) if path else False
        return DiagnosticResult(
            "backup",
            True,
            f"dir={path} exists={exists} retention={getattr(svc, 'retention', '?')}",
        )

    def _check_planner(self) -> DiagnosticResult:
        planner = getattr(self._os, "planner", None)
        if planner is None:
            return DiagnosticResult("planner", False, "not initialized")
        llm = getattr(self._os, "llm", None)
        llm_ok = bool(llm and getattr(llm, "available", lambda: False)())
        return DiagnosticResult(
            "planner",
            True,
            f"heuristic=ok llm_refine={'available' if llm_ok else 'offline-fallback'}",
            {"llm": llm_ok},
        )

    def _check_execution(self) -> DiagnosticResult:
        eng = getattr(self._os, "execution", None)
        if eng is None:
            return DiagnosticResult("execution", False, "not initialized")
        timeline = getattr(eng, "plan_timeline", None) or []
        return DiagnosticResult(
            "execution",
            True,
            f"tool_retries={getattr(eng, 'tool_max_retries', '?')} timeline={len(timeline)}",
            {"plan_progress": getattr(eng, "last_plan_progress", None)},
        )

    def _check_degraded(self) -> DiagnosticResult:
        try:
            from core.degraded import get_degraded_mode

            snap = get_degraded_mode().snapshot()
            return DiagnosticResult(
                "degraded_mode",
                True,
                "active" if snap.active else "nominal",
                {
                    "active": snap.active,
                    "reason": snap.reason,
                    "cursor_available": snap.cursor_available,
                },
            )
        except Exception as err:
            return DiagnosticResult("degraded_mode", False, str(err))

    def _check_browser(self) -> DiagnosticResult:
        try:
            from tools.browser_tools import browser_diagnostics

            info = browser_diagnostics()
            return DiagnosticResult(
                "browser",
                True,
                f"engine={info.get('engine')} playwright={info.get('playwright')}",
                info,
            )
        except Exception as err:
            return DiagnosticResult("browser", False, str(err))

    def _check_vision(self) -> DiagnosticResult:
        try:
            from tools.vision import vision_status

            info = vision_status()
            return DiagnosticResult(
                "vision",
                True,
                f"ocr={info.get('ocr')} fallback={info.get('fallback')}",
                info,
            )
        except Exception as err:
            return DiagnosticResult("vision", False, str(err))

    def _check_embeddings(self) -> DiagnosticResult:
        try:
            from memory.embeddings import embedding_status

            info = embedding_status()
            return DiagnosticResult(
                "embeddings",
                True,
                f"engine={info.get('engine')} dim={info.get('dim')}",
                info,
            )
        except Exception as err:
            return DiagnosticResult("embeddings", False, str(err))

    def _check_mcp(self) -> DiagnosticResult:
        mcp = getattr(self._os, "mcp", None)
        if mcp is None:
            return DiagnosticResult("mcp", True, "adapter not loaded (optional)")
        status = mcp.status()
        connected = int(status.get("connected") or 0)
        servers = status.get("servers") or []
        if connected == 0 and (
            not servers
            or all(
                (s.get("error") or "").startswith("no MCP")
                or s.get("name") == "_none"
                for s in servers
            )
        ):
            return DiagnosticResult(
                "mcp",
                True,
                "no MCP servers configured",
                status,
            )
        detail = f"runtime={status.get('runtime')} connected={connected}/{status.get('configured')}"
        return DiagnosticResult("mcp", True, detail, status)

    def _check_language(self) -> DiagnosticResult:
        try:
            from core.language import check_language_alignment

            cfg = getattr(self._os, "config", None) or {}
            info = check_language_alignment(cfg)
            detail = f"speak={info.speak} listen={info.listen}"
            if not info.aligned:
                detail = f"WARNING: {info.warning}"
            return DiagnosticResult(
                "language",
                True,
                detail,
                {
                    "speak": info.speak,
                    "listen": info.listen,
                    "aligned": info.aligned,
                },
            )
        except Exception as err:
            return DiagnosticResult("language", False, str(err))

    def _check_autonomy(self) -> DiagnosticResult:
        policy = getattr(self._os, "autonomy", None)
        if policy is None:
            return DiagnosticResult("autonomy", False, "not initialized")
        steps = getattr(self._os, "max_agent_steps", None)
        return DiagnosticResult(
            "autonomy",
            True,
            f"level={policy.level} ({policy.label}) confirm>={policy.confirm_at_or_above} max_steps={steps}",
            {
                "level": policy.level,
                "label": policy.label,
                "confirm_at_or_above": policy.confirm_at_or_above,
                "max_agent_steps": steps,
            },
        )


def _version_payload() -> dict[str, str]:
    try:
        from core.version import version_info

        return version_info()
    except Exception:
        return {"version": "unknown"}
