# Post-merge backlog (honest)

Phases 0–8+ shipped in **v2.0.0**. Remaining items are product polish, not missing OS scaffolding.

## Fixed in hardening PR
- Cursor boot failure → **degraded mode** (local tools keep working)
- DeepBrain wait capped (~8s) — no multi-minute hang
- Level-3 voice confirm speech respects `jarvis.language` (TR/EN)
- **N-01** `jarvis2.autonomy_level` 1–4 (confirm thresholds)
- **N-02** Plan dry-run (`dry run` / `ne yapacağını göster` → zero tool side effects)
- **N-03** `jarvis2.max_agent_steps` plan truncation
- **N-04** AGENT_DESIGN / DEVELOPMENT / DEPLOYMENT docs
- **N-05** Language alignment diagnostic (STT vs TTS warning)

## Still open (priority)

| Pri | Item | Notes |
|-----|------|--------|
| P1 | Align STT/TTS languages in config | Diagnostic warns; default still `listen=tr` / `speak=en` |
| P1 | PyAudio optional for mic fallback | Document / optional install in `start.sh` |
| P1 | Safer defaults for shell | Consider `full_shell_access: false` preset |
| P2 | MCP Calendar/Notes servers | `jarvis2.mcp.servers: []` by design |
| P2 | Playwright interactive browser | Optional deps |
| P2 | Offline STT | Needs local engine |
| P2 | Parallel tool fan-out (Phase 13) | Independent probes |
| P2 | DB abstraction / Postgres (Phase 14) | SQLite OK for now |

## Not gaps
Open-app verify, DecisionEngine gate, HUD confirm, hybrid memory, CI, autonomy/dry-run/step budget — done.
