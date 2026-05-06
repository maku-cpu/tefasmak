# tefasmak

TEFAS (Türkiye Elektronik Fon Alım Satım Platformu) için modern bir Python sarmalayıcısı. Yeni TEFAS sitesinin (Nisan 2026'dan itibaren Next.js'e taşındı) public JSON endpoint'lerine erişir.

```bash
pip install tefasmak
```

```python
from tefasmak import fon_anlik_bilgi, fon_5y_fiyat, fon_portfoy_dagilimi

info = fon_anlik_bilgi("IPB")
print(info["sonFiyat"], "·", info["fonUnvan"])
# 0.846063 · İSTANBUL PORTFÖY BİRİNCİ DEĞİŞKEN FON
```

---

## Neden bu paket?

TEFAS sitesi 2026 Nisan'da baştan aşağı yeniden yazıldı. Site Next.js'e taşındı, eski `/api/DB/BindHistoryInfo` endpoint'i kalıcı olarak kapatıldı, önüne Akamai TSPD bot koruması kondu. Bunun pratik sonucu: yıllardır kullanılan `tefas-crawler` paketi bir gece içinde çalışmaz hale geldi. Aynı şey, TEFAS sayfalarını `requests` veya `BeautifulSoup` ile kazıyan tüm scriptler için geçerli.

Yeni site aslında temiz bir JSON API sunuyor — sayfanın kendisi React tarafında bu API'leri çağırıyor. Sorun bu API'lerin ham HTTP istemcileriyle çağrılamaması: Akamai, `requests`'in TLS fingerprint'ini hemen tanıyıp boş yanıt döndürüyor (200 OK ama body boş). Çözüm, isteklerin TLS handshake'ini gerçek bir Chrome'a benzetmek — bu da [`curl_cffi`](https://github.com/lexiforest/curl_cffi) ile mümkün. `tefasmak` bu işin çoğunu kapatıp arkasında temiz Python fonksiyonları sunuyor.

Kapsadığı endpoint'ler genel: tek fon için günlük fiyat geçmişi (5 yıla kadar), anlık bilgi, portföy kategori dağılımı; tüm fonlar için bulk günlük detay, dönemsel getiriler, portföy büyüklüğü, yönetim ücretleri; ve istatistikler (işlem hacmi, üye stok bakiyeleri). 60'tan fazla portföy kategorisi (hisse, repo, mevduat, kıymetli madenler, eurobond, kira sertifikası, BYF/GYF/GSYF varyasyonları) insan-okur etiketlere normalize edilir.

---

## Hızlı tur

### Tek bir fonun anlık durumunu çek

```python
from tefasmak import fon_anlik_bilgi

info = fon_anlik_bilgi("IPB")
print(f"{info['fonKodu']} · {info['sonFiyat']} TL · günlük {info['gunlukGetiri']}%")
print(f"Kategori: {info['fonKategori']}, sıralama {info['kategoriDerece']}/{info['kategoriFonSay']}")
print(f"Büyüklük: {info['portBuyukluk']:,.0f} TL · {info['yatirimciSayi']:,} yatırımcı")
```

### 5 yıllık geçmiş — getiri grafiği için

```python
from tefasmak import fon_5y_fiyat

seri = fon_5y_fiyat("IPB")  # ~1250 günlük {tarih, fiyat} listesi
ilk, son = seri[0], seri[-1]
toplam_getiri = (son["fiyat"] / ilk["fiyat"] - 1) * 100
print(f"{ilk['tarih']} → {son['tarih']}: %{toplam_getiri:.1f}")
```

### Portföy dağılımı — kısa kodlardan insan-okur etiketlere

TEFAS API'si dağılımı `hs`, `tr`, `vint`, `yyf`, `khau` gibi kısa kodlarla döndürür. `portfoy_dagilimi_normalize` bunları "Hisse Senedi", "Ters Repo", "Altın Katılma Hesabı" gibi etiketlere çevirir ve sıfır olanları eler.

```python
from tefasmak import fon_portfoy_dagilimi, portfoy_dagilimi_normalize

ham = fon_portfoy_dagilimi("IPB")
print(portfoy_dagilimi_normalize(ham))
# {'Hisse Senedi': 34.46,
#  'Ters Repo': 38.3,
#  'Yatırım Fonları Katılma Payları': 16.01,
#  'Vadeli İşlemler Nakit Teminatları': 2.77,
#  'Finansman Bonosu': 3.67,
#  'Girişim Sermayesi YF Katılma Belgesi': 4.19,
#  'Gayrimenkul Yatırım Fonu Katılma Belgesi': 0.56,
#  'TL Vadeli Mevduat': 0.04}
```

### Tüm fonların güncel fiyatı — tek seferde

```python
from tefasmak import fonlar_son_fiyat_bulk

bulk = fonlar_son_fiyat_bulk("YAT")  # yaklaşık 2000 fon, 2 sayfa
print(f"{len(bulk)} fon")
print(bulk["IPB"])  # {'fonKodu': 'IPB', 'fiyat': 0.846063, ...}
```

### Tüm fonların dönemsel getirisi — tek istekte

```python
from tefasmak import fonlar_donemsel_getiri

rows = fonlar_donemsel_getiri()
# her satırda 1 ay, 3 ay, 6 ay, yıl başı, 1 yıl, 3 yıl, 5 yıl getirileri
en_iyi_1y = sorted(rows, key=lambda r: r.get("getiri1y") or 0, reverse=True)[:5]
for r in en_iyi_1y:
    print(f"{r['fonKodu']:6} · {r['fonUnvan'][:60]:<60} · %{r['getiri1y']}")
```

### Uzun tarih aralığı — chunked + paginated + dedupe

TEFAS tek istekte yaklaşık 1 ayla sınırlı bir aralık verir. `_aralik` ile biten fonksiyonlar bunu otomatik 28-gün pencerelere böler, her pencerede sayfalama yapar ve `(fonKodu, tarih)` çiftlerini dedupe eder. Çağrılar arasında rate-limit (TEFAS dakikada 6 istek) otomatik uygulanır.

```python
from tefasmak import fonlar_gunluk_detay_aralik

# 4 aylık çekim — yaklaşık 5 chunk, her birinde 2 sayfa
satirlar = fonlar_gunluk_detay_aralik(
    fon_tipi="YAT",
    bas_tarih="20260101",
    bit_tarih="20260430",
)
print(f"{len(satirlar)} satır")
```

---

## Endpoint kapsamı

**Tek fon**
- `fon_fiyat_gecmisi(kod, periyod)` — günlük fiyat (hafta / 1ay / 3ay / 6ay / 1yıl / 3yıl / 5yıl)
- `fon_5y_fiyat(kod)` — kısayol, 5 yıllık tam geçmiş
- `fon_son_iki_fiyat(kod)` — son iki iş günü ve günlük getiri
- `fon_anlik_bilgi(kod)` — sonFiyat, gunlukGetiri, portBuyukluk, payAdet, kategoriDerece, yatirimciSayi
- `fon_profil_detay(kod, periyod)` — kategori derece + tür ortalama getirisi
- `fon_portfoy_dagilimi(kod, tarih=None)` — portföy kategorileri (kısa kodlar)
- `fon_son_fiyat_ve_getiri(kod)` — fiyat + günlük getiri + tarih üçlüsü

**Bulk / aralık**
- `fonlar_gunluk_detay(...)` — sayfalı, tek tarih veya kısa aralık
- `fonlar_gunluk_detay_hepsi(...)` — otomatik sayfalama
- `fonlar_gunluk_detay_aralik(...)` — chunked uzun aralık + dedupe
- `fonlar_portfoy_dagilimi(...)` ve `fonlar_portfoy_dagilimi_aralik(...)`
- `fonlar_donemsel_getiri(...)` — TÜM fonlar 1a/3a/6a/yb/1y/3y/5y, tek istek
- `fonlar_buyukluk(...)` — portföy büyüklüğü ve pay adedi değişimi
- `fonlar_yonetim_ucretleri(...)` — yönetim ücreti, gider kesintisi
- `fonlar_son_fiyat_bulk(...)` — `{fonKodu: satır}` sözlüğü

**Liste / arama**
- `tum_fonlar(fon_tipi)` — kod, ünvan, kurucu sözlüğü
- `fon_unvan_ara(arama)`
- `fon_grup_listesi()`, `fon_tur_listesi()`, `doviz_listesi()`

**İstatistik**
- `islem_hacmi(...)`, `uye_stok_bakiye(...)`
- `fon_bazli_islem_hacmi()`, `uye_bazli_islem_hacmi()`
- `hafta_listesi()`

**Diğer**
- `duyurular()`
- `fund_returns_export(listing_type, fon_tipi)` — TEFAS Excel export'unun JSON karşılığı

### Fon tipleri

| Kod | |
|---|---|
| `YAT` | Yatırım Fonları (varsayılan) |
| `EMK` | Emeklilik Fonları |
| `BYF` | Borsa Yatırım Fonu (ETF) |
| `GYF` | Gayrimenkul Yatırım Fonu |
| `GSYF` | Girişim Sermayesi Yatırım Fonu |

---

## Kaputun altında

`tefasmak` her POST öncesi paylaşılan bir `curl_cffi.Session` kullanır. Session ilk açıldığında Chrome 131 olarak `https://www.tefas.gov.tr/tr/` adresine bir GET atar — TSPD challenge cookie'leri o anda alınır. Bundan sonra API çağrıları doğrudan POST ile yapılabilir, ilk denemede temiz JSON döner. Önceki nesil `requests` tabanlı çözümlerin gereksindiği "ısıtma turu + 5 retry + boş-yanıt loop'u" ortadan kalkar.

Diğer kararlar:

- **Rate-limit.** TEFAS dakikada yaklaşık 6 istek sınırı uyguluyor; aşılırsa boş 200 dönüyor (bazen 429). `_post`, ardışık çağrılar arasında 8 saniye bekler ve 429 yakalarsa exponential backoff ile 5 kez tekrar dener (Retry-After header'ı varsa onu kullanır).
- **Session TTL.** 10 dakika sonra session yeniden açılır, böylece Akamai tarafından expire edilmiş çerezlerle takılı kalmazsın.
- **Chunking.** TEFAS tek POST'ta yaklaşık 1 aylık aralık verir; daha uzun aralıklar sessizce kırpılır. `_aralik` fonksiyonları aralığı 28 günlük pencerelere böler, sayfalama ve dedupe işini halleder.
- **Sayfa boyutu.** Bulk endpoint'lerin varsayılanı 1000 — yaklaşık 2000 yatırım fonu için iki sayfa yetiyor. Daha küçük sayfa istersen parametre olarak verebilirsin.
- **Fallback.** `curl_cffi` yüklenemediği ortamlarda (örneğin bazı Linux containerları) `requests` üzerine geçilir. `pip install "tefasmak[requests]"` ile bu fallback bağımlılığını çekebilirsin; kod zaten ImportError'a karşı korunaklı.

---

## Hata yönetimi

```python
from tefasmak import (
    fon_anlik_bilgi,
    TefasAPIError,
    TefasRateLimitError,
    TefasInvalidParameterError,
)

try:
    info = fon_anlik_bilgi("IPB")
except TefasRateLimitError:
    # 429 — exponential backoff'un sonunda fırlatılır
    ...
except TefasInvalidParameterError:
    # geçersiz tarih formatı, geçersiz aralık, vs.
    ...
except TefasAPIError:
    # genel TEFAS hatası (boş yanıt loop'u dahil)
    ...
```

`TefasInvalidParameterError` aynı zamanda `ValueError` alt sınıfıdır — eski kodun `except ValueError` blokları aynen çalışmaya devam eder.

---

## Bilinmesi gerekenler

- TEFAS API public; kimlik bilgisi gerektirmez. Yine de aşırı yüklenmemek için rate-limit otomatik uygulanır — yine de uzun çekimler için ilave throttling ekleyebilirsin.
- Bu paket **bağımsız** bir projedir. TEFAS, MKK veya başka bir kurumun resmi bir ürünü değildir. Veri kaynağı: <https://www.tefas.gov.tr>
- Endpoint'ler TEFAS tarafından değiştirilirse paket güncellenmek zorunda kalır. Issue açmaktan çekinmeyin.
- AAK gibi artık TEFAS'ta işlem görmeyen fonlar için bazı endpoint'ler boş `resultList` döndürür — kodun "yok" durumu ile "hata" durumu arasındaki ayrımı yakalayabilmesi için bu davranışa dikkat edin.

---

## Lisans

MIT — bkz. [LICENSE](LICENSE).
