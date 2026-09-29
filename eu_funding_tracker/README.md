# AB Fon Çağrısı Takibi ve Akademisyen Eşleştirme

Bu araç [EU Funding & Tenders Portal](https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/home)
üzerindeki **açık** ve **yakında açılacak** hibe çağrılarını düzenli olarak tarar. Her çağrıyı
**İstanbul Ticaret Üniversitesi**'nin odak alanları, akademisyenleri ve ekosistem ortakları
(**İTO**, **Teknopark İstanbul**, **BTM — Bilgiyi Ticarileştirme Merkezi**) ile eşleştirir. Sonucu Türkçe bir HTML raporu
olarak GitHub Issue'su açar; GitHub bunu size e-postayla bildirir.

## Dosyalar

| Dosya | Görevi |
|---|---|
| `track.py` | Tarama, eşleştirme, rapor ve e-posta |
| `profile.json` | Üniversitenin odak alanları, ekosistem ortakları ve Türkiye katılım notları (anahtar kelimeler İngilizce) |
| `academics.csv` | Akademisyen listesi: ad, bölüm, e-posta, odak alanı id'leri, kişisel anahtar kelimeler |
| `state.json` | Daha önce raporlanmış çağrılar; aynı çağrı iki kez "yeni" diye gelmez |
| `tests/` | Çevrimdışı test (örnek API yanıtı ile) |
| `../.github/workflows/eu-funding-report.yml` | Haftalık otomatik çalıştırma + rapor issue'su |

## Rapor içeriği

- **Yeni eşleşen çağrılar:** her çağrı için uygunluk puanı, eşleşen odak alanları,
  önerilen akademisyenler (en fazla 5 kişi), rol önerisiyle birlikte ilgili ekosistem ortakları,
  Türkiye katılım notu ve portal bağlantısı.
- **Son başvurusu 30 gün içinde olan eşleşen çağrılar:** bu bölüm her raporda tekrar listelenir.

### Puanlama

- Bir anahtar kelime çağrının başlığında geçerse 3 puan alır. Açıklamada, etiketlerde veya
  anahtar kelimelerde geçerse 1 puan alır.
- Odak alanı puanlarının toplamı en az 3 ise çağrı rapora girer. Bu eşiği `MIN_AREA_SCORE`
  ile değiştirebilirsiniz.
- Akademisyen puanı şöyle hesaplanır: kişisel anahtar kelime puanının 2 katı, artı kişinin
  odak alanlarından en yüksek puanlı olanın puanı.

## Kurulum (bir kez)

1. **Akademisyenleri girin.** `academics.csv` dosyasına her akademisyen için bir satır ekleyin.
2. **İlk raporu hemen alın.** Actions → "AB Fon Çağrı Taraması" → **Run workflow** yolunu izleyin.
   İlk çalıştırmada tüm eşleşen açık çağrılar yeni sayılır, bu yüzden ilk rapor uzun olur.

Workflow her **Çarşamba 09:00'da (İstanbul saati)** çalışır. GitHub yoğunluğa göre birkaç dakika
gecikebilir. Zamanı değiştirmek için workflow dosyasındaki `cron` satırını (UTC) düzenleyin.

## Rapor nasıl ulaşır (şifre gerekmez)

- **GitHub Issue:** Her tarama, raporu repoda yeni bir **Issue** olarak açar ve bir önceki rapor
  issue'sunu kapatır. GitHub, repo sahibine yeni issue'ları hesabında kayıtlı e-posta adresine
  bildirim olarak gönderir. E-posta gelmiyorsa github.com → Settings → Notifications altında
  "Watching" için **Email** seçeneğinin açık olduğunu ve reponun "Watch" edildiğini kontrol edin.
- **Repoda dosya olarak:** Tam rapor `eu_funding_tracker/reports/rapor-YYYY-MM-DD.md` (ve `.html`)
  olarak kaydedilir.
- **Hata olursa:** Tarama başarısız olursa "AB fon taraması başarısız" başlıklı bir issue açılır.

`track.py --email` ile SMTP üzerinden doğrudan e-posta gönderme seçeneği kodda duruyor, ama
workflow bunu kullanmıyor.

## Elle çalıştırma

```bash
pip install -r requirements.txt
python3 track.py                                   # raporu ekrana basar, reports/ içine yazar
python3 track.py --email                           # ayrıca e-postalar (SMTP_* ortam değişkenleri gerekir)
python3 track.py --fixture tests/sample_response.json --no-save   # çevrimdışı deneme
python3 -m unittest discover -s tests
```

## Notlar

- Türkiye katılım notları genel bilgi amaçlıdır. Her çağrının uygunluk koşullarını çağrı
  metninden doğrulayın.
- Portal API'si (`api.tech.ec.europa.eu`) Claude Code bulut ortamının ağ politikasında
  engelli olabilir. GitHub Actions ise bu kısıtlamaya takılmaz.
