# JARVIS 2.0 — Roadmap (complete)

**Kaynak:** `docs/ARCHITECTURE_AUDIT.md`  
**Ölçüt:** Doğrulanmış icra; ham `Could not open` yok; sonsuz retry yok; CHAT/SIMPLE Cursor yok.

---

## All phases — Completed

| Phase | IDs | Status |
|-------|-----|--------|
| 0 Audit | P0-AUDIT | Done |
| 1 Stability | S-01…S-06 | Done |
| 2 Orchestrator | O-01…O-03 | Done |
| 3 Tools/plugins | T-01 | Done |
| 4 Tasks/cancel | K-02, K-03 | Done |
| 5 Memory | M-01 | Done |
| 6 Model/degraded | R-01, P-01 | Done |
| 7 Evidence/verify | V-01…V-04 | Done |
| 8 HUD/automation/health | U-01…U-04, H-01, H-02, A-01 | Done |
| Decision | O-04 (`DecisionEngine`) | Done |
| CI / Playwright opt | V-05 | Done |

---

## Docs

ARCHITECTURE, ARCHITECTURE_AUDIT, AUTOMATION, ERROR_RECOVERY, MEMORY, MODEL_ROUTING, PRODUCTION, SECURITY, TESTING, TOOLS, ROADMAP.

---

## Out of scope (by design)

Full rewrite · forced PostgreSQL · removing voice/HUD/Cursor · inventing a second overlapping router.

```
Branch: cursor/phase1-stability-b2cd
PR: #2 — Phases 0–8+ complete
Tests: unittest discover + GitHub Actions CI
```
