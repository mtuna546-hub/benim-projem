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
| `profile.json` | Genel profil: üniversitenin odak alanları, ekosistem ortakları ve Türkiye katılım notları (anahtar kelimeler İngilizce) |
| `profile_muhendislik.json` | Mühendislik Fakültesi profili: bölüm odak alanları ve program ağırlıkları |
| `academics.csv` | Akademisyen listesi: ad, bölüm, e-posta, odak alanı id'leri, kişisel anahtar kelimeler |
| `topic_cache.json` | Her çağrının aksiyon türü, MGA türü ve bütçe bilgisi (14 günde bir yenilenir) |
| `state.json`, `state_muhendislik.json` | Her profilin daha önce raporladığı çağrılar; aynı çağrı iki kez "yeni" diye gelmez |
| `tests/` | Çevrimdışı test (örnek API yanıtı ile) |
| `../.github/workflows/eu-funding-report.yml` | Haftalık otomatik çalıştırma + rapor issue'su |

## Rapor içeriği

Portal bir kez taranır ve sonuçlar iki profile göre ayrı ayrı eşleştirilir:

| Profil | Dosya | Odak |
|---|---|---|
| **Mühendislik Fakültesi** (ana rapor) | `profile_muhendislik.json` | Elektrik-Elektronik, Enerji, Bilgisayar ve Yapay Zeka, Endüstri Mühendisliği. Chips JU, KDT, EIC Pathfinder/Transition, Horizon Cluster 4/5 ve Digital Europe'a ek puan verilir. Cluster 2 (kültür, toplum), Cluster 6 (gıda, biyoekonomi) ve New European Bauhaus'tan puan düşülür. |
| **Genel** (tüm üniversite) | `profile.json` | Ticaret, işletme, finans, hukuk, mimarlık ve tasarım dahil 10 odak alanı |

İki profil ortak kaynakları paylaşır: ekosistem ortakları (İTO, Teknopark İstanbul, BTM), Türkiye katılım
notları (`profile.json`) ve `academics.csv`. Her profilin kendi "görülen çağrılar" dosyası vardır:
`state_muhendislik.json` ve `state.json`.

**Haftalık GitHub Issue'su:** En üstte Mühendislik Fakültesi özeti yer alır. Genel rapor, altında
açılır-kapanır bir bölümdedir.

Her profil için `reports/` klasöründe şu dosyalar üretilir:

- **Kısa özet** (`muhendislik-ozet-*.md`, `ozet-*.md`):
  - en yüksek puanlı 25 yeni çağrı, ayrıntılarıyla;
  - yeni olsun olmasın en uygun 10 açık çağrı;
  - son başvurusu 30 gün içinde olan çağrılar.
- **Tam rapor** (`muhendislik-rapor-*.md/.html`, `rapor-*.md/.html`): eşleşen tüm çağrılar.

Her çağrı için şunlar verilir: uygunluk puanı (varsa program ağırlığıyla birlikte), eşleşen odak
alanları, önerilen akademisyenler, ekosistem ortakları, Türkiye katılım notu ve portal bağlantısı.

**Program ağırlıklarını değiştirmek için:** `profile_muhendislik.json` içindeki `programme_weights`
alanını düzenleyin. Anahtar, çağrı koduna (büyük harfle) uygulanan bir düzenli ifadedir; değer
eklenecek (+) ya da düşülecek (−) puandır.

### Aksiyon türü ve MGA önceliği

Eşleşen her çağrı için portalın `topicDetails` verisinden şu bilgiler çekilir: aksiyon türü (RIA, IA, CSA...),
MGA türü (Lump Sum / Budget-Based), proje başı AB katkısı ve beklenen proje sayısı. Raporlar bu bilgiye göre
üç grupta sıralanır:

1. **Lump sum + RIA/CSA** (EIC hibeleri de bu grupta; %100 fonlu, idari yükü hafif)
2. **Lump sum + IA** (%70; kâr amacı gütmeyen kurumlar için %100)
3. **Diğer:** budget-based, COFUND, PCP, kaskad (FSTP) çağrılar ve bilgisi alınamayanlar

`profile.json` içindeki ayarlar:

- `action_weights`: aksiyon türüne göre eklenen puan (varsayılan RIA/CSA +3, EIC +2, IA +1)
- `mga_weights`: sözleşme türüne göre eklenen puan (varsayılan `HORIZON-AG-LS` +3)
- `only_lump_sum`: `true` yapılırsa raporda yalnızca 1. ve 2. gruptaki çağrılar kalır

Kısa özette "Lump sum öncelikli çağrılar" bölümü ilk 15 çağrıyı gösterir. Tam raporda ise eşleşen tüm
çağrılar bu üç gruba ayrılmış olarak listelenir. İptal edilmiş (`CANCELLED`) çağrılar rapora alınmaz.

### Ortak arama ilanı örneği

Mühendislik raporunun kısa özetinde her hafta **bir** örnek ilan yer alır. Örnek, en uygun çağrı için
portalın **Partner search** bölümüne yapıştırılmaya hazır İngilizce metindir; diğer ilanları bu örneğe
göre uyarlayabilirsiniz. Örnek sayısını profildeki `partner_search_drafts` alanından değiştirebilirsiniz
(mühendislik 1, genel 0).

- **Uzunluk:** Metin en fazla **500 karakterdir** (`DRAFT_MAX_CHARS`). Sınırı aşarsa önce uzmanlık
  listesi kısaltılır, sonra ekosistem cümlesi.
- **Ekosistem cümlesi:** Paydaşların adı yazılmaz. Yerine "Türkiye's leading technology park,
  a leading start-up incubation centre and the chamber of commerce with the widest business network"
  ifadesi kullanılır (`DRAFT_ECOSYSTEM`).
- **Aksiyon türüne göre metin:**
  - RIA: research & WP lead
  - IA: piloting & demonstration
  - CSA: stakeholder engagement & dissemination
- **Çağrı seçimi:**
  - Önce lump sum çağrılar alınır.
  - Son başvurusuna en az 30 gün kalmış olmalıdır (`DRAFT_MIN_DAYS`).
  - Daha önce örneği verilmiş çağrı tekrar seçilmez; bu bilgi state dosyasındaki `drafted` alanında tutulur.
- **Doldurulacak alan:** İletişim kısmı `[name, e-mail]` olarak bırakılır. İlanı EU Login ve kurumun
  PIC numarasıyla siz yayımlarsınız.

### Puanlama

- **Başlık:** Bir anahtar kelime çağrı başlığında geçerse 3 puan alır.
- **Açıklama:** Açıklamada, etiketlerde veya anahtar kelimelerde geçen her kelime 1 puan alır.
  Bu puan her alan için en fazla 3'tür (`BODY_SCORE_CAP`). Böylece uzun ve jargon dolu
  çağrı metinleri puanı şişirmez.
- **Rapora girme koşulu:** Odak alanı puanlarının toplamı en az 6 olmalı (`MIN_AREA_SCORE`)
  **ve** en az bir odak alanı kelimesi başlıkta geçmeli.
- **Akademisyen puanı:** kişisel anahtar kelime puanının 2 katı, artı kişinin odak
  alanlarından en yüksek puanlı olanın puanı.
- **Anahtar kelime seçimi:** "digital", "data", "policy", "management" gibi her AB çağrısında
  geçen genel kelimeler bilerek listede yok. Yerine "digital transformation", "data spaces"
  gibi belirgin ifadeler kullanılıyor.

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
python3 track.py --no-details                      # aksiyon/MGA bilgisini çekmeden hızlı tarama
python3 -m unittest discover -s tests
```

## Notlar

- Türk kuruluşlarının katılamadığı programlar raporlara hiç alınmaz. Şu an listede yalnızca
  Avrupa Savunma Fonu (EDF) var. Liste `profile.json` içindeki `exclude_programmes`
  alanında tutulur; değerler çağrı kodu önekidir. Mühendislik profili de bu listeyi kullanır.
- Portal, son başvuru tarihleri geçmiş bazı eski çağrıları hâlâ "açık" olarak döndürebiliyor.
  Bu çağrılar otomatik olarak elenir; kaç tanesinin elendiği rapor başlığında yazar.
- Türkiye katılım notları genel bilgi amaçlıdır. Her çağrının uygunluk koşullarını çağrı
  metninden doğrulayın.
- Portal API'si (`api.tech.ec.europa.eu`) Claude Code bulut ortamının ağ politikasında
  engelli olabilir. GitHub Actions ise bu kısıtlamaya takılmaz.
