# JARVIS 2.0 — Testing

```bash
python3 -m unittest discover -s tests -v
```

CI: `.github/workflows/ci.yml` (unit required; Playwright optional job).

| Suite | Focus |
|-------|--------|
| `test_phase1_stability` | open resolve, recovery, retries |
| `test_phase2_orchestrator` | handle_turn, CHAT/SIMPLE gate |
| `test_phase3_to_7_os` | plugins, cancel, evidence, memory, degraded |
| `test_phase8_plus` / `followon` / `phase9_polish` | HUD, verify, confirm, health |
| `test_phase_complete` | DecisionEngine wire + desktop confirm bridge |
| `test_playwright_optional_e2e` | opt-in `PLAYWRIGHT_E2E=1` |

Chaos: unknown tools / crashes / cancel must not raise into the voice loop.
