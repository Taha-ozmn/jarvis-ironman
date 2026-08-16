# JARVIS 2.0 — Roadmap (14 master phases)

**Source:** Master Engineering Spec §77–80 + live audit.

Statuses: `Completed` | `Partial` | `Next` | `Future`

---

## Completed

| ID | Phase | Description |
|----|------:|-------------|
| P0 | 0 | Architecture audit |
| P1 | 1 | Stability (open, recovery, retries) |
| P2 | 2 | Orchestrator (`handle_turn` + DecisionEngine) |
| P3 | 3 | Tools / plugins / validate |
| P4 | 4 | Task engine / cancel / resume |
| P5 | 5 | Hybrid memory retrieval |
| P6 | 6 | Model router + degraded |
| P7 | 7 | Evidence + verify |
| P8 | 8 | HUD stream + PLAN timeline |
| P10 | 10 | Automation engine + YAML packs |
| P12 | 12 | Unit/chaos + GitHub CI |

---

## Partial (in progress)

| ID | Phase | Gap | Acceptance |
|----|------:|-----|------------|
| P9 | 9 Voice | STT/TTS language align; PyAudio optional | Same language path or explicit dual |
| P11 | 11 Security | Shell defaults still open; autonomy levels | Config presets + levels 1–4 |
| P13 | 13 Perf | Limited parallel tool fan-out | Independent probes parallel |
| P14 | 14 Prod | No DB abstraction / Postgres | SQLite OK; abstract later |
| H1 | — | Brain soft-fail hang | Degraded + short wait (hardening PR) |

---

## Next (this iteration)

| ID | Description | Priority | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------------|---------------------|
| N-01 | Autonomy levels 1–4 in config | P0 | P11 | ✅ `jarvis2.autonomy_level` gates confirms |
| N-02 | Plan dry-run | P0 | P4 | ✅ `dry run` / TR phrases → zero side effects |
| N-03 | max_agent_steps budget | P0 | P4 | ✅ Plans truncated at budget |
| N-04 | AGENT_DESIGN / DEVELOPMENT / DEPLOYMENT docs | P1 | P0 | ✅ Files present |
| N-05 | Voice language helper | P1 | P9 | ✅ Diagnostic warns on STT/TTS mismatch |

## Still next (Phase 9 / 11 / 13 / 14 deepen)

| ID | Description | Priority | Acceptance |
|----|-------------|----------|------------|
| N-06 | Align default listen/speak language | P1 | ✅ Diagnostic + safe preset aligned; default still dual-locale |
| N-07 | Safer shell preset | P1 | ✅ `config/presets/safe.yaml` (`full_shell_access: false`) |
| N-08 | Parallel independent probes | P2 | ✅ Diagnostics via `run_parallel` |
| N-09 | Storage abstraction seam | P2 | ✅ `storage.StorageBackend` + sqlite factory |
| N-10 | Optional PyAudio mic path docs | P1 | ✅ DEVELOPMENT + `start.sh` hint |

## Future polish

| ID | Description | Priority |
|----|-------------|----------|
| N-11 | MCP Calendar/Notes pack | P2 |
| N-12 | Postgres adapter (implements StorageBackend) | P2 |

---

## Phase report

```
WHAT CHANGED
  N-01…N-10 on hardening branch: autonomy, dry-run, step budget, safe preset,
  parallel diagnostics, storage seam, PyAudio docs.

WHY
  Complete Next control surfaces for phases 9/11/13/14 without rewrite.

TEST RESULT
  237 unittest OK (2 skipped optional e2e).

NEXT
  N-11 MCP packs / N-12 Postgres when needed; merge PR #3 when ready.
```
