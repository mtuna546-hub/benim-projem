# AB Fon Çağrısı Takibi ve Akademisyen Eşleştirme

Bu araç [EU Funding & Tenders Portal](https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/home)
üzerindeki **açık** ve **yakında açılacak** hibe çağrılarını düzenli olarak tarar. Her çağrıyı
**İstanbul Ticaret Üniversitesi**'nin odak alanları, akademisyenleri ve ekosistem ortakları
(**İTO**, **Teknopark İstanbul**, **BİM**) ile eşleştirir. Sonucu Türkçe bir HTML raporu
olarak e-postayla gönderir.

## Dosyalar

| Dosya | Görevi |
|---|---|
| `track.py` | Tarama, eşleştirme, rapor ve e-posta |
| `profile.json` | Üniversitenin odak alanları, ekosistem ortakları ve Türkiye katılım notları (anahtar kelimeler İngilizce) |
| `academics.csv` | Akademisyen listesi: ad, bölüm, e-posta, odak alanı id'leri, kişisel anahtar kelimeler |
| `state.json` | Daha önce raporlanmış çağrılar; aynı çağrı iki kez "yeni" diye gelmez |
| `tests/` | Çevrimdışı test (örnek API yanıtı ile) |
| `../.github/workflows/eu-funding-report.yml` | Haftalık otomatik çalıştırma + e-posta |

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
   Bu bilgileri üniversitenin AVESİS / YÖK Akademik sayfalarından alabilirsiniz.
2. **Gmail uygulama şifresi alın.** Google Hesabı → Güvenlik → 2 Adımlı Doğrulama → Uygulama
   şifreleri yolunu izleyin ve 16 haneli bir şifre oluşturun.
3. **GitHub Secrets ekleyin.** Depoda Settings → Secrets and variables → Actions yoluna gidin:
   - `SMTP_USER`: gönderen Gmail adresi (örn. `mtuna546@gmail.com`)
   - `SMTP_PASSWORD`: 2. adımda aldığınız uygulama şifresi
   - `REPORT_TO` (isteğe bağlı): alıcı adresi. Varsayılan `mtuna546@gmail.com`'dur.
     Birden fazla alıcıyı virgülle ayırın.
   - `SMTP_HOST` / `SMTP_PORT` (isteğe bağlı): Gmail dışında bir sunucu kullanacaksanız
4. **Workflow'u varsayılan branch'e alın.** GitHub, zamanlanmış workflow'ları yalnızca
   varsayılan branch'ten çalıştırır.
5. **İlk raporu hemen alın.** Actions → "AB Fon Çağrı Taraması" → **Run workflow** yolunu izleyin.
   İlk çalıştırmada tüm eşleşen açık çağrılar yeni sayılır, bu yüzden ilk rapor uzun olur.

Workflow her **Pazartesi 05:47'de (İstanbul saati)** çalışır. Zamanı değiştirmek için
workflow dosyasındaki `cron` satırını düzenleyin. Günlük çalıştırma için `"47 2 * * *"` yazın.

## Elle çalıştırma

```bash
pip install -r requirements.txt
python3 track.py                                   # raporu ekrana basar, reports/ içine yazar
python3 track.py --email                           # ayrıca e-postalar (SMTP_* ortam değişkenleri gerekir)
python3 track.py --fixture tests/sample_response.json --no-save   # çevrimdışı deneme
python3 -m unittest discover -s tests
```

## Notlar

- `profile.json`'daki **BİM** tanımı ve anahtar kelimeleri tahmine dayanır. Kastedilen
  kuruma göre `role` ve `keywords` alanlarını güncelleyin.
- Türkiye katılım notları genel bilgi amaçlıdır. Her çağrının uygunluk koşullarını çağrı
  metninden doğrulayın.
- Portal API'si (`api.tech.ec.europa.eu`) Claude Code bulut ortamının ağ politikasında
  engelli olabilir. GitHub Actions ise bu kısıtlamaya takılmaz.
