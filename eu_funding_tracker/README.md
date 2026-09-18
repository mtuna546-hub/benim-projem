# AB Fonları Takip Ajanı (EU Funding Tracker)

[EU Funding & Tenders Portal](https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/home)
üzerindeki açık çağrıları (calls for proposals) `track.py` ile günlük olarak
kontrol eder; daha önce görülmemiş çağrıları `state.json` ile karşılaştırıp
Türkçe bir özet üretir.

## Nasıl çalışır

- `track.py`, portalın herkese açık SEDIA arama API'sini (`api.tech.ec.europa.eu`)
  kullanır; ayrı bir API anahtarı gerekmez.
- `KEYWORDS` listesindeki anahtar kelimelerle (varsayılan: dijitalleşme / yapay
  zeka / teknoloji odaklı) sadece **status=Open** olan hibe çağrılarını (calls
  for proposals) arar.
- Sonuçları `state.json`'daki daha önce görülen çağrı kimlikleriyle
  karşılaştırır; yeni olanları özet olarak yazdırır.
- `state.json` her çalıştırmada güncellenir ve repoya commit edilmelidir ki
  bir sonraki günün "yeni" tespiti doğru çalışsın.

Takip edilen anahtar kelimeleri değiştirmek için `track.py` içindeki
`KEYWORDS` listesini düzenleyin.

## Elle çalıştırma

```bash
pip install -r requirements.txt
python3 track.py
```

## Günlük otomasyon

Bu ajan, Claude Code Remote üzerinde kurulmuş bir **Routine** (zamanlanmış
tetikleyici) ile her gün otomatik çalışacak şekilde ayarlanmıştır: Routine her
gün yeni bir oturum açar, bu betiği çalıştırır, yeni çağrı varsa `state.json`
değişikliğini commit+push eder ve özeti oturumun son mesajı olarak bırakır —
bu da e-posta bildirimi olarak size ulaşır.

### Önemli: Ağ erişimi

`api.tech.ec.europa.eu` adresine giden trafik, bu ortamın ağ politikası
tarafından engellenmişse betik hata verir (özet bunu açıkça belirtir).
Routine'in gerçekten çalışabilmesi için bu ortamın (environment) ağ
politikasının `ec.europa.eu` / `api.tech.ec.europa.eu` adresine (veya genel
internet erişimine) izin verecek şekilde güncellenmesi gerekir. Bkz.
[Claude Code on the web dokümantasyonu](https://code.claude.com/docs/en/claude-code-on-the-web).
