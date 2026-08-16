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

1. Install deps + optional Playwright if needed  
2. Ensure Cursor auth for DeepBrain  
3. Start HUD (`./start.sh`)  
4. Monitor `/api/health` and audit log in SQLite  

SQLite is the supported store. PostgreSQL is Future (Phase 14 stretch).
