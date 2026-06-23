# J.A.R.V.I.S. — Iron Man Voice Assistant

Tony Stark'ın yapay zeka asistanı **JARVIS**'i Cursor API ile sıfırdan inşa edilmiş, tam sesli konuşma destekli macOS asistanı.

## Özellikler

- **Sesli konuşma** — "Jarvis" uyandırma kelimesi ile sürekli dinleme
- **British accent TTS** — Filmdeki JARVIS gibi İngiliz aksanı (`en-GB-RyanNeural`)
- **Cursor API beyin** — Cursor SDK ile çok turlu akıllı sohbet
- **Iron Man HUD** — Arc Reactor tarzı gerçek zamanlı arayüz
- **macOS kontrolü** — Uygulama açma, ses, saat/tarih
- **Türkçe + İngilizce** — Hem Türkçe hem İngilizce komutları anlar

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
├── main.py              # Ana döngü
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
└── config.yaml          # Ayarlar
```

## Ses ayarları

`config.yaml` veya `.env` ile özelleştirin:

```yaml
jarvis:
  voice: en-GB-RyanNeural
  language: tr-TR
  user_name: sir
```

Alternatif İngiliz sesler: `en-GB-ThomasNeural`, `en-GB-LibbyNeural`

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
