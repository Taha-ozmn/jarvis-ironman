# JARVIS 2.0 — Roadmap

**Kaynak:** `docs/ARCHITECTURE_AUDIT.md`  
**Ölçüt:** Doğrulanmış icra; ham `Could not open` yok; sonsuz retry yok.

Durum: `Completed` | `In Progress` | `Next` | `Future`

---

## Completed

| ID | Description |
|----|-------------|
| C-01 | Soft-init JarvisOS + ToolRegistry + SQLite |
| C-02 | Permission 0–3, ConfirmationGate, AuditLog |
| C-03 | CommandRouter + ExecutionEngine + Planner |
| C-04 | Automation / projects / git / dev tools |
| C-05 | HUD command center + REST-ish diagnostics |
| P0-AUDIT | Architecture audit + roadmap docs |
| S-01…S-06 | Phase 1 stability (open, recovery, retries, workspace, legacy) |
| O-01…O-03 | Phase 2 orchestrator (`handle_turn`, Cursor gate, request_id) |
| T-01 | Tool validate/rollback hooks + plugin loader |
| K-02/K-03 | Task states + plan cancel/resume |
| M-01 | Hybrid memory retrieval + temporal phrases |
| V-01 | ExecutionEvidence on tool calls |
| R-01 | Degraded mode + cheap/smart model routing |
| X-01 | Security / tools / memory / recovery docs |
| Q-01 | Chaos/recovery unit tests |

---

## In Progress / This PR

| ID | Description | Priority | Status | Acceptance Criteria |
|----|-------------|----------|--------|---------------------|
| P3-7 | Tools, tasks, memory, evidence, routing | P0 | Completed | Tests green; docs present |

---

## Next

| ID | Description | Priority | Dependencies |
|----|-------------|----------|--------------|
| O-04 | Reduce DecisionEngine/Router overlap (when DecisionEngine lands) | P1 | O-01 |
| U-01 | Streaming HUD progress for long plans | P1 | K-03 |
| V-02 | Broader verify coverage for fs/git tools | P1 | V-01 |
| P-01 | Perf: trim Cursor path for SIMPLE misses | P2 | O-02 |

---

## Future

Phases 8–14 polish: streaming HUD, voice layer refinements, automation YAML packs, production diagnostics dashboards. Incremental only.

**Yapılmayacak:** Full rewrite, PostgreSQL zorunluluğu, voice/HUD/Cursor kaldırma.

---

## Phase report (Phase 1–7)

```
WHAT CHANGED
  Phase 1–2: open verify+retry; recovery speech; handle_turn; Cursor gate.
  Phase 3–4: tool validate/rollback; plugins; task state machine; cancel.
  Phase 5–7: hybrid memory; ExecutionEvidence; degraded + model routing.
  Docs: TOOLS, SECURITY, ERROR_RECOVERY, MEMORY, MODEL_ROUTING, TESTING, ARCHITECTURE.

WHY
  False success / raw errors; trivial Cursor cost; no cancel/evidence; weak recall.

TEST RESULT
  unittest discover — phase1–7 + existing suite.

NEXT
  Streaming HUD; broader verify; DecisionEngine consolidation.
```
