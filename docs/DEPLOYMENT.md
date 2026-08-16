# JARVIS 2.0 — Deployment

## Target

Personal Mac workstation (voice + `open` + HUD). Linux CI runs unit tests only.

## Health

```
GET /api/health → 200|503
```

Includes `ready`, `degraded`, `version`.

## Config

- Secrets: environment / `.env` only
- Safe preset: `docs/SECURITY.md`
- Automation packs: `config/automation_packs/`

## Ops

1. Install deps + optional Playwright / psycopg if needed  
2. Ensure Cursor auth for DeepBrain  
3. Start HUD (`./start.sh`)  
4. Monitor `/api/health` and audit log in SQLite  

**Storage:** SQLite is the default (`jarvis2.db_path`). Postgres:

```yaml
jarvis2:
  storage:
    backend: postgres
    dsn: postgresql://user:pass@localhost:5432/jarvis
```

Requires `pip install -r requirements-optional.txt` (psycopg). Prefer SQLite until migrations are fully Postgres-native.

**Notes/Calendar:** built-in tools (`notes.*`, `calendar.*`). Optional MCP pack:

```yaml
jarvis2:
  mcp:
    servers:
      - name: calendar_notes
        transport: stdio
        command: python3
        args: ["-m", "integrations.local_calendar_notes_mcp"]
```
