# Post-merge backlog (honest)

Phases 0–8+ shipped in **v2.0.0**. Remaining items are product polish, not missing OS scaffolding.

## Fixed in hardening PR
- Cursor boot failure → **degraded mode**
- DeepBrain wait capped (~8s)
- Bilingual Level-3 confirm
- **N-01…N-10** autonomy, dry-run, step budget, docs, safe preset, parallel probes, storage seam, PyAudio docs
- **N-11** Local notes/calendar tools + optional MCP pack module
- **N-12** `open_backend()` + `storage.postgres.PostgresDatabase` (optional psycopg)

## Still open (priority)

| Pri | Item | Notes |
|-----|------|--------|
| P1 | Change default STT to match TTS | Safe preset aligned; main config still TR listen / EN speak |
| P1 | Flip default `full_shell_access` to false | Safe preset ready; default left true for compat |
| P2 | Wire live Postgres in CI | Adapter exists; needs DSN + optional dep |
| P2 | Playwright interactive browser | Optional deps |
| P2 | Offline STT | Needs local engine |
| P2 | Apple Calendar/Notes sync | Local store only today |

## Not gaps
Core OS scaffolding, autonomy/dry-run, parallel health, notes/calendar CRUD, storage factory — done.
