## Analiz
HealthMonitor sorumlu olacak:
- Sistem bileşenlerinin sağlık durumunu toplama
- Süreç yöneticisi, bağlantı kurtarma, model yönlendirici, vb. alt sistemlerden sağlık verilerini toplama
- Sağlık durumunu uygun aralıklarla kontrol etme
- Sağlık sorunlarını bildirme ve gerekirse otomatik recovery tetikleme
- HUD ve diğer UI bileşenlerine sağlık durumu sağlama

## Problemler
- Şu anda sağlık durumu parçalı ve標準lı bir şekilde izlenmiyor
- Süreç yöneticisi kendi içindeki süreçlerin sağlığını izliyor ancak genel sistem sağlığı için bir birleşme noktası yok
- Bağlantı Kurtarma ve diğer sistemler kendi içerisinde sağlık kontrolleri yapıyor ancak bu bilgiler merkezi bir yerde toplanmıyor
- HUD sağlık durumunu göstermek için farklı kaynaklardan veri toplamak zorunda

## Çözüm
- `core/health_monitor.py` dosyasında `HealthMonitor` sınıfı oluştur
- `HealthMonitor` şu sorumluluğa sahip olacak:
  - Kayıtlı sağlık sağlayıcıları (health providers) koleksiyonu tutma
  - Her sağlayıcıdan periyodik olarak sağlık verisi toplama
  - Sağlık verilerini birleştirerek genel sistem sağlığını hesaplama
  - Sağlık durumunu belirli aralıklarla güncelleme ve interested dinlerciyelerine bildirme
  - Sağlık sağlayıcıları için arayüz tanımlama (basit bir protokol)
  - Sistem bileşenlerini (ProcessManager, ConnectionRecovery, ModelRouter, vb.) sağlık sağlayıcı olarak kaydetme
  - HUD ve diğer UI bileşenleri için sağlık durumu sağlama
- Sağlık sağlayıcı arayüzü: `get_health()` metodu döndüren bir sözlük
  - Örnek: `{"component": "process_manager", "status": "healthy", "details": {"total_processes": 5, "healthy": 5}}`
- HealthMonitor başlangıçta sistem başlangıcında başlatılacak ve arka planda çalışacak
- Güncelleme aralığı yapılandırılabilir (varsayılan 30 saniye)
- Sağlık durumu değiştiğinde bir olay (event) yayınlanacak (mevcut event bus kullanılabilir)

## Riskler
- HealthMonitor kendi başına bir hata noktası oluşturmamalı; sağlayıcıların sağlık kontrolü sırasında bir hata olursa bu sağlayıcı için hata olarak işaretlenmeli ve diğer sağlayıcıların çalışmasını etkilememeli
- Periyodik kontroller çok sık yapılırsa sistem performansını etkileyebilir; aralık cuidadosa seçilmeli
- HealthMonitor 자체가 너무 많은 자원을 소비하지 않아야 함; 가볍게 구현되어야 함

## Yapılacaklar
1. `core/health_monitor.py` dosyasını oluştur
2. `HealthProvider` arayüzünü (basit bir protokol) tanımlama
3. `HealthMonitor` sınıfını uygulama:
   - sağlayıcı kaydı ve kaldırma metodları
   - periyodik toplama işlevi (background thread veya asyncio kullanarak)
   - sağlık verilerini birleştirme mantığı
   - eventi yayınlama (opsiyonel)
4. Sistem bileşenlerini sağlık sağlayıcı olarak kaydetme:
   - ProcessManager (zaten is_healthy özelliği var)
   - ConnectionRecovery (bağlantı durumu ve retry sayısı gibi)
   - ModelRouter (model geçişleri ve hata oranları gibi)
   - ExecutionEngine (araç başarı/g başarısız oranları gibi)
   - ContextManager (oturum durumu)
   - Gerekirse diğer bileşenler
5. HealthMonitor'ı main.py'deki JarvisCore başlangıcında başlatma
6. HealthMonitor'dan sağlık verilerini HUD'a sağlama (mevcut telemetry sistemi üzerinden genişletilebilir)
7. Basit bir test escrever

## Beklenen Etkİ
- Sistem sağlığı merkezi ve standardized şekilde izlenecek
- HUD daha detaylı ve doğru sağlık bilgileri gösterebilecek
- Sağlık sorunları erken tespit edilerek otomatik recovery veya yönetici bildirimi mümkün olacak
- Sistem genelinde sağlık monitoring için Tekil bir nokta sahip olacak

## Onay Bekleniyor
Yukarıdaki planı onaylıyor musunuz? Onaydan sonra kod yazmaya başlayacağım.