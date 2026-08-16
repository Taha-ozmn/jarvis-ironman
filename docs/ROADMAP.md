# JARVIS 2.0 — Roadmap

**Kaynak:** `docs/ARCHITECTURE_AUDIT.md`  
**Ölçüt:** Doğrulanmış icra; ham `Could not open` yok; sonsuz retry yok.

---

## Completed

| ID | Description |
|----|-------------|
| P0 / S / O / T / K / M / V / R / X / Q | Phases 0–7 core |
| U-01 | Streaming HUD `plan_progress` |
| V-02 | Verify fs/git write·add·push |
| P-01 | Cursor trim fillers / local phrases |
| H-01 | `GET /api/health` |
| A-01 | Automation YAML packs |
| U-02 | HUD PLAN timeline pane |
| V-03 | Verify browser + `dev.run_command` |
| P-02 | Background plan speech throttle |
| O-04a | `core/decision.py` facade (prep; no DecisionEngine rewrite) |

---

## Next

| ID | Description | Priority |
|----|-------------|----------|
| O-04b | Optional DecisionEngine only if Router/complexity diverge further | P2 |
| U-03 | Confirm UX polish / mic pause indicators | P2 |
| V-04 | Verify Playwright fill/click when optional deps present | P3 |

---

## Future

Voice refinements, production dashboards. No full rewrite / forced PostgreSQL / removing voice·HUD·Cursor.

---

## Phase report

```
Phase 8 follow-on: plan_timeline → HUD PLAN tab; browser/dev verify;
throttled background plan speech; decision facade for routing docs.

Tests: unittest discover green.
```
