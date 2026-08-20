# JARVIS 2.0 — Roadmap

**Kaynak gerçek:** `docs/ARCHITECTURE_AUDIT.md` (2026-08-18)  
**Strateji:** Incremental. Rewrite yok. Faz fail → yeni özellik yok.  
**Ölçüt:** Daha fazla cevap değil; doğrulanmış icra.

Durum değerleri: `Completed` | `In Progress` | `Next` | `Future`

---

# Completed

Önceki fazlarda (2026-08-13 … 08-14) üretilmiş ve hâlâ duran temel. Master spec’in tamamı değil.

| ID | Description | Notes |
|----|-------------|--------|
| C-01 | Soft-init JarvisOS beside JarvisCore | `core/app.py`, `main.py` |
| C-02 | ToolRegistry + BaseTool + bootstrap | `tools/` |
| C-03 | Permission 0–3, ConfirmationGate, AuditLog | `security/` |
| C-04 | SQLite + FTS + hashing embeddings | `memory/` |
| C-05 | Fast vs Deep BrainRouter | `core/brain_router.py` |
| C-06 | CommandRouter NL→tool | keyword; kırılgan |
| C-07 | ExecutionEngine + plan + verify allowlist | retry yalnız plan |
| C-08 | Memory layers convention | profile/episodic/fact |
| C-09 | Agent loop cap + research/coding allowlists | `core/agent_loop.py` |
| C-10 | Automation + file watch + briefing | |
| C-11 | Timeout race / echo / active-run tests | |
| C-12 | REST `/api/health\|state\|command` | localhost |
| C-13 | Cost meter placeholder | rates 0.0 |
| C-14 | Personality YAML | |
| C-15 | Open-target «açık» ≠ «aç» regression tests | |

---

# In Progress

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| P0-AUDIT | Architecture audit + this roadmap | P0 | **In Progress** | — | `ARCHITECTURE_AUDIT.md` + `ROADMAP.md` güncellendi; kod değişmedi |

---

# Next

Phase numaraları master spec (§77) ile hizalı. Her faz: build + `unittest discover` + ilgili manuel kontrol.

## Phase 1 — Stability (P0)

Amaç: `Could not open` / timeout / tool fail kullanıcıya ham yansımasın; Fast path kaçmasın.

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| S-01 | OpenApp resolve + retry + fallback (Spotlight/`/Applications`/bundle) | P0 | Next | — | Bilinen app adları açılır; garbage isimde clarify; stderr developer log |
| S-02 | Kullanıcı hata politikası: `Could not open` konuşulmaz | P0 | Next | S-01 | TTS: ne denendi + sonraki adım; ham EN exception yok |
| S-03 | Tekil tool retry: max 3, exponential backoff, error classify | P0 | Next | — | NETWORK/TIMEOUT/PERMISSION ayrılır; sonsuz retry yok |
| S-04 | `config.yaml` workspace → bu repo; autonomy profili belgelenir | P0 | Next | — | Cursor yanlış klasörde çalışmaz; güvenlik gerçeği README’de |
| S-05 | Open/STT corpus regression (ık, açsana, krom, youtube’dan video) | P0 | Next | S-01 | `test_fast_path` + yeni case’ler yeşil |
| S-06 | Fast miss → kör Cursor azalt: action intent’te clarify veya legacy tool | P0 | Next | S-01 | “aç X” asla sohbet-only success claim etmez |
| S-07 | `except Exception: pass` kritik yollarda log+classify | P1 | Next | — | Sessiz yutma open/brain/memory ingest’te yok |

**Phase 1 çıkış kapısı:** text-mode `Chrome aç`, olmayan app, bozuk STT hedefi, `jarvis status` — hepsi anlamlı Türkçe/İngilizce politika ile (config dil kilidine uygun), unittest yeşil.

## Phase 2 — Core Orchestrator (P0)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| O-01 | JarvisOS’u tek giriş API olarak netleştir (`handle_turn`) | P0 | Next | Phase 1 | main.py yalnızca voice/HUD/boot |
| O-02 | Complexity gate: CHAT/SIMPLE Cursor spawn etmez | P0 | Next | O-01 | “merhaba”, “saat kaç” 0 Cursor call |
| O-03 | request_id tüm audit/tool/log’da | P1 | Next | — | Bir komut uçtan uca izlenir |
| O-04 | DecisionEngine + Router overlap azalt | P1 | Next | O-01 | Aynı intent tek yerde çözülür |

## Phase 3 — Tool System (P1)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| T-01 | Tool sözleşmesi: validate hook + optional rollback | P1 | Next | Phase 2 | fs/git tehlikeli işlerde rollback veya dürüst “yok” |
| T-02 | Terminal pipeline: generate→validate→run→parse→verify | P1 | Next | T-01 | `npm install` yalnız exit 0 ile “başarılı” sayılmaz |
| T-03 | Plugin register iskeleti (`tools/packages`) | P2 | Next | T-01 | Yeni tool core’u değiştirmeden eklenir |
| T-04 | Browser kritik aksiyon confirmation | P1 | Next | — | send/pay/login confirm; open URL L1 |

## Phase 4 — Task Engine (P1)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| K-01 | Task state: PENDING/PLANNING/RUNNING/WAITING/RETRYING/FAILED/COMPLETED/CANCELLED | P1 | Next | Phase 2 | DB migration geriye uyumlu |
| K-02 | Checkpoint resume (kaldığı adım) | P0 | Next | K-01 | Fail sonrası “devam et” baştan başlamaz |
| K-03 | CancellationToken tool/plan | P0 | Next | K-01 | “Dur” çalışan planı durdurur |
| K-04 | Pause / resume / retry API + HUD | P1 | Next | K-03 | |

## Phase 5 — Memory (P1)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| M-01 | Hybrid retrieval policy (semantic × keyword × recency × importance) | P1 | Next | — | Full dump yok; ilgili 3–8 bellek |
| M-02 | Procedural memory (nasıl yapılır) | P2 | Next | M-01 | Tekrarlayan git/test akışı hatırlanır |
| M-03 | Temporal (“dün”) episodic query | P1 | Next | M-01 | “dün kaldığımız yer” boş dönmez veya dürüst “kayıt yok” |
| M-04 | Task lessons after complete | P2 | Next | K-01 | |

---

# Future

## Phase 6 — Model Router (P1)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| R-01 | cheap/fast vs smart vs vision vs fallback | P1 | Future | Phase 2 | Chat ucuz; kod smart; primary down → fallback konuşur |
| R-02 | Local/degraded mode (tools-only) | P1 | Future | R-01 | İnternet yokken Fast tools yaşar |
| R-03 | Structured JSON intent/plan schema validation | P1 | Future | O-01 | LLM çıktısı şemasız execute edilmez |

## Phase 7 — Execution & Verification (P0)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| V-01 | Evidence object her tool call | P0 | Future | T-01 | “Testler geçti” yalnız stdout’a dayanır |
| V-02 | DeepBrain claim_safe (Cursor tool evidence) | P0 | Future | V-01 | Tool’suz “açtım” yasak (prompt + runtime) |
| V-03 | Error recovery engine (classify→strategy) | P1 | Future | S-03 | |
| V-04 | Dry-run HIGH+ | P1 | Future | T-01 | “deployment ne yapar” icrasız plan |

## Phase 8 — UI / Streaming (P1)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| U-01 | Task timeline HUD | P1 | Future | K-01 | Adımlar canlı |
| U-02 | Opt-in streaming (fake yok) | P2 | Future | — | `stream_preview` dürüst |
| U-03 | Approve/Reject/Pause/Cancel/Retry butonları | P1 | Future | K-03 | |

## Phase 9 — Voice (P2)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| VO-01 | Voice katmanı backend’den daha net ayrışır | P2 | Future | O-01 | |
| VO-02 | Wake-word güvenli düşük CPU (opsiyonel) | P2 | Future | — | `require_wake_word` kalite |
| VO-03 | Dil politikası tek kaynak (README vs runtime) | P1 | Future | S-04 | Çelişki yok |

## Phase 10 — Automation (P2)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| A-01 | “Her gün bunu yap” → workflow YAML | P2 | Future | T-03 | Permission üzerinden |
| A-02 | GitHub webhook/watcher | P2 | Future | A-01 | |

## Phase 11 — Security (P0, sürekli)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| X-01 | Safe autonomy preset default | P0 | Future | S-04 | Yeni clone’da L3 confirm açık |
| X-02 | Path/command validation sıkılaştır | P0 | Future | T-01 | |
| X-03 | Audit correlation + arg redaction | P1 | Future | O-03 | |
| X-04 | Progressive autonomy levels 1–4 UI | P2 | Future | X-01 | |

## Phase 12 — Testing (sürekli)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| Q-01 | Chaos: timeout, model down, tool None | P1 | Future | S-03 | Recovery testli |
| Q-02 | E2E text-mode 10 kabul senaryosu | P0 | Future | Phase 1–4 | §81 senaryoları |
| Q-03 | Tool/agent/memory/recovery test ayrımı | P1 | Future | | |

## Phase 13 — Performance (P2)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| F-01 | Independent tools parallel | P2 | Future | T-01 | git status + tree aynı anda |
| F-02 | Context compression | P2 | Future | M-01 | |
| F-03 | Latency budget enforce | P1 | Future | O-02 | SIMPLE p95 hedefi ölçülür |

## Phase 14 — Production (P1)

| ID | Description | Priority | Status | Dependencies | Acceptance Criteria |
|----|-------------|----------|--------|--------------|---------------------|
| PR-01 | Startup diagnostic kullanıcıya dürüst | P1 | Future | C-13 | Browser/voice/MCP warning boot’ta |
| PR-02 | Self-heal: reconnect Cursor, no random file rewrite | P1 | Future | R-02 | |
| PR-03 | Doküman seti: ARCHITECTURE, TOOLS, SECURITY, ERROR_RECOVERY, MODEL_ROUTING, AUTOMATION, TESTING, DEVELOPMENT, DEPLOYMENT | P2 | Future | her faz | |
| PR-04 | Kabul: 10 senaryo uçtan uca | P0 | Future | Q-02 | JARVIS 2.0 “tamam” ancak o zaman |

---

# Yapılmayacak (bilinçli)

- PostgreSQL zorunlu göç
- Tüm sistemin silinip yeniden yazılması
- Voice / HUD / Cursor kaldırma
- Sonsuz agent loop
- Kullanıcıya stack trace
- Tool’suz başarı iddiası
- Background otomasyonun permission bypass etmesi

---

# Öncelik sırası (şimdi)

1. **S-01 … S-06** — open/fail/recovery (Could not open sınıfı)
2. **O-02** — SIMPLE path Cursor’suz
3. **K-02 / K-03** — resume + cancel
4. **V-01 / V-02** — evidence, false claim
5. **X-01** — safe defaults
6. Geri kalan yetenekler (browser agent, workflow, multi-agent)

---

# Faz raporu şablonu (her phase sonu)

```
WHAT CHANGED
WHY
TEST RESULT
NEXT
```

---

*Phase 0 Audit: doküman üretildi. Kod değişikliği onay sonrası Phase 1.*