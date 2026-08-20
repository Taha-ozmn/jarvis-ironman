# JARVIS Second Brain / Autonomous AI Assistant — Mimari Denetim

**Proje:** `/Users/mac/Desktop/jarvis-ironman-main` (jarvis-ironman → JARVIS 2.0)  
**Tarih:** 2026-08-14  
**Kapsam:** Analiz + mevcut klasörlere map; büyük rewrite yok  
**Kaynaklar:** `main.py`, `brain/`, `voice/`, `core/`, `memory/`, `tools/`, `automation/`, `security/`, `ui/`, `config.yaml`, `docs/`, `tests/` + bilinen UX ağrı noktaları (timeout race, echo, efendim, CPU %99, tabs, active run, false claim, Emel TR-only)

---

## CURRENT ARCHITECTURE

İki katmanlı hibrit:

| Katman | Giriş | Rol | Durum |
|--------|-------|-----|--------|
| **v1 orchestrator** | `main.py` → `JarvisCore` (~1426 satır) | Wake, STT, TTS, HUD, Cursor fallback, latency kayıt | **Çalışıyor (monolit)** |
| **v2 OS facade** | `core/app.py` → `JarvisOS` (~658 satır) | EventBus, SQLite, ToolRegistry, ExecutionEngine, CommandRouter, memory/tasks/automation | **Soft-init ile yan yana; production path’te kullanılıyor** |

```
Mic / HUD WS
  → JarvisCore.process_command / _run_command
       ├─ confirm / stop / listen / preference (meta)
       ├─ JarvisOS.try_handle_command  → CommandRouter → ExecutionEngine → tools/*
       ├─ try_local_meta / legacy macos heuristics
       └─ JarvisBrain.think* (Cursor SDK) — Deep path
            ├─ ModelRouter (action/code/system/search/chat)
            ├─ task_router complexity (simple/complex/deep) + soft/hard timeout
            └─ ConversationMemory (RAM deque) + optional SQLite recall prompt
```

**Veri:** SQLite `data/jarvis.db` (WAL), FTS5 memories, hashing embeddings (dim=256). PostgreSQL yok (bilinçli).  
**Beyin:** Tek Cursor agent (`brain/cursor_brain.py`); ayrı FastBrain/DeepBrain sınıfı yok — fast = local tools, deep = Cursor.  
**Ses:** `voice/listener` + `speaker` (edge-tts Emel) + `SelfListenGuard` + `speech_clean` (efendim strip).  
**UI:** `ui/server.py` WebSocket + Iron Man `index.html` Command Center.

`docs/JARVIS_2_ARCHITECTURE.md` Phase 2–8 + Ordered Gap Close’u **done** olarak işaretliyor; Second Brain hedeflerinin bir kısmı hâlâ eksik/kısmi (aşağıda).

---

## CURRENT FEATURES

### Done (üretimde / testli)

- Wake word + continuous listen (`ui.always_listen`, `require_wake_word: false`)
- Türkçe-only UX + Emel (`tr-TR-EmelNeural`); İngilizce yanıt kilidi
- Fast local tools: open/close app, time/date, volume, weather, media.play, browser tabs/open/search, mail, clipboard, notify, finder, processes
- `system.health` (host CPU/RAM/swap — çekirdek düzeltmeli) vs `diagnostics.health` (subsystem)
- Tool registry + PermissionLevel 0–3 + ConfirmationGate + AuditLog
- SQLite memory CRUD + FTS + semantic hashing search + rule-based extractor (secret redact)
- Tasks, projects registry, git/dev/patch tools, planner + verify/retry, backup
- Automation scheduler + file_watch + proactive briefing (quiet hours)
- Screen watcher (on-demand OCR/vision hook) + light-mode (yüksek yükte pause)
- Model routing + complexity timeouts + soft/hard timeout race fix + active-run recovery
- LatencyStats (`data/latency_stats.json`) — path: tool/cursor/legacy/meta
- Echo/self-listen guard + post-TTS cooldown
- efendim strip (`voice/speech_clean.py`) + prompt’ta yasak
- Verify-before-claim hooks (open_app, media.play, browser.open_url, git.commit, …)
- MCP stdio client (config boşsa dürüst “not connected”)
- HUD Command Center (tasks/memory/projects/automations/tools/logs)
- ~31 test modülü (fast_path, timeout_race, self_listen, active_run, memory, …)

### Partial

- Memory “second brain”: tek `memories` tablosu + category; working/episodic/semantic/profile ayrımı yok
- Importance alanı var; skorlama kaba (çoğu extract → importance=2)
- Streaming: `stream_preview` config flag var, varsayılan `false`; gerçek token stream UX zayıf
- Two-brain: fiilen tool vs Cursor; formal FastBrain/DeepBrain API yoktu (Phase 1 sonrası ince wrapper)
- Agent loop: Cursor agent + planner steps; açık `max_iterations` politika katmanı yok
- Personality: prompt string’leri `cursor_brain.py` içinde; ayrı YAML yoktu
- Cost control: model alias’ları var; token/cost meter yok
- Observability: latency JSON + print; structured request_id / tracing yoktu
- Barge-in: “Jarvis dur” / flush var; konuşma ortası kesme rafine değil
- Research/coding agents: tool’lar var; ayrı agent persona/loop değil
- API-first: HUD WS + internal tools; dış REST API yüzeyi yok

### Missing / Broken (bilinen ağrı noktaları ile)

| Konu | Durum |
|------|--------|
| False “I did it” | Kısmen düzeltilmiş (verify + prompt); Cursor yolu hâlâ tool success olmadan claim riski |
| Tabs (“açık sekme” → «ık») | Router + test ile düzeltilmiş görünüyor; regression riski keyword sırasına bağlı |
| CPU false 99% | `host_metrics` çekirdek-normalize; eski loadavg*100 hatası giderilmiş — izlenmeli |
| Echo / self-talk | Guard + cooldown; edge-tts gecikmesinde sızıntı mümkün |
| efendim | Strip + prompt; Cursor yine üretebilir → strip zorunlu kalmalı |
| Active run | Recovery + test var; SDK race edge case’leri kalabilir |
| Timeout race | Soft konuşur, hard yalnızca pending — testli |
| Personality / profile memory | Eksik ayrı katman |
| Episodic timeline / retrieval policy | Eksik |
| Cost / budget router | Eksik |
| Formal Fast/Deep entry | Bu denetim sonrası ince wrapper ile formalize |

---

## CURRENT PROBLEMS

1. **Çift yol karmaşası:** `CommandRouter` + `system/macos` legacy heuristics + Cursor — aynı intent üç yerde çözülebilir; latency “prefer_tool” ipucu var ama router kaçırırsa Cursor’a düşer.
2. **Monolit `JarvisCore`:** Orkestrasyon, dil, UI, voice gate, latency, preference aynı sınıfta.
3. **Second Brain eksik:** Tek flat memory; working (session) ContextManager’da, episodic/semantic/profile ayrılmamış; retrieval politikası (recency × importance × relevance) yok.
4. **Persona dağınık:** Iron Man prompt’ları brain dosyasında; config’te `persona: iron_man` ama içerik hardcode.
5. **Güvenlik gerçeği:** `full_autonomy: true`, `auto_approve_dangerous: true`, `full_shell_access: true` — kişisel cihaz OK, “enterprise secure” değil; catastrophic shell block var, Level-3 fiilen otomatik.
6. **Performans hedefi &lt;1s:** Local tool path genelde hızlı; Cursor yolu saniyeler–dakikalar. Fast path kaçırılırsa hedef bozulur.
7. **Streaming / barge-in:** Kullanıcı deneyimi “konuş → bekle → cevap”; gerçek zamanlı kesme sınırlı.
8. **Observability:** request_id yoktu; HUD telemetry kaba; cost yok.
9. **Keyword router kırılganlığı:** TR morfoloji (“açsana”, “açık sekme”) özel case’lerle yamalı; ölçeklenmez.
10. **Config drift:** `workspace` path başka bir jarvis kopyasına işaret edebiliyor; `ai_only` / autonomy bayrakları tehlikeli kombinasyonlar üretiyor.

---

## TECHNICAL DEBT

- Keyword listeleri: `model_router` / `task_router` / `command_router` / `open_target` / `macos` — örtüşme
- `main.py` + `JarvisOS` sorumluluk sınırı bulanık (preference hem main hem tools)
- Embeddings: hashing-trick; gerçek semantic kalitesi sınırlı (bilinçli trade-off)
- Playwright / OCR / MCP: opsiyonel; diagnostics dürüst ama özellik “var gibi” algısı riski
- Test coverage: birim ağırlıklı; uçtan uca ses/Cursor entegrasyonu mock’lu
- Audit log var; structured tracing / correlation id yoktu
- `stream_preview`, `work_updates` bayrakları UX ile tam hizalı değil
- İngilizce plan/automation speech string’leri (TR-only UX ile çelişebilir)

---

## RECOMMENDED ARCHITECTURE

Mevcut klasörlere map (yeniden yazma yok — evrim):

```
main.py                 # KEEP — ince bootstrap + voice loop
core/
  brain_router.py       # NEW (Phase1) — FastBrain vs DeepBrain giriş
  command_router.py     # Fast path NL→tool
  app.py                # JarvisOS facade
  execution_engine.py   # tool + plan + verify
  context_manager.py    # → Working Memory
  planner.py            # multi-step
  latency_stats.py      # + request_id
  event_bus.py          # observability events
brain/
  cursor_brain.py       # DeepBrain implementation
  model_router.py       # cost-aware evolve
  task_router.py        # complexity → timeout / max_iter
  llm_provider.py       # KEEP
memory/
  repository.py         # semantic store
  extractor.py          # + trivial skip + importance
  (future) layers.py    # working/episodic/semantic/profile views
config/
  personality.yaml      # NEW — persona ayrı dosya
  projects.yaml         # KEEP
  loader.py             # wire personality
tools/                  # registry — KEEP expand
security/               # permissions — tighten defaults for non-dev
automation/ + proactive/# background workers — KEEP
voice/                  # barge-in polish
ui/                     # API-first later: REST beside WS
```

**Hedef akış:**

```
request_id
  → BrainRouter.classify
       Fast: health/time/open/tabs/music/prefs → tools (<1s)
       Deep: Cursor agent loop (max_iter, soft/hard timeout, verify)
  → MemoryPipeline (skip trivial; score importance; recall policy)
  → Speak + HUD + LatencyStats(request_id)
```

---

## MISSING COMPONENTS

| Bileşen | Öncelik | Not |
|---------|---------|-----|
| Formal Fast/Deep router API | P0 | ✅ Phase 1 |
| Personality YAML | P0 | ✅ Phase 1 |
| Trivial utterance skip + importance | P0 | ✅ Phase 1 |
| request_id observability | P0 | ✅ Phase 1 |
| Memory layer types (episodic/profile) | P1 | ✅ Phase 2 (`memory/layers.py`) |
| Retrieval scoring (importance×recency×sim) | P1 | Partial — rank + semantic; full formula next |
| Agent max_iterations policy | P1 | ✅ Phase 2 (`max_plan_steps` / timeout / deep_max) |
| Cost / budget router | P2 | ✅ Phase 5 — estimates from config.cost.rates (not invoices) |
| Research/coding allowlists | P1 | ✅ Phase 3 (`agent_profiles` + agent tools) |
| Verify-before-claim | P1 | ✅ Phase 3 (tabs/media/url/git + claim_safe) |
| Background long analyze | P1 | ✅ Phase 3 |
| Streaming TTS / partial reply | P2 | Opt-in `stream_preview` only — not faked |
| Barge-in rafine | P2 | ✅ Phase 3 (TTS + Cursor cancel) |
| External REST API | P2 | ✅ Phase 5 `/api/health|state|command` |
| Dedicated research/coding agent loops | P2 | tools var; loop politikası kısmi |
| PostgreSQL | — | **Yapılmayacak** (SQLite kalsın) |

---

## MEMORY DESIGN

**Mevcut:** `memories(key, content, category, importance, embedding)` + FTS + hashing cosine; `ContextManager` short-term turns; `ConversationMemory` in brain.

**Hedef (SQLite üzerinde, migration minimal):**

| Katman | Map | Saklama |
|--------|-----|---------|
| Working | `core/context_manager` + brain deque | RAM |
| Episodic | `category=episodic` + timestamp | SQLite |
| Semantic | embedding + FTS | SQLite (mevcut) |
| Profile | `category=preference` / `profile`, key=`user_*` | SQLite + config sync |

**Kurallar:**

- Trivial (“tamam”, “anladım”, gürültü) → extract skip
- Preference / name / project → importance 3–5
- Explicit “hatırla” → importance ≥ 3
- Secrets → asla yazma (mevcut)
- Recall: light-mode’da semantic skip (mevcut); importance DESC zaten ORDER BY’da

**Bu faz:** `is_trivial_utterance` + `score_importance` + extract_and_save skip.

---

## AGENT DESIGN

**Mevcut:** Tek Cursor agent; complexity → timeout; planner multi-step tools; auto_continue / background_on_timeout.

**Hedef iki-beyin:**

| Beyin | Ne zaman | Implementasyon |
|-------|----------|----------------|
| FastBrain | health, time, open_app, tabs, music, prefs, weather | `CommandRouter` + `ExecutionEngine` |
| DeepBrain | sohbet, kod, araştırma, belirsiz NL | `JarvisBrain` + model_router |

**Agent loop politikası (sonraki faz):** `max_iterations`, verify-before-claim zorunlu, false success yasak, research vs coding tool whitelist.

**Pain point bağlantıları:** active-run recovery DeepBrain’de kalsın; FastBrain asla Cursor spawn etmesin.

---

## TOOL SYSTEM

**Mevcut güçlü:** `ToolRegistry`, `BaseTool`, permission, audit, verify set, bootstrap ~50+ tool.

**İyileştirme:**

- Fast tool allowlist (latency SLA) ayrı dokümante
- Router confidence / stats-backed prefer_tool (kısmen var)
- Dış API: tools’u HTTP ile expose (sonra)
- Research/coding: mevcut tool’ları agent policy ile grupla (`tools/packages/`)

---

## SECURITY DESIGN

**Mevcut:** PermissionGate, ConfirmationGate, AuditLog, risk patterns (rm -rf /, credentials, force-push), memory secret redact.

**Gerçek config riski:** `full_autonomy` + `auto_approve_dangerous` + `full_shell_access` → Level-3 fiilen onay bypass (audit kalır).

**Öneri:**

1. Dev makinede autonomy açık OK; “safe profile” YAML preset
2. Fast path tools Level ≤1; shell her zaman risk check
3. request_id → audit_logs.details correlation
4. HUD WS localhost — auth ihtiyaç kişisel kullanımda düşük
5. Workspace path doğrulama (yanlış repo’da Cursor çalışmasın)

---

## PERFORMANCE PLAN

| Hedef | Yol |
|-------|-----|
| &lt;1s basit | FastBrain only; health/time/open/tabs/music asla Cursor’a düşmesin |
| Soft ack | `speak_ack` + soft timeout mesajı (efendim yok) |
| Light mode | CPU/RAM/swap → automation/screen pause (mevcut) |
| Latency | LatencyStats + request_id; p75 soft timeout bump (mevcut) |
| Streaming | Phase 2+: Cursor stream → erken TTS cümle sınırı |
| Cost | ucuz model chat; composer action/code; deep sadece deep complexity |

**CPU %99:** `ps %cpu` toplamı / core — doğrulandı; HUD’da “99” görürsen light_mode tetiklenir — eşik ayarı gözden geçirilebilir.

---

## IMPLEMENTATION ROADMAP

### Phase 1 — Foundation (SAFE, 2026-08-14) ✅ uygulandı

1. Bu denetim dokümanı → `docs/JARVIS_SECOND_BRAIN_AUDIT.md`
2. `core/brain_router.py` — Fast vs Deep giriş (`JarvisOS.try_handle_command` + allowlist)
3. Memory trivial skip + importance scoring (`memory/extractor.py`)
4. `config/personality.yaml` + `config/loader.load_personality`
5. `request_id` + `brain_path` on `LatencyStats` / `main.py`
6. Testler: `tests/test_second_brain_phase1.py` (+ regression suite OK)

### Phase 2 — Memory Second Brain (SAFE, 2026-08-14) ✅ uygulandı

1. `memory/layers.py` — profile / preference / episodic / fact / project conventions
2. User profile get/update + `memory.about_user` / `memory.forget` tools
3. Layered `recall_for_prompt` (profile + episodic + semantic) — not full dump
4. Episodic write on significant turns (`ingest_conversation`)
5. Agent loop guards: `max_plan_steps`, `plan_timeout_sec`, `plan_max_retries`, `deep_max_iterations`
6. Lightweight `core/cost_meter.py` (complexity units; Fast=0)
7. Voice: «Ne biliyorsun benim hakkımda?» / «Bunu unut»
8. Testler: `tests/test_second_brain_phase2.py`

### Phase 3 — Agent policy (SAFE, 2026-08-14) ✅ uygulandı

1. Verify-before-claim güçlendirme — `browser.list_tabs` / `media.play` / `open_url` / `git.push|add`; `claim_safe_speech`
2. Research / Coding allowlists — `core/agent_profiles.py` + `agent.research` / `agent.coding_analyze` tools
3. Background long tasks — «projeyi analiz et» → kısa ack + `execute_plan_background` + notify
4. Barge-in — `try_stop_speech` → TTS `flush` + Cursor `_interrupt_inflight`
5. Streaming — **dürüst:** `stream_preview` SDK `iter_text` ile var, varsayılan `false`; fake streaming yok
6. Testler: `tests/test_second_brain_phase3.py`

### Phase 4 — UX / session / observability (SAFE, 2026-08-14) ✅ uygulandı

1. FastBrain latency — tool/meta/legacy path asla Cursor beklemez; `speak_ack` yalnız DeepBrain; deep `wait_ready` 1.2s
2. `core/jarvis_state.py` — active_project / active_task / pending_confirmations / memory_capture
3. «Bu konuşmayı hatırlama» — `memory.session_capture` (oturum boyu ingest skip)
4. Observability — `request_id` + `brain_path` audit_logs.details + latency/cost meter
5. Security — `security_profile()`; DEFAULT `full_autonomy=false` (gate ON); **config.yaml şu an `true`** (kişisel cihaz)
6. Testler: `tests/test_second_brain_phase4.py`

**Bilinçli erteleme (Phase 4 audit “sonraki”):** ~~stream_preview polish, REST API, HUD, real token/$~~ → Phase 5 gap close.

### Phase 5 — Gap close (SAFE, 2026-08-14) ✅ uygulandı

Sıra (her katman testli):

0. **İnsansı Emel** — SSML `<break>`, rate `-10%`, pitch `-4Hz`, cümle bölme, «Bakıyorum.» strip; Yelda last resort
1. **Cost meter** — `config.cost.rates` placeholder USD/1M; `invoice: false`; request_id log
2. **REST** — aiohttp `/api/health` `/api/state` `/api/command` (HUD WS duruyor; core HUD’suz çağrılır)
3. **HUD** — LISTENING / THINKING / WORKING / SPEAKING; daha az animasyon
4. **Streaming** — opt-in `stream_preview` + `iter_text` ilk cümle; yoksa fake TTS yok
5. **MCP** — `jarvis2.mcp.servers` örnek (fake stdio); boş liste ile boot OK
6. **Playwright** — optional; TR dürüst mesaj + `playwright install chromium`
7. **Screen Recording TCC** — probe + System Settings deep link + ses talimatı
8. **Calendar** — bugünkü etkinlik / randevu ekle (AppleScript; izin yoksa dürüst)
9. **GitHub** — `gh` veya `GITHUB_TOKEN`; issue/PR liste (L0), issue aç (L2)
10. **Full autonomy** — FastBrain Cursor’suz; `core/agent_loop.py` think-plan-act-observe-verify; catastrophic block kalır; persona sakin profesyonel

Testler: `tests/test_human_voice.py`, `tests/test_rest_cost.py`, `tests/test_calendar_github.py`, `tests/test_agent_loop.py`

### Phase 6 — Harden (sonraki)

- safe autonomy preset (config profile)
- workspace guard
- regression suite for tabs/echo/efendim/timeout/active-run

**Yapılmayacak:** PostgreSQL migration, full rewrite, wake/HUD/Emel/echo/local tools kaldırma.

---

## Pain points ↔ kod haritası

| Ağrı | Kod | Durum |
|------|-----|--------|
| Timeout race | `brain/cursor_brain.py`, `tests/test_timeout_race.py` | Fixed + tested |
| Echo | `voice/self_listen_guard.py` | Mitigated |
| efendim | `speech_clean` + prompts | Mitigated |
| CPU false 99% | `system/host_metrics.py` | Fixed (normalize) |
| Tabs «ık» | `open_target` + `command_router` + tests | Fixed |
| Active run | `_send_with_active_run_recovery` | Fixed + tested |
| False claim | `verification.py` + `claim_safe_speech` + prompts | Strengthened (Phase 3) |
| Emel TR-only | `main.py` language lock + preference | Done |
| Barge-in «dur» | `try_stop_speech` + flush + `_interrupt_inflight` | Improved (Phase 3) |
| Streaming | `stream_preview` + `iter_text` (opt-in) | Partial — not faked |

---

## SECURITY — autonomy defaults (Phase 4)

| Kaynak | `full_autonomy` | Level-3 confirm |
|--------|-----------------|-----------------|
| `config/loader.py` DEFAULT_JARVIS2 | **false** | Gerekli (`auto_approve_dangerous=false`) |
| `config.yaml` (bu makine) | **true** | Bypass (audit kalır) |

Catastrophic shell (`rm -rf /`, disk erase, …) → her iki profilde **hard block**.  
Güvenli profil: `full_autonomy: false` + `auto_approve_dangerous: false` → HUD/ses «evet/hayır».  
`JarvisOS.security_profile()` runtime dürüst özet verir.

---

*Denetim tamam; Phase 1–4 incremental uygulandı.*
