# JARVIS 2.0 — Roadmap

**Kaynak:** `docs/ARCHITECTURE_AUDIT.md`  
**Ölçüt:** Doğrulanmış icra; ham `Could not open` yok; sonsuz retry yok.

Durum: `Completed` | `In Progress` | `Next` | `Future`

---

## Completed

| ID | Description |
|----|-------------|
| C-01…C-05 | Soft-init OS, permissions, router, automation, HUD |
| P0-AUDIT | Architecture audit + roadmap docs |
| S-01…S-06 | Phase 1 stability |
| O-01…O-03 | Phase 2 orchestrator |
| T-01 | Tool validate/rollback + plugins |
| K-02/K-03 | Task states + plan cancel/resume |
| M-01 | Hybrid memory retrieval |
| V-01 | ExecutionEvidence |
| R-01 | Degraded mode + model routing |
| X-01 | Security / tools / memory docs |
| Q-01 | Chaos/recovery tests |
| U-01 | Streaming HUD plan progress (WS `plan_progress`) |
| V-02 | Verify `fs.write`/`fs.create`/`git.add`/`git.push` |
| P-01 | Cursor trim — fillers + local phrases as CHAT/SIMPLE |
| H-01 | `GET /api/health` production probe |
| A-01 | Automation YAML packs loader |

---

## Next

| ID | Description | Priority | Dependencies |
|----|-------------|----------|--------------|
| O-04 | DecisionEngine (when introduced) — avoid Router duplication | P1 | — |
| V-03 | Broader verify for browser/dev tools | P2 | V-02 |
| U-02 | HUD plan timeline pane (history of steps) | P2 | U-01 |
| P-02 | Background plan speech throttle | P2 | U-01 |

---

## Future

Voice layer refinements, production dashboards, DecisionEngine consolidation. Incremental only.

**Yapılmayacak:** Full rewrite, PostgreSQL zorunluluğu, voice/HUD/Cursor kaldırma.

---

## Phase report (Phase 1–8+)

```
WHAT CHANGED
  Phase 1–7: stability, orchestrator, tools, memory, evidence, degraded.
  Phase 8+: plan_progress → HUD WS; fs/git verify; Cursor filler trim;
  /api/health; automation YAML packs.

TEST RESULT
  unittest discover — full suite green.

NEXT
  DecisionEngine (if added); HUD plan timeline; more verify coverage.
```
