# JARVIS 2.0 — Architecture Audit

**Proje:** `/workspace` (github.com/Taha-ozmn/jarvis-ironman)  
**Tarih:** 2026-08-16  
**Faz:** Phases 0–8+ **COMPLETE** (PR branch `cursor/phase1-stability-b2cd`)

---

## 1. Current Architecture

Hibrit iki katman:

| Katman | Giriş | Rol |
|--------|-------|-----|
| v1 | `main.py` → `JarvisCore` | Voice, HUD, Cursor DeepBrain |
| v2 | `core/app.py` → `JarvisOS` | ToolRegistry, SQLite, ExecutionEngine, DecisionEngine |

**Akış:** Mic/UI → `process_command` → `handle_turn` → tools → meta → legacy → DecisionEngine gate → Cursor.

**Stack:** Python 3.10+, Cursor SDK, edge-tts, aiohttp HUD, SQLite WAL, optional Playwright.

## 2–3. Problems addressed

- Open-app false success → verified + retries + recovery speech
- CHAT/SIMPLE Cursor cost → DecisionEngine gate
- No cancel/evidence → CancellationToken + ExecutionEvidence
- Weak recall → hybrid memory retrieval
- No plan HUD → `plan_progress` + PLAN timeline
- Level-3 UX → countdown, Enter/Esc, desktop focus

## 4. KEEP

voice, HUD, Cursor, ToolRegistry, SQLite, permissions/audit, CommandRouter (NL→tools), DecisionEngine (Cursor policy).

## 5. Production

`GET /api/health` · `docs/PRODUCTION.md` · GitHub Actions CI · safe autonomy (`auto_approve_dangerous: false`).

Detay: `docs/ROADMAP.md`.
