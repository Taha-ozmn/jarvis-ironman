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

---

## In Progress / This PR

| ID | Description | Priority | Status | Acceptance Criteria |
|----|-------------|----------|--------|---------------------|
| P0-AUDIT | Architecture audit + roadmap docs | P0 | Completed | Docs present |
| S-01 | OpenApp resolve + retry + Applications fallback | P0 | Completed | `open -a` returncode; no false success |
| S-02 | User-safe recovery speech (no raw Could not open) | P0 | Completed | TTS/tool errors rewritten |
| S-03 | Single-tool retry max 3 + exponential backoff | P0 | Completed | `tool_max_retries`; classify errors |
| S-04 | Workspace `.` → repo root if stale | P0 | Completed | `ensure_jarvis2_defaults` |
| S-05 | Open/STT regression tests (açık, açsana, krom) | P0 | Completed | `tests/test_phase1_stability.py` |
| S-06 | Action miss → legacy local before Cursor | P0 | Completed | `ai_only` + looks_like_action |

---

## Next

| ID | Description | Priority | Dependencies |
|----|-------------|----------|--------------|
| O-01 | JarvisOS `handle_turn` single entry; thin main.py | P0 | Phase 1 |
| O-02 | Complexity gate: CHAT/SIMPLE never Cursor | P0 | O-01 |
| K-02 | Task checkpoint resume | P0 | O-01 |
| K-03 | CancellationToken for plans | P0 | K-02 |
| V-01 | Evidence object on every tool call | P0 | S-03 |
| X-01 | Document safe autonomy preset | P1 | — |

---

## Future

Phases 2–14 per master spec: orchestrator, tools/plugins, task engine, memory retrieval, model fallback, streaming HUD, voice layer, automation YAML, security, chaos tests, performance, production diagnostics.

**Yapılmayacak:** Full rewrite, PostgreSQL zorunluluğu, voice/HUD/Cursor kaldırma.

---

## Phase report (Phase 1)

```
WHAT CHANGED
  OpenApp verify+retry+fallback; recovery speech; tool retries;
  workspace guard; action→legacy path; audit/roadmap docs; tests.

WHY
  Eliminate false "opened" claims and raw "Could not open" UX;
  stop action intents falling blindly into Cursor chat.

TEST RESULT
  See CI / unittest discover (test_phase1_stability + existing suite).

NEXT
  Phase 2 orchestrator thinning + complexity gate.
```
