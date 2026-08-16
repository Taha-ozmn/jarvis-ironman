# JARVIS 2.0 — Production diagnostics

## Health probe

```
GET /api/health
```

| Status | Meaning |
|--------|---------|
| 200 | `ok: true` and not degraded |
| 503 | subsystem failure, soft-init missing, or `degraded: true` |

Payload includes `ready`, `degraded`, `passed`/`total`, and per-check details from `SelfDiagnostics`.

Also: `GET /api/command-center` for the full HUD snapshot.

## Checks (selected)

| Name | Notes |
|------|-------|
| database / memory / tasks | SQLite paths |
| execution | tool retries + plan timeline |
| degraded_mode | sensor; summary.ok false when active |
| browser / vision / mcp | optional engines — honest notes |

## Ops tips

- Prefer `/api/health` for load balancers / uptime monitors.
- Voice Level-3 confirm resolves via HUD (Enter/Esc) or `evet`/`hayır`.
- Safe autonomy: `jarvis2.auto_approve_dangerous: false` (see `docs/SECURITY.md`).
