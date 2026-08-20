# JARVIS 2.0 — Architecture Audit

**Proje:** `/Users/mac/Desktop/jarvis-ironman-main`  
**Tarih:** 2026-08-18  
**Faz:** Phase 0 — Audit (kod değiştirilmedi)  
**İlke:** Mevcut çalışan parçaları koru. Körlemesine rewrite yok.  

---

# 1. Genel Amaç

JARVIS 2.0, kullanıcının bilgisayarında çalışan, doğal dille konuşulan istekleri anlayan, planlayan, araçları kullanan, gerçek işlemler yapan, sonuçları doğrulayan, geçmiş bağlamı hatırlayan, otomasyonlar çalıştıran, hata durumlarında toparlanan, sesli iletişim kurabilen ve kullanıcıyla uzun süreli çalışan gerçek bir Personal AI Operating System olmakta. Sistem, Cursor SDK tabanlı sesli macOS asistanı + yanına eklenmiş JARVIS 2.0 OS çekirdeği структурда. Hedef “Personal AI OS” olarak yazılmış; üretim yolu hâlâ hibrit chatbot + keyword-tool router'dır.

# 2. Kullanılan Teknolojiler

| Katman | Teknoloji | Not |
|--------|-----------|-----|
| Runtime | Python 3.10+ | Tek süreç, thread'ler |
| Beyin | `cursor-sdk` (`Agent` / `Cursor`) | Tek provider; OpenAI/Anthropic doğrudan yok |
| TTS | edge-tts (`en-GB-RyanNeural`) + `afplay` / `say` | Runtime İngilizce kilitli |
| STT | Native Swift mic + SpeechRecognition | `listen_language: tr-TR` |
| HUD | aiohttp WebSocket + HTML + opsiyonel pywebview | Port 8765 |
| REST | aiohttp `/api/health`, `/api/state`, `/api/command` | HUD yanında |
| DB | SQLite WAL (`data/jarvis.db`) | PostgreSQL yok (bilinçli) |
| Embeddings | Hashing-trick 256-dim | Gerçek sentence model yok |
| Browser | `webbrowser` + opsiyonel Playwright | Playwright yoksa dürüst düşüş |
| Config | `config.yaml` + `.env` + `config/personality.yaml` | Şema doğrulama yok |
| Test | `unittest` (`tests/`) | ~40+ modül; E2E ses/Cursor canlı değil |

# 3. Mimari Yapı

## 3.1 Genel Yapı (Gerçek)

```
USER (mic / HUD / REST / text)
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  JarvisCore  (main.py)  — monolit orkestratör             │
│  voice gate, TTS, HUD, latency, preference, stop/dur      │
└─────────────┬─────────────────────────────┬───────────────┘
              │                             │
              ▼                             ▼
     JarvisOS.try_handle_command     JarvisBrain.think*
     (core/app.py)                   (brain/cursor_brain.py)
              │                             │
       DecisionEngine                          │
       BrainRouter (fast/deep)                 │
       CommandRouter (keyword)                 │
              │                             │
              ▼                             ▼
     ExecutionEngine                 Cursor SDK Agent
     ToolRegistry + verify           ModelRouter (keyword)
     PermissionGate + Audit          ConversationMemory (RAM)
              │                             │
              ▼                             ▼
         SQLite memory/tasks          optional memory.recall_for_prompt
         EventBus (kısmi HUD)
```

**İki orkestratör:** `JarvisCore` (~1530 satır) + `JarvisOS` (~860 satır). Spec’teki `JarvisOrchestrator` yok; sorumluluk dağınık.

## 3.2 Klasör Yapısı

```
main.py                 # v1 orkestratör + soft-init v2
config.yaml             # runtime flags (autonomy, voice, models)
config/                 # loader, personality.yaml, projects.yaml
brain/                  # Cursor SDK, model/task router, conversation
voice/                  # STT, TTS, self-listen, speech_clean
system/                 # macos heuristics, host metrics, screen, light mode
ui/                     # HUD HTML + WS server + desktop
core/                   # JarvisOS, router, execution, planner, agent loop
tools/                  # registry + 20+ tool modülü
memory/                 # SQLite, FTS, layers, extractor, embeddings
security/               # permission 0–3, confirm, audit, risk
automation/             # scheduler + file watch
proactive/              # briefing + notifier
projects/               # project registry
integrations/           # MCP adapter
docs/                   # mimari belgeler
tests/                  # unittest
data/                   # jarvis.db (gitignore)
```

## 3.3 Veri Akışı (Komut)

```
STT / HUD WS / REST
  → self-listen gate
  → confirm / "dur" / mic control
  → JarvisOS:
        DecisionEngine (clarify | rewrite | proceed)
        BrainRouter:
           FAST → CommandRouter → ExecutionEngine → verify → speak
           DEEP → None (fallthrough)
  → try_local_meta (saat/status/voice)
  → legacy MacOSController heuristics
  → Cursor JarvisBrain (timeout / background / active-run recovery)
  → TTS + HUD + latency_stats + optional memory ingest
```

## 3.4 API Akışı

| Yüzey | Protokol | Auth |
|-------|----------|------|
| HUD | WebSocket `/ws` | Yok (localhost) |
| REST | `GET /api/health`, `GET /api/state`, `POST /api/command` | Yok (localhost) |
| MCP | stdio (config boş → bağlı değil, dürüst) | N/A |

Harici kimlik doğrulama yok. Kişisel cihaz varsayımı.

## 3.5 Authentication / Authorization

- **Auth:** `CURSOR_API_KEY` (`.env`). GitHub: `GITHUB_TOKEN` veya `gh`.
- **AuthZ:** `PermissionLevel` 0–3 + `ConfirmationGate`.
- **Bu makine:** `full_autonomy: true`, `auto_approve_dangerous: true`, `full_shell_access: true`, `max_permission_level: 3` → Level-3 fiilen otomatik (audit kalır; catastrophic `rm -rf /` hard-block).
- **Loader default:** `full_autonomy: false` — config.yaml override ediyor.

## 3.6 Veritabanı

SQLite tabloları: `projects`, `memories` (+ FTS5), `tasks`, `automations`, `events`, `audit_logs`, `schema_migrations`.
Task status: `pending | in_progress | done | cancelled`. Spec’teki `PLANNING / WAITING / RETRYING / FAILED` yok.
ID’ler integer autoincrement; spec’teki `task_01HX…` ULID yok.

## 3.7 Voice

```
Mic → VoiceListener (wake optional) → command queue
TTS → VoiceSpeaker (Ryan) → SelfListenGuard cooldown → listen resume
```

Wake word altyapısı var; `ui.require_wake_word: false` (sürekli dinleme).
Barge-in: `"dur"` → TTS flush + Cursor interrupt. Tool-level `CancellationToken` yok.

## 3.8 Tool Envanteri (Kayıtlı, Gerçek)

`system.open_app/close_app/time/date/volume/web_search/shell/notify/processes/health/check_permissions`,
`clipboard.*`, `finder.reveal`, `mail.*`, `calendar.*`, `github.*`,
`memory.*`, `preference.apply`, `task.*`, `fs.*`, `diagnostics.health`,
`browser.open_url/list_tabs/search/get_page_text/fill/click`, `media.play`,
`research.topic`, `screen.capture/describe`, `git.*`, `dev.*`, `dev.apply_patch`,
`agent.research`, `agent.coding_analyze`, `system.backup`, `plan.run`,
`project.*`, `automation.*`, `proactive.briefing`.

`BaseTool` sözleşmesi: `name`, `description`, `permission_level`, `input_schema`, `run()`.
Spec’teki `validate()` / `rollback()` tool interface’te yok (validate registry’de şema kontrolü).

# 4. Mimari Problemler

## 4.1 Spec vs Gerçek (Özet)

| Master spec bileşeni | Durum | Gerçek karşılık |
|----------------------|-------|-----------------|
| JarvisOrchestrator | **Yok** | `JarvisCore` + `JarvisOS` |
| IntentEngine | **Kısmi** | Keyword/regex (`CommandRouter`, `mode_selector`, `decision_engine`) |
| ContextEngine (katmanlı) | **Kısmi** | `ContextManager` + RAM deque + SQLite layers |
| PlanningEngine | **Kısmi** | `Planner` + Cursor agent; structured JSON plan zorunlu değil |
| TaskManager stateful | **Kısmi** | CRUD; resume仅的确认暂停 |
| ToolRegistry | **Var** | İyi; rollback/plugin yok |
| Execution + verify | **Var** | Allowlist tool’larda; Cursor path zayıf |
| RecoveryEngine | **Kısmi** | Plan retry (`plan_max_retries: 1`); tekil tool retry yok; exponential backoff yok |
| MemoryEngine hybrid | **Kısmi** | FTS + hashing cosine; retrieval formülü kaba |
| ModelRouter + fallback | **Kısmi** | Keyword classify; tüm alias’lar `composer-2.5`; local LLM yok |
| Event bus | **Var** | HUD tam event-driven değil |
| Streaming | **Kısmi** | `stream_preview: false` |
| Plugin architecture | **Yok** | `register_phase3_tools` monolit |
| Human-in-the-loop UI | **Kısmi** | Confirm var; pause/retry butonları zayıf |
| Offline / degraded | **Kısmi** | Fast tools lokal; DeepBrain internet/Cursor’a bağlı |

## 4.2 Çift Yol Karmaşası

Aynı intent üç yerde çözülebilir:
1. `core/command_router.py`
2. `system/macos.py` legacy heuristics (`main.py` `_try_legacy_actions`)
3. Cursor agent tool çağrıları

Fast path kaçarsa DeepBrain’e düşer → yavaş, pahalı, “Could not open” yerine genel sohbet.

## 4.3 Intent = Keyword

`"Şu projeye bir bakar mısın?"` → `PROJECT_ANALYSIS` structured intent üretilmez.
`mode_selector` “bak/hata/repo” kelimelerine göre CODE/RESEARCH atar.
`"Onu düzelt"` kısmen `ContextManager.resolve_followup` + prompt’a bağlı; güvenilir değil.

## 4.4 Chatbot Kalıntısı

`ai_only` kapalı olsa bile eşleşmeyen her şey Cursor chat’e gider.
LLM planner/decision/tool-selector olarak **her zaman** kullanılmıyor; çoğu eylem regex.

## 4.5 Config Sapması

- `jarvis.workspace` → `/Users/mac/Desktop/Projeler/projelerim-github/jarvis-ironman` (bu repo değil)
- README: Türkçe-only Emel; runtime: İngilizce Ryan kilit
- `full_autonomy: true` vs loader default `false`
- `user_name: neydi` (placeholder / STT artığı riski)

## 4.6 Hata Yutma

Birçok `except Exception: pass` (`core/app.py`, `memory/preference.py`, `main.py`).
Hata kaybolur; recovery sınıflandırması yok (`NETWORK_ERROR` vs `TIMEOUT` enum’u yok).

# 5. "Could not open" — Kök Neden Analizi

Kullanıcıya yansıyan `Could not open` **tek bir bug değil**; bir **arıza sınıfı**.

## 5.1 Üretim Noktaları

| Kaynak | Mesaj | Tetik |
|--------|-------|--------|
| `tools/macos_tools.py` `OpenAppTool` | `Could not open «{name}».` | `_open_app` `None` döner |
| `tools/browser_tools.py` | `Could not open «{url}».` | URL açılamadı |
| `tools/media_tools.py` | `Could not open Spotify/YouTube` | media.play fail |
| `core/verification.py` | `Could not verify that.` | claim_safe fallback |
| Cursor / SDK | `Could not connect` / timeout / Bridge | DeepBrain |

TTS yolu: `speak_safe(..., language="en-GB")` **Türkçe çeviri yapmaz**.
`speak_safe_tr` var ve testlerde `"Could not open Chrome"` → `"açılamadı"` beklenir; **konuşma path’i bu fonksiyonu kullanmıyor**. Sonuç: kullanıcı ham İngilizce hata duyar.

## 5.2 Zincir: open_app

```
STT metni
  → extract_open_target / CommandRouter._open_app
  → ExecutionRequest(system.open_app, {name})
  → OpenAppTool.run
       resolved = MacOSController._resolve_app_name(name) or name
       msg = _open_app(resolved)
            subprocess: open -a "{name}"
            returncode != 0 veya timeout → None
       None → ToolResult(ok=False, error="Could not open «{name}».")
  → ExecutionEngine.verify (_verify_open_app)
  → claim_safe_speech → İngilizce error
  → kullanıcıya doğrudan yansır
```

**Retry / fallback / Spotlight / LaunchServices / “hangi uygulamayı?” clarification yok.**
Tekil `execute()` içinde `max_retries` yok; retry yalnızca **plan adımlarında** (`plan_max_retries: 1`).

## 5.3 Kök Nedenler (Öncelik Sırası)

### A. Hedef Çıkarımı (Yüksek)

Türkçe morfoloji + STT:
- `"açık sekme"` → fiil `aç` + art<ık> `ık` (düzeltilmiş + testli; regression riski duruyor)
- `"Chrome'u açsana"` / `"açar mısın"` — alias tablosu sınırlı
- STT: `"krom"` → alias var; `"çift gp"` → chrome; bilinmeyen gurultü → `open -a <garbage>`
- Bare 1–2 kelime `APP_HINTS` ile open_app’e zorlanabilir

`open -a` macOS’ta **tam uygulama adı** ister. Yanlış string = sessiz fail = `Could not open`.

### B. Çözümleme Zayıf (Yüksek)

`_resolve_app_name` yalnızca `APP_ALIASES` + substring.
Yok: `/Applications` taraması, `mdfind kMDItemKind==Application`, fuzzy match, bundle id.

### C. `open -a` Tek Deneme (Yüksek)

Timeout 15s, `returncode != 0` → `None`.
Stderr loglanmıyor kullanıcıya. Alternatif: `open /Applications/X.app`, URL scheme, `webbrowser`.

### D. Hata Mesajı Politikası (Yüksek — Spec İhlali)

Spec: kullanıcıya `Could not open` gösterme.
Kod: tam olarak bunu konuşuyor. Recovery cümlesi yok (“uygulama adını netleştiriyorum / Spotlight’ta arıyorum”).

### E. Cursor / Network (Orta — Ayrı Sınıf)

`sdk_patch.py` timeout’ları yükseltir. Yine:
- Bridge `tool-callback-auth-token` / `Bridge exited`
- `ReadTimeout` → arka plan retry
- Model unavailable → sistem çökmez ama “Neural link isn’t ready”

Bunlar `Could not connect` ailesi. Fast tools çalışır; DeepBrain durur. **Local LLM fallback yok.**

### F. Playwright / TCC (Orta)

Browser click/fill Playwright yoksa dürüst fail.
Ekran kaydı izni yoksa screen tool fail. Mesajlar bazen İngilizce teknik.

## 5.4 Neden “Zaman Zaman”

1. STT gürültüsü / yanlış kelime
2. Uygulama adı çözülemedi
3. Uygulama yüklü değil / isim farklı (Google Chrome vs Chrome)
4. Cursor bridge anlık timeout
5. Fast path kaçtı, DeepBrain “open”i kendisi denedi ve genel hata döndü
6. Verify, tool `ok=True` ama post-condition fail → “Could not verify”

## 5.5 Olması Gereken (Henüz Yok)

```
Tool Request
  → timeout? → retry (max 3, exponential backoff)
  → hâlâ fail? → alternative (Spotlight / bundle / URL)
  → hâlâ fail? → clarification (“Chrome mi, Chromium mı?”)
  → kullanıcıya: ne denendi, ne kaldı — ham exception değil
```

# 6. Stabilite Problemleri

1. **Tek worker lock:** `_processing` — ikinci komut atlanır (`Hâlâ işleniyor, atlandı`). Kuyruk var ama worker tek.
2. **Cursor active-run race:** recovery + test var; SDK kenar durumları kalabilir.
3. **Soft/hard timeout:** hard `0` (iptal yok); uzun görevler arka planda — iyi. Soft ping 5s.
4. **Daemon background plan:** süreç kapanınca plan ölür; kalıcı resume yok.
5. **Automation tick 30s:** file watch + briefing; light-mode yüksek CPU’da durdurur.
6. **Screen watcher** `always_watch: true` + 15s poll — kaynak ve TCC bağımlı.
7. **Boot music / osascript** başarısız olursa uyarı; boot devam eder (iyi).
8. **Yutulan exception’lar** sessiz bozulma üretir.
9. **Workspace yanlış path** → Cursor yanlış repo’da çalışır.
10. **Sonsuz loop koruması kısmi:** `deep_max_iterations: 8`, `max_plan_steps: 12`; Cursor SDK kendi döngüsü ayrı.

# 7. Güvenlik Problemleri

| Seviye | Risk | Kanıt |
|--------|------|--------|
| Kritik | `full_shell_access` + `system.shell` `shell=True` | `tools/macos_tools.py` |
| Kritik | `full_autonomy` + `auto_approve_dangerous` | `config.yaml` |
| Yüksek | HUD/REST localhost auth yok | Kişisel OK; LAN açık port riski |
| Yüksek | Secrets memory redact var; tool arg audit’te durabilir | `audit_logs.details` |
| Orta | Path traversal fs tools — working_dir’e bağlı, sandbox zayıf | `tools/fs_tools.py` |
| Orta | Credential path pattern’leri risk.py’de; tüm yazma yollarını kapsamayabilir | |
| Orta | CORS/CSP HUD HTML — yerel dosya; XSS düşük öncelik ama `send_response` ham metin | |
| Düşük | `.env` gitignore’da; `user_name` config’de düz metin | |

**Korunan:** catastrophic shell hard-block, secret redact extractor, permission gate altyapısı, audit log.

**Eksik (spec):** rate limit, tool sandbox, dry-run zorunluluğu HIGH+, transaction/rollback, progressive autonomy UI.

# 8. Performans Problemleri

| Hedef | Gerçek |
|-------|--------|
| Basit komut <1s | Fast path genelde evet; miss olursa Cursor saniyeler–dakikalar |
| Streaming progress | `stream_preview: false`; DeepBrain sessiz kalabilir (ack + 5s ping) |
| Parallel tool | Yok; plan adımları sıralı |
| Context büyütme | `conversation_turns: 40` + recall 3 item / 300 char — makul |
| Model cost | Tüm kategoriler `composer-2.5`; cheap/fast ayrımı fiilen kapalı |
| Cost meter | Tahmini char/token; fatura değil; rate’ler 0.0 |
| CPU | host_metrics normalize edilmiş; light_mode var |
| Brain preload | `join(timeout=120)` — boot’u uzatabilir |

`LatencyStats` + `prefer_tool` ipucu var; router kaçırırsa işe yaramaz.

# 9. Güncel AI / Model Mimari

```
config.jarvis.llm_provider: cursor
model: composer-2.5
models.*: hepsi composer-2.5 (deep: auto)
model_routing: true  → ModelRouter.classify(keyword) → aynı model
```

- **FAST MODEL / LOCAL / FALLBACK:** yok.
- **Vision:** `tools/vision.py` + screen describe; ayrı vision model router yok.
- **Structured agent output (JSON intent/plan):** zorunlu değil; planner whitelist tool adları ile LLM refine opsiyonel.
- **Hallucination control:** prompt + `claim_safe_speech` Fast path’te; DeepBrain’de prompt’a güvenilir — tool evidence zorunluluğu SDK’ya bağlı.

`brain/llm_provider.py` `CursorProvider` — abstraction ince; ikinci provider takmak mümkün ama kullanılmıyor.

# 10. Güncel Tool Mimari

**Güçlü:** merkezi registry, permission, audit, input schema, verify allowlist, bootstrap kaydı.

**Zayıf:**
- Intent→tool seçimi LLM değil, regex sırası (`command_router.route` uzun if zinciri)
- `rollback()` yok
- Plugin `register()` paketi yok (`tools/packages/` boş iskelet)
- Terminal pipeline: `command → validate → run → parse logs → verify` eksik (`ShellTool` exit code + 200 char stdout)
- Browser kritik işlem (login/pay/send) confirmation tutarsız
- Dry-run yok

# 11. Güncel Mimari

| Katman (spec) | Gerçek |
|---------------|--------|
| Short-term | `ContextManager` + `ConversationMemory` deque |
| Working | session extras, active project, last open |
| Episodic | `category=episodic` on ingest (önemli turlar) |
| Semantic | FTS5 + hashing cosine |
| Procedural | Yok (nasıl iş yapılır kayıtlı değil) |
| Profile | `memory/layers.py` keys `user_*` |

**Retrieval:** limit 3, max 300 char; hybrid var (keyword FTS + semantic) ama scoring tam formül değil.
**Secrets:** extractor redact.
**Trivial skip:** var.
Her istekte full dump yok — iyi.

Eksik: task-level lessons, learning loop, vector DB abstraction.

# 12. Önerilen JARVIS 2.0 Mimari

**Rewrite değil — evrim.** Yeni isimler mevcut dosyalara map edilir.

```
                    ┌─────────────────────────┐
                    │   JarvisOrchestrator    │  (İNCE FAÇADE)
                    │   = JarvisOS + hooks    │  main.py küçülür
                    └───────────┬─────────────┘
                                │
             IntentEngine*    ContextEngine     PlanningEngine
             (evolve Decision + Router)  (layers+)   (Planner + structured)
                                │
                     TaskManager (state machine)
                                │
              ToolRegistry ── ExecutionEngine ── RecoveryEngine
                                │
              Observation/Verify ── MemoryEngine ── ResponseEngine
                                │
              ModelRouter (fast/smart/vision/fallback)
                                │
                         EventBus ── HUD / Voice / REST
```

\* İlk sürümde ayrı mikroservis yok. `DecisionEngine` + `CommandRouter` + opsiyonel küçük LLM classify (cheap model) birleşir.

**Golden path (hedef):**

```
request_id
  → complexity: CHAT | SIMPLE | MEDIUM | COMPLEX | AUTONOMOUS
  → CHAT/SIMPLE: Fast tools only (Cursor yok)
  → MEDIUM+: plan (structured) → execute → verify → evidence
  → fail: classify → retry ≤3 backoff → alternate → clarify
  → memory update (relevant only)
  → speech: NE YAPTIM / SONUÇ / İHTİYAÇ  (kanıtlı)
```

**Korunan dış yüzey:** wake, HUD, Cursor DeepBrain, macOS, SQLite.

# 13. KEEP / REFACTOR / REPLACE / REMOVE

## KEEP (çalışıyor, dokunma veya ince tut)

| Parça | Neden |
|-------|--------|
| `voice/listener.py`, `speaker.py`, `self_listen_guard.py` | Ses pipeline üretimde |
| `voice/speech_clean.py` | efendim/filler; `speak_safe_tr` genişletilecek |
| `ui/index.html`, `ui/server.py` | HUD + WS |
| `brain/cursor_brain.py`, `sdk_patch.py` | DeepBrain; active-run/timeout testli |
| `brain/conversation.py` | Kısa bellek |
| `tools/registry.py`, `tools/base.py` | Sözleşme |
| `security/permissions.py`, `risk.py`, `audit.py`, `confirmation.py` | Altyapı doğru |
| `memory/database.py`, migrations, FTS | Offline-first |
| `core/event_bus.py`, `execution_engine.py`, `verification.py` | İskelet doğru |
| `core/diagnostics.py`, `core/backup.py` | Health + yedek |
| `tests/test_timeout_race.py`, `test_fast_path.py`, `test_self_listen_guard.py`, `test_active_run_recovery.py` | Regression altın |
| `start.sh`, `.env.example` | Boot |

## REFACTOR (kontrollü)

| Parça | Neden | Yön |
|-------|--------|-----|
| `main.py` JarvisCore | 1500+ satır karışık | Voice loop + bootstrap; domain → JarvisOS |
| `core/app.py` | Facade şişiyor | Orchestrator API netleştir |
| `core/command_router.py` | 1300+ satır keyword | Intent table + confidence; LLM classify yalnız düşük confidence |
| `core/open_target.py` | Morfoloji yamaları | App resolver servisi + test corpus |
| `system/macos.py` | Legacy + tools çift | Tools tek kaynak; macos düşük seviye |
| `tools/macos_tools.py` OpenApp | Could not open | Retry + resolve + TR/EN mesaj politikası |
| `brain/model_router.py` | Hepsi aynı model | Cost/complexity routing gerçek ayrım |
| `memory/layers.py` | Kategori convention | Retrieval policy + procedural |
| `core/task_manager.py` | 4 status | Spec state machine + resume |
| `core/agent_loop.py` | İnce | observe/think/verify + evidence |
| `config.yaml` | Tehlikeli default + yanlış workspace | Safe profile + bu repo path |
| `except Exception: pass` | Gözlük | log + classify |

## REPLACE (davranış; dosya silme yok)

| Davranış | Yerine |
|----------|--------|
| Kullanıcıya ham `Could not open` | Recovery speech + developer log |
| Keyword-only intent (uzun vadede) | Hybrid: rules (yüksek precision) + cheap classify |
| Plan fail → tüm iş baştan | Checkpoint resume |
| DeepBrain her miss | Complexity gate + clarify |

## REMOVE (sonra; şimdi silme)

| Aday | Koşul |
|------|--------|
| `system/macos.py` try_quick_action örtüşmesi | Tool path %100 kapsayınca |
| `StubTool` production bootstrap | Zaten phase3 real tools |
| README’deki Emel-only iddiası | Doküman senkronu (kod İngilizce kilitli) |
| Yanlış `workspace` path | Düzelt |

**Yapılmayacak:** PostgreSQL zorunluluğu, full rewrite, voice/HUD/Cursor kaldırma, hashing embeddings’i hemen sentence-transformers ile değiştirme.

# 14. Dosya-başa-değişim Planı (Sonraki Fazlar — Henüz Uygulanmadı)

Öncelik: P0 güvenlik/stabilite → P1 orkestrasyon → P2 yetenek.

| Dosya | Aksiyon | Faz | Risk |
|-------|---------|-----|------|
| `config.yaml` | workspace bu repo; autonomy profili belgele | 1 | Düşük |
| `tools/macos_tools.py` | open retry/fallback/mesaj | 1 | Düşük |
| `system/macos.py` | `_open_app` | stderr log, alternate open | 1 | Düşük |
| `voice/speech_clean.py` | speak_safe hata politikası (ham EN yok) | 1 | Düşük |
| `core/execution_engine.py` | tekil tool retry + backoff + error class | 1 | Orta |
| `core/app.py` try_handle_command | fail → alternate/clarify, Cursor’a kör düşme azalt | 1 | Orta |
| `core/open_target.py` + tests | STT corpus genişlet | 1 | Düşük |
| `main.py` | process_command sadeleştir (davranış aynı) | 2 | Orta |
| `core/command_router.py` | intent registry’ye böl | 2 | Orta |
| `core/task_manager.py` | status enum genişlet | 4 | Orta |
| `brain/model_router.py` | gerçek cheap vs smart | 6 | Orta |
| `tools/base.py` | optional rollback hook | 3 | Düşük |
| `ui/index.html` | task timeline | 8 | Orta |
| `docs/*` | ARCHITECTURE, TOOLS, SECURITY… | her faz | Düşük |

# 15. Test Stratejisi

Mevcut: birim + smoke; canlı Cursor/mikrofon yok.

Hedef piramit:

| Katman | Şimdi | Ekle |
|--------|-------|------|
| Unit | Router, open_target, verify, permissions | Error classify, retry, app resolve |
| Tool | Birçok tool mock’lu | OpenApp fail matrix (ık, garbage, missing app) |
| Agent | `test_agent_loop` | max_steps, evidence, no false claim |
| Memory | repo + layers | retrieval policy, secret redact |
| Recovery | timeout_race, active_run | network fail, model unavailable, tool timeout |
| Chaos | Yok | Inject timeout/None/bridge exit |
| E2E | Yok | Text-mode senaryolar (kabul kriterleri) |

Kural: faz fail olursa yeni özellik yok.
`python -m unittest discover -s tests -v`

# 16. Üretim Stratejisi

Bu ürün **tek kullanıcı / tek Mac**. “Enterprise multi-tenant” değil.

1. **Safe profile:** `full_autonomy: false` varsayılan; kişisel override açık belgelensin
2. **Workspace guard:** Cursor yalnızca kayıtlı project path
3. **Secrets:** `.env` only; audit’te arg truncate
4. **Degraded mode:** Cursor down → Fast tools + dürüst “beyin bağlı değil”
5. **Observability:** request_id (var) + structured log (kısmi) + asla kullanıcıya stack trace
6. **Backup:** mevcut `BackupService` — boot/health’e bağla
7. **Release:** unittest + manuel 10 kabul senaryosu
8. **PostgreSQL:** gerekirse abstraction sonra; şimdi SQLite

# 17. Güçlü / Zayıf / Borç

## Güçlü Yönler

- Çalışan ses + HUD + wake/listen gate
- Fast local tools (saat, app, media, git, fs) gerçekten icra ediyor
- Permission/audit/verify iskeleti
- SQLite second-brain başlangıcı
- Timeout race ve echo için testli düzeltmeler
- Soft-init: v2 fail olursa v1 yaşar

## Zayıf Yönler

- Orkestratör bölünmüş
- Intent keyword
- Open-app kırılgan
- DeepBrain chatbot fallback
- Autonomy bu makinede açık
- Dil doküman/kod çelişkisi
- Streaming ve task resume zayıf

## Teknik Borç

- Keyword listeleri 5+ dosyada
- `except: pass`
- Config şemasız
- Embeddings hashing
- Playwright/MCP “var gibi” algısı (diagnostics dürüst, UX değil)
- `main.py` + `JarvisOS` tercih/dil tekrarı

## Ölçeklenebilirlik

Tek cihaz için yeterli. EventBus + SQLite doğru temel. Çok ajan/çok cihaz sonra.

# 18. Spec Kabul Senaryoları — Bugünkü Gerçeklik

| Senaryo | Fast tool? | Doğrulanmış icra? | Not |
|---------|------------|-------------------|-----|
| Projeyi analiz et | `dev.analyze_repo` / plan / Cursor | Kısmi | Background plan veya DeepBrain |
| Bu hatayı bul | Keyword → CODE → Cursor | Zayıf | Gerçek inspect garanti değil |
| Hatayı düzelt | patch/fix_cycle var | Kısmi | Verify test’e bağlı |
| Testleri çalıştır | `dev.run_tests` | Evet (tool) | Router kaçırırsa chat |
| Git durum | `git.status` | Evet | |
| Dün kaldığımız yer | episodic + context | Zayıf | “dün” temporal query yok |
| Bu dosyayı düzenle | fs.write / Cursor | Kısmi | |
| Sistem durumu | host_metrics / diagnostics | Evet | |
| Başarısızı tekrar dene | plan resume sınırlı | Hayır | Kullanıcı komutu tekrar eder |
| Durdur | TTS + Cursor interrupt | Kısmi | Tool iptali yok |

**Sonuç:** JARVIS 2.0 master spec **tamamlanmış sayılmaz**. İskelet güçlü; “personal OS” davranışı henüz tutarlı değil.

---

*Değişiklik onayından sonra bu belge güncellenecektir.*