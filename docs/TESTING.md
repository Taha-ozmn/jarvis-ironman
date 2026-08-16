# JARVIS 2.0 — Testing

```bash
python3 -m unittest discover -s tests -v
```

| Suite | Focus |
|-------|--------|
| `test_phase1_stability` | open resolve, recovery speech, retries |
| `test_phase2_orchestrator` | `handle_turn`, CHAT/SIMPLE gate |
| `test_phase3_to_7_os` | plugins, cancel, evidence, hybrid memory, degraded, chaos |
| `test_phase3_tools` | router + real tools |
| `test_phase4_automation` | scheduler |
| `test_phase7_planner` | plans |

## Chaos expectations

Unknown tools, tool crashes, and cancel mid-plan must not raise into the voice loop. Prefer failing with user-safe speech.
