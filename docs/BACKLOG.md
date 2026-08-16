# Post-merge backlog (honest)

Phases 0–8+ shipped in **v2.0.0**. Remaining items are product polish, not missing OS scaffolding.

## Fixed in hardening PR
- Cursor boot failure → **degraded mode** (local tools keep working)
- DeepBrain wait capped (~8s) — no multi-minute hang
- Level-3 voice confirm speech respects `jarvis.language` (TR/EN)
- **N-01** `jarvis2.autonomy_level` 1–4
- **N-02** Plan dry-run
- **N-03** `jarvis2.max_agent_steps`
- **N-04** AGENT_DESIGN / DEVELOPMENT / DEPLOYMENT docs
- **N-05** Language alignment diagnostic
- **N-06/N-07** Safe preset (`config/presets/safe.yaml`) + language notes
- **N-08** Parallel diagnostic probes (`core/parallel.py`)
- **N-09** `storage.StorageBackend` seam (SQLite factory; Postgres later)

## Still open (priority)

| Pri | Item | Notes |
|-----|------|--------|
| P1 | Change default STT to match TTS | Opt-in via safe preset; main config still TR listen / EN speak |
| P1 | PyAudio optional for mic fallback | Document / optional install in `start.sh` |
| P1 | Flip default `full_shell_access` to false | Safe preset ready; default left true for compat |
| P2 | MCP Calendar/Notes servers | `jarvis2.mcp.servers: []` by design |
| P2 | Playwright interactive browser | Optional deps |
| P2 | Offline STT | Needs local engine |
| P2 | Postgres `StorageBackend` impl | Protocol + factory ready |

## Not gaps
Open-app verify, DecisionEngine, HUD confirm, hybrid memory, CI, autonomy/dry-run/steps, parallel health, storage seam — done.
