# tefasmak

[![PyPI](https://img.shields.io/pypi/v/tefasmak.svg)](https://pypi.org/project/tefasmak/)
[![Python](https://img.shields.io/pypi/pyversions/tefasmak.svg)](https://pypi.org/project/tefasmak/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**TEFAS** (Türkiye Elektronik Fon Alım Satım Platformu) için modern Python sarmalayıcısı.

Yeni TEFAS sitesinin (Next.js, Nisan 2026+) public JSON endpoint'lerine erişir.
Akamai TSPD bot korumasını [`curl_cffi`](https://github.com/lexiforest/curl_cffi) ile
Chrome TLS impersonation kullanarak geçer — ilk POST'ta temiz JSON döner, warmup loop yok.

> Eski `tefas-crawler` paketinin kullandığı `/api/DB/BindHistoryInfo` endpoint'i
> TEFAS sitesinin yeniden yazımıyla kalıcı olarak kaldırıldı. `tefasmak` yeni
> endpoint setine modern bir alternatif sunar.

---

## Kurulum

```bash
pip install tefasmak
```

`curl_cffi` yüklenemediği ortamlarda `requests` fallback'i etkinleşir:

```bash
pip install "tefasmak[requests]"
```

---

## Hızlı kullanım

```python
from tefasmak import (
    fon_anlik_bilgi,
    fon_5y_fiyat,
    fon_portfoy_dagilimi,
    portfoy_dagilimi_normalize,
    fonlar_donemsel_getiri,
)

# Tek fon — anlık bilgi
info = fon_anlik_bilgi("IPB")
print(info["sonFiyat"], info["gunlukGetiri"], info["portBuyukluk"])

# 5 yıllık günlük fiyat geçmişi (getiri grafiği için)
fiyatlar = fon_5y_fiyat("IPB")
print(f"{len(fiyatlar)} gün, son: {fiyatlar[-1]['tarih']} = {fiyatlar[-1]['fiyat']}")

# Portföy dağılımı (kısa kod → insan-okurabilir)
ham = fon_portfoy_dagilimi("IPB")
dagilim = portfoy_dagilimi_normalize(ham)
# {'Hisse Senedi': 34.46, 'Ters Repo': 38.3, ...}

# TÜM fonların dönemsel getirisi tek istekte
getiriler = fonlar_donemsel_getiri()  # 1a/3a/6a/yb/1y/3y/5y kolonları dolu
```

### Bulk çekim

```python
from tefasmak import fonlar_son_fiyat_bulk, fonlar_gunluk_detay_aralik

# Tüm fonların güncel fiyatı (~2000 fon, 2 istek)
bulk = fonlar_son_fiyat_bulk("YAT")
print(len(bulk), "fon")

# Tarih aralığı (chunked + paginated + dedupe + rate-limit otomatik)
df = fonlar_gunluk_detay_aralik(
    fon_tipi="YAT",
    bas_tarih="20260101",
    bit_tarih="20260430",
)
```

---

## Endpoint kapsamı

| Kategori | Fonksiyon | Açıklama |
|---|---|---|
| **Tek fon** | `fon_fiyat_gecmisi(kod, periyod)` | Günlük fiyat geçmişi (hafta/1ay/.../5yıl) |
| | `fon_5y_fiyat(kod)` | 5 yıllık geçmiş — getiri grafiği için ideal |
| | `fon_anlik_bilgi(kod)` | sonFiyat, gunlukGetiri, portBuyukluk, kategoriDerece |
| | `fon_profil_detay(kod, periyod)` | Kategori derecesi + tür ortalama getirisi |
| | `fon_portfoy_dagilimi(kod, tarih)` | Portföy kategorileri (hs/tr/yyf/...) |
| **Bulk** | `fonlar_gunluk_detay_hepsi(...)` | Tüm fonlar tek tarih için, sayfalı |
| | `fonlar_gunluk_detay_aralik(...)` | Uzun tarih aralığı, chunked + paginated |
| | `fonlar_portfoy_dagilimi_aralik(...)` | Portföy dağılımı geçmişi |
| | `fonlar_donemsel_getiri(...)` | Tüm fonlar 1a/3a/6a/yb/1y/3y/5y, **tek istek** |
| | `fonlar_buyukluk(...)` | Portföy büyüklüğü, pay adedi değişimi |
| | `fonlar_yonetim_ucretleri(...)` | Yönetim ücreti, gider kesintisi |
| **Liste / arama** | `tum_fonlar(fon_tipi)` | Tüm fonlar: kod, ünvan, kurucu |
| | `fon_unvan_ara(arama)` | Kod/ünvan araması |
| | `fon_grup_listesi()`, `fon_tur_listesi()` | Sözlük |
| **İstatistik** | `islem_hacmi(...)` | Toplam işlem hacmi raporu |
| | `uye_stok_bakiye(...)` | Üye stok bakiyeleri |
| | `fon_bazli_islem_hacmi()`, `uye_bazli_islem_hacmi()` | Detaylı işlem raporları |
| **Diğer** | `duyurular()` | TEFAS duyuruları |
| | `fund_returns_export(...)` | Excel export'un JSON karşılığı |

### Fon tipleri

| Kod | Açıklama |
|---|---|
| `YAT` | Yatırım Fonları (varsayılan) |
| `EMK` | Emeklilik Fonları |
| `BYF` | Borsa Yatırım Fonu (ETF) |
| `GYF` | Gayrimenkul Yatırım Fonu |
| `GSYF` | Girişim Sermayesi Yatırım Fonu |

---

## Özellikler

- **TLS impersonation** — `curl_cffi` Chrome 131 fingerprint ile Akamai TSPD bypass; ilk POST'tan temiz JSON
- **Otomatik rate-limit** — TEFAS 6 req/dk sınırı için ardışık çağrılar arası 8sn bekleme
- **Chunked tarih çekimi** — TEFAS'ın 1 ay sınırını aşan aralıklar için 28-gün pencerelere otomatik bölme + dedupe
- **Sayfalı bulk** — 1000'lik sayfa boyutu (2000 fon = 2 istek)
- **Session cache** — 10 dk TTL ile cookie tazeleme
- **Backoff + retry** — 429/boş yanıt için exponential backoff, max 5 deneme
- **Custom exceptions** — `TefasAPIError`, `TefasRateLimitError`, `TefasInvalidParameterError`

---

## Portföy dağılımı kısa kodları

`fon_portfoy_dagilimi` ham sözlükte kısa kodlar döner (`hs`, `tr`, `yyf`, `vint` vb.).
İnsan-okurabilir karşılıkları için `portfoy_dagilimi_normalize` veya `PORTFOY_KOD_LABEL`:

```python
from tefasmak import PORTFOY_KOD_LABEL, fon_portfoy_dagilimi, portfoy_dagilimi_normalize

ham = fon_portfoy_dagilimi("IPB")
print(portfoy_dagilimi_normalize(ham))
# {'Hisse Senedi': 34.46, 'Ters Repo': 38.3, 'Yatırım Fonları Katılma Payları': 16.01, ...}

print(PORTFOY_KOD_LABEL["khau"])  # 'Altın Katılma Hesabı'
```

60+ kategori desteklenir (hisse, repo, mevduat, kıymetli madenler, eurobond, kira sertifikası, BYF, GYF, GSYF vb.).

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
    info = fon_anlik_bilgi("XYZ")
except TefasRateLimitError:
    # 429 — exponential backoff bittikten sonra fırlatılır
    ...
except TefasInvalidParameterError:
    # Tarih formatı vb. geçersiz
    ...
except TefasAPIError:
    # Genel TEFAS hatası
    ...
```

`TefasInvalidParameterError` aynı zamanda `ValueError` alt sınıfıdır — eski kod
`except ValueError` ile yakalamaya devam edebilir.

---

## Notlar

- TEFAS API public'tir, kimlik bilgisi gerektirmez.
- Site'nin servis politikalarına saygı gösterin (rate-limit otomatik uygulanır).
- Veri kaynağı: <https://www.tefas.gov.tr> — bağımsız bir projedir, TEFAS/MKK ile resmi bağı yoktur.

---

## Lisans

MIT — bkz. [LICENSE](LICENSE).
