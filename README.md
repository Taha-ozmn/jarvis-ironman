# J.A.R.V.I.S. — Iron Man Voice Assistant

Tony Stark'ın yapay zeka asistanı **JARVIS**'i Cursor API ile sıfırdan inşa edilmiş, tam sesli konuşma destekli macOS asistanı.

## Özellikler

- **Sesli konuşma** — "Jarvis" uyandırma kelimesi ile sürekli dinleme
- **Türkçe ses** — `tr-TR-EmelNeural` (edge-tts), SSML durakları, sakin profesyonel tempo
- **Cursor API beyin** — Cursor SDK ile çok turlu akıllı sohbet (DeepBrain)
- **Iron Man HUD** — komuta merkezi; durum: Listening / Thinking / Working / Speaking
- **macOS kontrolü** — uygulama, takvim, mail, ekran, GitHub (`gh` / `GITHUB_TOKEN`)
- **Türkçe-only UX** — yanıtlar Türkçe; İngilizce TTS kapalı

## Gereksinimler

- macOS (ses için `afplay` kullanır)
- Python 3.10+ (önerilen: `/usr/local/bin/python3.11`)
- Mikrofon erişimi
- [Cursor API Key](https://cursor.com/dashboard/integrations)

## Kurulum

```bash
cd ~/jarvis-ironman
chmod +x start.sh
./start.sh
```

İlk çalıştırmada `.env` dosyası oluşur. API anahtarınızı ekleyin:

```bash
nano .env
# CURSOR_API_KEY=cursor_xxxxxxxx
```

## Kullanım

```bash
# Sesli mod (varsayılan)
./start.sh

# Metin modu (test için)
./start.sh --text

# HUD olmadan
./start.sh --no-ui
```

### Sesli komutlar

| Komut | Örnek |
|-------|-------|
| Uyandırma | "Jarvis", "Hey Jarvis" |
| Uygulama aç | "Jarvis aç Spotify" |
| Saat | "Jarvis saat kaç" |
| Genel soru | "Jarvis bugün hava nasıl" |
| Kod görevi | "Jarvis bu projede bug bul" |

## Mimari

```
jarvis-ironman/
├── main.py              # Ana döngü (+ JARVIS 2.0 soft-init)
├── brain/
│   └── cursor_brain.py  # Cursor SDK + JARVIS kişiliği
├── voice/
│   ├── listener.py      # Mikrofon + STT
│   └── speaker.py       # edge-tts British voice
├── system/
│   └── macos.py         # macOS hızlı eylemler
├── ui/
│   ├── index.html       # Iron Man HUD
│   └── server.py        # WebSocket sunucu
├── core/                # JARVIS 2.0 event bus, tasks, execution
├── memory/              # SQLite bellek / migrations
├── security/            # Permission 0–3, audit
├── tools/               # Tool registry
├── docs/JARVIS_2_ARCHITECTURE.md
└── config.yaml          # Ayarlar (jarvis2 feature flags)
```

### JARVIS 2.0 (Personal AI OS)

Kalıcı SQLite bellek (FTS5), görevler, proje registry, git/dev tool’ları, izin seviyeleri (0–3), HUD onay, otomasyon (zaman + Downloads dosya izleme), planner, yedekleme, opsiyonel Playwright.

Mevcut ses / HUD / Cursor / wake word yolu korunur. Detay: `docs/JARVIS_2_ARCHITECTURE.md`.

```bash
# Birim + entegrasyon testleri
.venv/bin/python -m unittest discover -s tests -v

# Emel ses örneği (MP3 üretir)
.venv/bin/python scripts/test_voice.py --play

# REST (HUD açıkken, localhost)
# GET  http://127.0.0.1:8765/api/health
# GET  http://127.0.0.1:8765/api/state
# POST http://127.0.0.1:8765/api/command  {"text":"saat kaç"}

# Opsiyonel browser otomasyonu (click/fill)
# macOS 12 (Monterey): requirements-optional.txt Playwright <1.62 pinler (1.62+ chromium yok).
# Chromium yoksa boot bozulmaz; browser.open_url çalışır. Ayrıntı: docs/MACOS_PERMISSIONS.md
pip install -r requirements-optional.txt && playwright install chromium
```

GitHub: `.env` içine `GITHUB_TOKEN=` veya `gh auth login` (token commit edilmez).
MCP: `config.yaml` → `jarvis2.mcp.servers` (boş liste ile boot olur).
Ekran Kaydı: `docs/MACOS_PERMISSIONS.md`.

`config.yaml` → `jarvis2.enabled: false` ile v2 çekirdeği kapatılabilir.

Örnek komutlar: «Jarvis status», «sistem durumunu kontrol et», «Jettel üzerinde çalış», «plan and organize», «İndirilenlere PDF gelince söyle …», «yedekle», «Jarvis dur».
## Ses ayarları

`config.yaml` → `voice:` (Türkçe-only, varsayılan Emel):

```yaml
voice:
  turkish_voice: tr-TR-EmelNeural
  rate: -10%
  pitch: -4Hz
  ssml: true
```

Örnek cümle: `.venv/bin/python scripts/test_voice.py --out /tmp/jarvis_emel.mp3 && afplay /tmp/jarvis_emel.mp3`

Yelda (`say -v Yelda`) yalnızca Emel denemeleri bittikten sonra yedek.

## Sorun giderme

**Mikrofon çalışmıyor:** Sistem Ayarları → Gizlilik → Mikrofon → Terminal/Python izni verin.

**PyAudio hatası:**
```bash
brew install portaudio
pip install pyaudio
```

**Cursor API hatası:** `.env` dosyasındaki `CURSOR_API_KEY` değerini kontrol edin.

## Lisans

MIT — Kişisel kullanım için özgürce kullanın.
