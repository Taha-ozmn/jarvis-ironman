# JARVIS 2.0 — Architecture Audit

**Proje:** `/workspace` (github.com/Taha-ozmn/jarvis-ironman)  
**Tarih:** 2026-08-16  
**Faz:** Phase 0 Audit + Phase 1 Stability (bu PR)

---

## 1. Current Architecture

Hibrit iki katman:

| Katman | Giriş | Rol |
|--------|-------|-----|
| v1 | `main.py` → `JarvisCore` | Voice, HUD, Cursor DeepBrain |
| v2 | `core/app.py` → `JarvisOS` | ToolRegistry, SQLite, ExecutionEngine, Automation |

**Akış:** Mic/UI → `process_command` → JarvisOS tools → (miss) legacy macOS → Cursor.

**Stack:** Python 3.10+, Cursor SDK, edge-tts, aiohttp HUD, SQLite WAL.

## 2. Architecture Problems

- Orkestratör bölünmüş (`JarvisCore` + `JarvisOS`); tek `JarvisOrchestrator` yok
- Intent çoğunlukla keyword (`CommandRouter`)
- `ai_only: true` iken action miss → Cursor sohbet (Phase 1’de legacy action path eklendi)
- Workspace config stale absolute path olabiliyordu (Phase 1: `.` → repo root)
- `_open_app` eskiden `Popen` ile **her zaman başarı** iddia ediyordu (kritik)

## 3. "Could not open" Root Cause

1. `open -a` tek deneme, returncode kontrolü yoktu (Popen)
2. STT/Türkçe hedef çıkarımı (`açık` → `ık` riski)
3. Alias/Applications fallback yoktu
4. Ham `Could not open {name}` kullanıcıya yansıyordu
5. Tekil tool retry yoktu

## 4–6. Stability / Security / Performance

- Tek worker lock; plan retry vardı, tool retry yoktu → **Phase 1 tool retry**
- `auto_approve_dangerous: false` (bu repo); shell `full_shell_access: true`
- Fast miss → Cursor maliyeti yüksek; action intents artık önce local

## 7–9. AI / Tools / Memory

- Tek provider: Cursor; model router keyword
- Tools: registry + permission 0–3 + audit
- Memory: SQLite + FTS + hashing embeddings

## 10. Proposed Direction

Incremental: Stability → Orchestrator → Tools → Tasks → Memory → Model Router → Verify → UI → Voice → Automation → Security → Tests → Perf → Production.

## 11. KEEP / REFACTOR / REPLACE / REMOVE

| KEEP | REFACTOR | REPLACE (behavior) |
|------|----------|-------------------|
| voice, HUD, Cursor | main.py / router | Popen success claim |
| ToolRegistry, SQLite | open_app pipeline | raw "Could not open" speech |
| permissions/audit | task state machine | stale workspace |

## 12–15. Migration / Testing / Production / Roadmap

Detay: `docs/ROADMAP.md`. Phase 1 kabul: open resolve+retry, recovery speech, workspace guard, action miss → legacy, unittest yeşil.
