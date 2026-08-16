# JARVIS 2.0 — Roadmap

**Kaynak:** `docs/ARCHITECTURE_AUDIT.md`

---

## Completed

Phases 0–8+ core OS work, plus:

| ID | Description |
|----|-------------|
| U-03 | Confirm UX — timer, Enter/Esc, AUTH badge / mic indicators |
| V-04 | Verify `browser.fill_form` / `browser.click` when ok |
| H-02 | Health payload: `ready` / `degraded` / execution check; PRODUCTION.md |

---

## Next (optional)

| ID | Description | Priority |
|----|-------------|----------|
| O-04b | DecisionEngine only if Router/complexity diverge | P3 |
| U-04 | Desktop native confirm parity | P3 |
| V-05 | Live Playwright e2e (optional deps CI job) | P3 |

---

## Future

Voice refinements, richer dashboards. No full rewrite / forced PostgreSQL / removing voice·HUD·Cursor.

```
Polish: confirm countdown + keyboard; Playwright verify; production health fields.
Tests: unittest discover green.
```
