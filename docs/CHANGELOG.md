# Changelog

## 2.0.0 — Personal AI OS (Phases 0–8+)

Branch / PR: `cursor/phase1-stability-b2cd` → https://github.com/Taha-ozmn/jarvis-ironman/pull/2

### Highlights
- Stable open-app + recovery speech + bounded tool retries
- `JarvisOS.handle_turn` + `DecisionEngine` Cursor gate (CHAT/SIMPLE/degraded never deep)
- Tools/plugins, plan cancel/resume, hybrid memory, execution evidence
- HUD plan stream + PLAN timeline; Level-3 confirm UX (timer, Enter/Esc, desktop focus)
- Verify: fs/git/browser/dev (+ Playwright fill/click when available)
- `GET /api/health` with ready/degraded/version; automation YAML packs
- GitHub Actions CI (unit + optional Playwright)

### Tests
`python3 -m unittest discover -s tests` — green on CI.

### Security default
`jarvis2.auto_approve_dangerous: false`
