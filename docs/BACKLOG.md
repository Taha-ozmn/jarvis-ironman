# Post-merge backlog (honest)

Phases 0–8+ shipped in **v2.0.0**. Remaining items are product polish, not missing OS scaffolding.

## Fixed in hardening PR
- Cursor boot failure → **degraded mode** (local tools keep working)
- DeepBrain wait capped (~8s) — no multi-minute hang
- Level-3 voice confirm speech respects `jarvis.language` (TR/EN)

## Still open (priority)

| Pri | Item | Notes |
|-----|------|--------|
| P1 | STT `tr-TR` vs TTS `en-GB` mismatch | Config choice; align language or dual replies |
| P1 | PyAudio optional for mic fallback | Document / optional install in `start.sh` |
| P1 | Safer defaults for shell | Consider `full_shell_access: false` preset |
| P2 | MCP Calendar/Notes servers | `jarvis2.mcp.servers: []` by design |
| P2 | Playwright interactive browser | Optional deps |
| P2 | Offline STT | Needs local engine |

## Not gaps
Open-app verify, DecisionEngine gate, HUD confirm, hybrid memory, CI — done.
