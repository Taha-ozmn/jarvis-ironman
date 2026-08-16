# JARVIS 2.0 — Mimari Analiz ve Migrasyon Planı

**Proje:** jarvis-ironman → JARVIS 2.0 Personal AI OS  
**Kullanıcı:** Taha Emre Özmen  
**Tarih:** 2026-08-13  
**İlke:** Mevcut çalışan özellikleri koru; incremental refactor; offline-first

---

# Genel Amaç

Cursor SDK tabanlı sesli Iron Man asistanını, **kalıcı bellek**, **görev yönetimi**, **izin seviyeleri**, **araç kayıt sistemi** ve **olay tabanlı çekirdek** içeren kişisel bir AI işletim sistemine dönüştürmek. Mevcut wake word, voice I/O, HUD, macOS kontrolü, model routing ve startup yolu korunur.

---

# Kullanılan Teknolojiler

| Katman | Teknoloji |
|--------|-----------|
| Runtime | Python 3.10+ |
| Beyin | Cursor SDK (`cursor-sdk`) |
| TTS | edge-tts + macOS `say` / afplay |
| STT | Swift native mic + SpeechRecognition / Google STT |
| HUD | aiohttp WebSocket + HTML (Iron Man UI) / pywebview desktop |
| Sistem | subprocess, osascript, webbrowser |
| Config | YAML + dotenv |
| **Yeni (2.0)** | stdlib `sqlite3`, typed event bus, tool registry |

Yeni ağır bağımlılık eklenmedi (stdlib + mevcut deps).

---

# Mimari Yapı

## Mevcut (v1) — monolith orchestrator

```
main.py (JarvisCore)
  ├── voice/     listener, speaker, narrator
  ├── brain/     cursor_brain, model_router, conversation, task_router
  ├── system/    macos, listen_control, hud_stats
  ├── ui/        server (WS), index.html, desktop
  └── config.yaml
```

`JarvisCore` ses, beyin, sistem ve UI'ı tek sınıfta orkestre eder. Bellek yalnızca RAM'de (`ConversationMemory`). Kalıcı DB yok. İzin modeli yok (`full_shell_access` boolean). Araçlar Cursor agent + keyword heuristic'ler.

## Hedef (v2) — layered Personal AI OS

```
main.py (mevcut yol + soft-init)
  └── core.app.JarvisOS (opsiyonel sarmalayıcı)
        ├── EventBus
        ├── ContextManager
        ├── TaskManager
        ├── ExecutionEngine
        ├── ToolRegistry + PermissionGate
        ├── MemoryRepository (SQLite)
        ├── AuditLog
        └── AutomationEngine (skeleton)
  ├── brain/ voice/ system/ ui/  (KORUNUR)
  ├── memory/ security/ tools/ automation/
  └── data/jarvis.db
```

---

# Klasör Yapısı

```
jarvis-ironman/
├── main.py                 # KORU — soft-init v2 core
├── config.yaml             # KORU — jarvis2: feature flags ekle
├── brain/                  # KORU
├── voice/                  # KORU
├── system/                 # KORU
├── ui/                     # KORU
├── workspace/              # KORU
├── core/                   # YENİ — event bus, tasks, execution, context
├── security/               # YENİ — permissions 0-3, confirmation, audit
├── tools/                  # YENİ — registry + base + package hooks
├── memory/                 # YENİ — SQLite, repository, migrations
├── automation/             # YENİ — engine skeleton
├── config/                 # YENİ — loader (backward compat)
├── data/                   # YENİ — jarvis.db, audit (gitignore)
├── docs/                   # YENİ — bu doküman
└── tests/                  # YENİ — unit tests
```

---

# Veri Akışı

### v1 (mevcut)
```
Mic/UI → JarvisCore.process_command
  → local heuristics (system/macos) OR brain.think
  → speaker + HUD broadcast
```

### v2 (hedef, aşamalı)
```
Mic/UI → EventBus(CommandReceived)
  → ContextManager (session + memory recall)
  → PermissionGate → ToolRegistry / ExecutionEngine
  → TaskManager (persist) + AuditLog
  → brain (Cursor) fallback when no local tool
  → EventBus(ResponseReady) → speaker + HUD
```

---

# API Akışı

HUD WebSocket (`/ws`): `config`, `telemetry`, `mic_state`, `command`, status broadcast.  
Değişiklik yok (Phase 2). İleride command center event'leri eklenecek.

---

# Authentication

Cursor API key (`CURSOR_API_KEY` / `.env`). Yerel OS için ayrı auth yok.  
v2: audit log kullanıcı eylemlerini kaydeder; harici auth eklenmez (kişisel cihaz).

---

# Authorization

**v1:** `full_access` / `full_shell_access` / `sandbox` bayrakları.  
**v2 Permission Levels:**

| Level | Ad | Örnek |
|-------|----|--------|
| 0 | READ | bellek oku, saat, durum |
| 1 | LOCAL | app aç, TTS, bellek yaz |
| 2 | SYSTEM | shell, dosya yaz, otomasyon |
| 3 | DANGEROUS | sudo-benzeri, kalıcı sistem değişikliği — onay gerekir |

---

# Veritabanı

SQLite (`data/jarvis.db`), offline-first:

- `memories` — kalıcı notlar / tercihler
- `tasks` — görev CRUD
- `automations` — zamanlanmış kurallar (skeleton)
- `events` — event bus kalıcı iz (opsiyonel)
- `audit_logs` — güvenlik denetimi
- `projects` — proje bağlamı
- `schema_migrations` — sürüm takibi

---

# Güçlü Yönler

- Çalışan sesli pipeline (wake word, native mic, TTS)
- Cursor agent ile gerçek macOS eylem kapasitesi
- Iron Man HUD + telemetry
- Model routing + complexity timeout
- TR/EN dil desteği
- Hızlı local heuristics (saat, app, media)

---

# Zayıf Yönler

- Monolitik `JarvisCore` (~900 satır)
- Kalıcı bellek yok (sadece deque)
- İzin / audit yok — shell tam açık
- Araçlar tip güvenli registry'de değil
- Test altyapısı yoktu
- `ai_only: true` local quick-path'i fiilen kapatıyor
- Config tek dosya, şema doğrulama yok

---

# Güvenlik Riskleri

1. **Kritik:** `full_shell_access: true` + sandbox off → sınırsız shell
2. **Yüksek:** Audit trail yok
3. **Yüksek:** Onay kapısı yok (Level 3)
4. **Orta:** Secrets `.env`'de (doğru); workspace path config'de sabit
5. **Orta:** WebSocket localhost — auth yok (kişisel kullanım OK)

---

# Performans Sorunları

- Her kompleks komut Cursor round-trip
- Brain preload 120s join
- Conversation memory RAM-only, restart'ta kayıp
- Telemetry interval UI'da sık polling

---

# Teknik Borçlar

- Keyword heuristic tekrarları (`model_router` / `task_router` / `macos`)
- `main.py` orchestration + domain logic karışık
- Fake capability mesajları (ekran görme vb.) — dürüst kalınmalı
- Boş `workspace/` kullanımı belirsiz

---

# Ölçeklenebilirlik

Tek kullanıcı / tek cihaz için uygun. Event bus + SQLite ile yerel ölçek yeterli. Çok cihaz sync Phase 4+.

---

# Yapılması Gerekenler

### Kritik / Yüksek (Phase 2–8 tamam + v2.0.0)
Permission, audit, SQLite/FTS, tools, automation, HUD confirm, DecisionEngine,
backup, MCP adapter, optional Playwright, CI — landed.

### Bilinçli eksikler / sonraki
- Multi-device sync (out of scope)
- Heavy ML sentence-transformers (local hashing embeddings yeterli)
- Continuous screen capture (bilinçli olarak yok — yalnızca on-demand)
- MCP sunucu paketleri (config boş; Calendar/Notes istenince eklenir)
- Offline STT (Google STT ağ ister)

### Not
Eski «Zayıf Yönler» (permissions/tests/memory yok) **artık geçerli değil** —
güncel durum: `docs/ARCHITECTURE_AUDIT.md`, `docs/ROADMAP.md`.

---

# Korunan Özellikler (KEEP)

| Özellik | Dosya |
|---------|-------|
| Wake word | `voice/listener.py` |
| Voice I/O | `voice/speaker.py`, `narrator.py` |
| Iron Man HUD | `ui/index.html`, `server.py`, `desktop.py` |
| Cursor integration | `brain/cursor_brain.py`, `sdk_patch.py` |
| macOS control | `system/macos.py` |
| TR/EN | config + brain language lines |
| Model routing | `brain/model_router.py`, `task_router.py` |
| Startup | `main.py`, `start.sh`, `JARVIS.command` |

---

# Refactor vs Add

| KEEP as-is | REFACTOR later | ADD (Phase 2–3) |
|------------|----------------|-------------------|
| voice/*, ui/*, brain/*, system/* | JarvisCore split | core/*, security/*, tools/*, memory/* |
| config.yaml loading | config schema | CommandRouter + real tools |
| Cursor agent path | more macOS via tools | memory recall in prompts |

---

# Migrasyon Stratejisi

### Phase 1 — Analiz ✅
Bu doküman.

### Phase 2 — Foundation ✅
Event bus, permissions, audit, SQLite, task/memory repos, tool registry, soft-init, tests.

### Phase 3 — Integration ✅ (2026-08-13)
- Gerçek tool’lar: `system.*`, `memory.*`, `task.*`, `fs.*`, `diagnostics.health`
- `CommandRouter` → `ExecutionEngine` (ai_only açıkken de)
- Shell/fs için dinamik Level 3 (`resolve_permission` + `security.risk`)
- SQLite memory recall → `JarvisBrain.set_memory_recall` / prompt enjeksiyonu
- Audit: her tool çalıştırması `audit_logs` tablosuna yazılır
- Stub kalan: `browser.navigate`

### Phase 4 — Intelligence ✅ (2026-08-13)
- Gerçek automation engine: daily/weekly/interval tetikleyiciler (stdlib)
- NL → otomasyon (`every morning`, `her pazartesi saat 10`, `at 18:00 remind…`)
- Background scheduler (voice thread’i bloklamaz); fail_count + max_failures
- Proactive: quiet hours + rate limit; daily briefing (tasks/memories/projects)
- Memory extraction (rule-based, secret filtreli)
- Router: briefing + automation CRUD intents (TR/EN)
- Stub kalan: `browser.navigate` (Playwright yok)

### Phase 5 — UX ✅ (2026-08-13)
- Iron Man HUD Command Center sekmeleri: TASKS / MEMORY / PROJECTS / AUTOMATIONS / TOOLS / LOGS / SETTINGS
- Canlı SQLite/core verisi (`ui/hud_data.py` + WS `command_center` + `/api/command-center`)
- Level 2: HUD `permission_notice` toast
- Level 3: `ConfirmationGate` pending kuyruğu + HUD modal + ses “evet/hayır” (worker blokluyken loop intercept)
- Soft-init / `jarvis2.enabled` rollback korundu
- Stub kalan: interactive browser (Playwright yok)

### Phase 6 — Tool Expansion ✅ (2026-08-13)
- **Project registry:** `config/projects.yaml` → SQLite sync (`projects/registry.py`); tools `project.list` / `get` / `set_active`; NL: “Jettel üzerinde çalış”
- **Git tools:** real `subprocess` (`git.status|diff|branch|log` L0, `add|commit` L2, `push` L3); cwd = active project; gerçek stderr, asla sahte başarı
- **Developer agent:** `dev.analyze_repo`, `dev.run_tests`, `dev.run_command` + ExecutionEngine/audit
- **Browser:** `open` + `urllib` (Playwright **yok** / requirements’a eklenmedi); `browser.fill_form` açıkça **NOT IMPLEMENTED**
- **Research:** `research.topic` — DDG Instant Answer → extractive summary; opsiyonel memory save
- **Screen:** `screen.capture` (screencapture), `screen.describe` (frontmost app metadata — OCR yok)
- **Config:** `max_permission_level: 3` (Phase 5 HUD/voice confirm ile); `auto_approve_dangerous: false` korunur
- Failures isolated; wake/HUD/soft-init korunur

### Phase 7 — Planner + Verification + Backup + Hardening ✅ (2026-08-13)
- **Planner:** `core/planner.py` — simple goals skip plan; complex (`plan and`, organize, analyze and fix) → ordered tool steps; optional Task persistence
- **Multi-step execution:** `ExecutionEngine.execute_plan` / `execute_plan_background` — sequential tools, per-step audit, Level-3 denial → pause/resume, voice loop non-blocking
- **Verification + retry:** `core/verification.py` after git.commit / fs.move / run_tests / backup; `plan_max_retries` (default 1); alternate strategy stub (honest)
- **Backup:** `core/backup.py` + `system.backup` (Level 1) → `data/backups/<timestamp>/` (DB + projects.yaml + config.yaml); `backup_retention`
- **Hardening:** block `rm -rf /`; force-push blocked in git tool + dangerous shell; credential path refusal; stronger secret redaction in memory extractor
- **Semantic memory (light):** SQLite **FTS5** (`003_memories_fts.sql`) + multi-token LIKE fallback — no new ML deps
- Router: `plan and …`, `backup memory` / `yedekle`
- Playwright: opsiyonel (`requirements-optional.txt`) — yoksa urllib+open

### Phase 8 — Completion / gap close ✅ (2026-08-13)
- **Event automation:** `file_watch` trigger + Downloads poller; NL «İndirilenlere PDF gelince…»
- **LLM planner refine:** `CursorProvider` + whitelist JSON parse; offline → heuristic
- **Optional Playwright:** lazy import; fill/click only if installed; diagnostics honest
- **MCP adapter:** schema bridge (`integrations/mcp_adapter.py`) — runtime NOT CONNECTED (superseded by Ordered Gap Close layer 1)
- **Model routing:** `brain/llm_provider.py` protocol + existing `ModelRouter`
- **Dev agent:** `fs.read`/`fs.write` + `dev.fix_cycle` (analyze→locate→optional patch→tests)
- **Interrupt:** «Jarvis dur» / stop → `speaker.flush`+killall; follow-up context («şimdi onu aç»)
- **Diagnostics:** planner/browser/mcp/backup/projects in health + «sistem durumunu kontrol et»
- Integration smoke tests added

### Ordered Gap Close ✅ (layers 1–5, 2026-08-13)
1. **Live MCP client:** `integrations/mcp_client.py` (stdio JSON-RPC) + adapter registers `mcp.<server>.<tool>`; `jarvis2.mcp.servers`; empty → diagnostics «no MCP servers»; fake server tests
2. **Vision/OCR:** on-demand `screen.describe` → capture → optional tesseract OCR / LLM vision hook → frontmost-app metadata fallback; never continuous
3. **Local embeddings:** hashing-trick vectors (stdlib, dim=256) on memories; `search_semantic` + FTS fallback; offline-safe
4. **LLM patch loop:** `dev.apply_patch` — analyze → propose (LLM or explicit) → `fs.write` (L2) → `run_tests` → verify; dry_run; mocked LLM tests
5. **Playwright click/fill:** real when installed; honest **NOT AVAILABLE** otherwise; injectable mocks for tests; `requirements-optional.txt`

---

# Orijinal Prompt Karşılama Matrisi

| Bölüm | Durum | Not |
|-------|-------|-----|
| Event bus + soft-init | **done** | `core/event_bus`, `try_create_os` |
| Permissions 0–3 + confirm | **done** | HUD + voice evet/hayır |
| SQLite memory/tasks/audit | **done** | FTS5 + local embeddings |
| Tool registry + ExecutionEngine | **done** | plan + verify + retry |
| Command router TR/EN | **done** | |
| Automation time-based | **done** | daily/weekly/interval |
| Automation file events | **done** | Downloads/`file_watch` poll |
| Proactive briefing | **done** | quiet hours |
| Project registry + git/dev | **done** | + `dev.apply_patch` |
| Planner multi-step | **done** | heuristic + optional LLM |
| Browser read-only | **done** | open + urllib |
| Browser click/fill | **done** | Playwright optional; NOT AVAILABLE without |
| MCP live servers | **done** | stdio client; empty config OK |
| Screen OCR/vision | **done** | on-demand OCR optional + metadata fallback |
| Wake/HUD/Cursor/TR-EN | **done** | preserved |
| Embedding vector search | **done** | local hashing + FTS fallback |
| Multi-device sync | **not done** | out of scope |

---

# Feature Flag

```yaml
jarvis2:
  enabled: true
  soft_init: true
  db_path: data/jarvis.db
  max_permission_level: 3
  auto_approve_dangerous: false
  automation: true
  automation_tick_seconds: 15
  confirm_timeout: 60
  plan_max_retries: 1
  backup_retention: 10
  file_watch_enabled: true
  proactive:
    enabled: true
    quiet_hours_start: 22
    quiet_hours_end: 7
ui:
  command_center_interval: 5
```

`enabled: false` → v1 davranışı birebir.

# Browser notları (dürüst)

| Tool | Durum |
|------|--------|
| `browser.open_url` | macOS `open` / webbrowser |
| `browser.search` | DDG results sayfasını açar |
| `browser.get_page_text` | urllib fetch + HTML strip |
| `browser.fill_form` / `browser.click` | Playwright **opsiyonel**; yoksa **NOT AVAILABLE** (sahte başarı yok) |

### MCP / Vision / Embeddings / Patch (dürüst)

| Özellik | Durum |
|---------|-------|
| MCP stdio client | `jarvis2.mcp.enabled` + `servers[]`; yoksa diagnostics OK |
| Screen describe | On-demand; OCR opsiyonel (tesseract); yoksa frontmost metadata |
| Embeddings | Local hashing (dim=256); FTS fallback; heavy ML yok |
| `dev.apply_patch` | LLM veya explicit path/content; L2 write + tests; dry_run |
