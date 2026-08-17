# JARVIS 2.0 — Roadmap (14 master phases)

**Source:** Master Engineering Spec §77–80 + live audit.  
**Release:** v2.1.0 (`PHASE = 0-14-complete`)

Statuses: `Completed` | `Partial` | `Next` | `Future`

---

## Completed

| ID | Phase | Description |
|----|------:|-------------|
| P0 | 0 | Architecture audit |
| P1 | 1 | Stability (open, recovery, retries) |
| P2 | 2 | Orchestrator (`handle_turn` + DecisionEngine) |
| P3 | 3 | Tools / plugins / validate |
| P4 | 4 | Task engine / cancel / pause / resume |
| P5 | 5 | Hybrid memory retrieval |
| P6 | 6 | Model router + degraded |
| P7 | 7 | Evidence + verify |
| P8 | 8 | HUD stream + PLAN timeline |
| P9 | 9 | Voice dual-locale (TR STT / EN TTS) |
| P10 | 10 | Automation engine + YAML packs |
| P11 | 11 | Security: autonomy 1–4, shell default off, audit |
| P12 | 12 | Unit/chaos + GitHub CI + §81 acceptance |
| P13 | 13 | Parallel project health probes |
| P14 | 14 | Health, storage seam, Postgres adapter, 2.1.0 |

---

## Acceptance §81

All ten phrases classify + `handle_turn` without Cursor (see `tests/test_acceptance_spec.py`).

---

## Optional extras (not phase blockers)

| Item | Notes |
|------|--------|
| Live Postgres CI | Adapter exists; needs DSN |
| Offline STT engine | Dual-locale Web Speech / native path is the shipped voice |
| Apple Calendar/Notes sync | Local `notes.*` / `calendar.*` store shipped |
| Playwright interactive | Optional extras |

---

## Phase report

```
WHAT CHANGED
  2.1.0: intent/session tools, dual-locale voice, safer shell default,
  parallel project.health, §81 acceptance suite.

WHY
  Close remaining Partial phases 9/11/13/14 without rewrite.

TEST RESULT
  unittest discover + test_acceptance_spec.

NEXT
  Merge PR #3 when ready.
```
