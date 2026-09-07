# J.A.R.V.I.S. — Iron Man Voice Assistant

Tony Stark'ın yapay zeka asistanı **JARVIS**'i Cursor API ile sıfırdan inşa edilmiş, tam sesli konuşma destekli macOS asistanı.

## Özellikler

- **Sesli konuşma** — "Jarvis" uyandırma kelimesi ile sürekli dinleme
- **Türkçe giriş, İngilizce JARVIS yanıtı** — Türkçe STT, `en-GB-RyanNeural` TTS
- **Cursor API beyin** — Cursor SDK ile çok turlu akıllı sohbet (DeepBrain)
- **Iron Man HUD** — komuta merkezi; Listening / Thinking / Working / Speaking ve neural-core durumu
- **macOS kontrolü** — uygulama, takvim, mail, ekran, GitHub (`gh` / `GITHUB_TOKEN`)
- **Tam otonom çalışma** — planlama, araç yürütme, doğrulama, bellek ve 7/24 watchdog

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

### iPhone’dan izleme ve kontrol

JARVIS çalışırken Mac’te aşağıdaki bağlantıyı açın:

```text
http://127.0.0.1:8765/connect
```

Sayfadaki özel HTTPS bağlantısını iPhone’da açın. Bağlantı token içerir; bu
adresi paylaşmayın. Token yalnızca JARVIS süreci çalıştığı sürece geçerlidir ve
launchd yeniden başlatıldığında yeni bağlantı `/connect` sayfasından alınır.
iPhone’da ilk kez mikrofon iznini verin; ardından mobil panel sürekli dinleme,
metin komutu, STT, TTS, thinking trace, durum, ekran özeti ve onay akışlarını
kullanabilir.

Panel komutları ana JARVIS kuyruğuna girer. REST kullanan istemciler aynı token’ı
`X-Jarvis-Pairing-Token` başlığında göndermelidir. Eşleşmemiş istemciler komut,
mikrofon, TTS ve durum API’lerine erişemez.

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

### Tam JARVIS çalışma modu

Uzun bir kodlama veya araştırma görevi başladığında JARVIS bir kez kabul
bildirimi verir, en fazla üç seyrek ilerleme güncellemesi gönderir ve görevi
arka planda tamamlar. Sürekli "tekrar deneyeyim mi?" sorusu üretmez. Başarısız
adım checkpoint'e yazılır; `devam et` komutu kaldığı adımdan devam eder.

Cursor bağlantısı yoksa yerel macOS araçları, SQLite belleği ve otomasyon
motoru çalışmaya devam eder. Deep coding görevleri için dürüstçe bağlantı
durumu bildirilir; araç kanıtı olmadan başarı söylenmez.

JARVIS'in kendini geliştirmesi sınırsız kaynak kodu değişikliği değildir.
Hatalardan sınırlı bir iyileştirme önerisi oluşturur, izole git worktree'sinde
test eder ve ana çalışma alanına uygulanmadan önce Taha'nın onayını ister.

7/24 servis kurulumu için `docs/MACOS_PERMISSIONS.md` içindeki launchd
adımlarını kullanın. Bu çalışma alanındaki etkin profil `jarvis2.autonomy_profile:
full` değeridir: JARVIS görevleri onay beklemeden planlar, çalıştırır ve doğrular.
Yıkıcı shell kalıpları yine de güvenlik katmanında sert olarak engellenir.
Güvenli varsayılanlara dönmek için profili `safe` yapın.
## Ses ayarları

`config.yaml` → `voice:` (Türkçe giriş, İngilizce yanıt, varsayılan Ryan):

```yaml
voice:
  turkish_voice: tr-TR-EmelNeural
  listen_languages:
    - tr-TR
    - en-US
  rate: -10%
  pitch: -4Hz
  ssml: true
```

Örnek cümle: `.venv/bin/python scripts/test_voice.py --out /tmp/jarvis_emel.mp3 && afplay /tmp/jarvis_emel.mp3`

Yelda (`say -v Yelda`) yalnızca Emel denemeleri bittikten sonra yedek.

Native mikrofon, aynı kaydı Türkçe ve İngilizce STT ile değerlendirir; bu yüzden
“ekranımı gör”, “open Chrome” ve Türkçe-İngilizce karışık komutlar desteklenir.

### Yerel ses kimliği

Ses kimliği doğrulaması hız için varsayılan olarak kapalıdır
(`voice_identity.enabled: false`). Bu durumda mikrofon kaydı doğrudan STT'ye
gider ve profil kontrolü komut akışını yavaşlatmaz. Yalnızca isterseniz
`voice_identity.enabled: true` yaparak yerel doğrulamayı etkinleştirebilirsiniz;
profil yokken sesli komut çalıştırılmaz:

```bash
.venv/bin/python main.py --enroll-voice
```

JARVIS dört kısa cümle okutacak ve yalnızca embedding profilini
`data/voice_profile.json` içinde, kullanıcıya özel `0600` izinleriyle saklayacak;
ham kayıtları saklamayacak. Profil oluşturulduktan sonra film, müzik, başka
kişiler ve JARVIS'in kendi sesi komut kuyruğuna alınmaz. Bu katman biyometrik
doğrulamadır; kusursuz kimlik garantisi değildir. Yanlış ret olursa enrollment'ı
sessiz bir ortamda tekrarlayın. Browser mikrofonu, doğrulanamadığı için bu
modda sesli komut olarak kabul edilmez; native macOS mikrofon kullanılır.

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
