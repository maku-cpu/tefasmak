"""
tefasmak — Türkiye Elektronik Fon Alım Satım Platformu (TEFAS) Python sarmalayıcısı.

Yeni TEFAS sitesinin (Next.js, Nisan 2026+) public JSON endpoint'lerine
erişir. Akamai TSPD bot korumasını `curl_cffi` Chrome TLS impersonation ile
geçer; vanilla `requests` fallback olarak korunur.

Hızlı kullanım:

    from tefasmak import fon_anlik_bilgi, fon_5y_fiyat, fon_portfoy_dagilimi

    info = fon_anlik_bilgi("IPB")
    fiyatlar = fon_5y_fiyat("IPB")
    portfoy = fon_portfoy_dagilimi("IPB")
"""

__version__ = "1.0.0"

from .api import (
    # Hata sınıfları
    TefasAPIError,
    TefasRateLimitError,
    TefasInvalidParameterError,
    # Periyod sabitleri
    PERIYOD_HAFTA,
    PERIYOD_1AY,
    PERIYOD_3AY,
    PERIYOD_6AY,
    PERIYOD_1YIL,
    PERIYOD_3YIL,
    PERIYOD_5YIL,
    # Portföy etiketleri
    PORTFOY_KOD_LABEL,
    portfoy_dagilimi_normalize,
    # Tarih yardımcıları
    yyyymmdd,
    # Tek fon endpoint'leri
    fon_fiyat_gecmisi,
    fon_5y_fiyat,
    fon_son_iki_fiyat,
    fon_anlik_bilgi,
    fon_profil_detay,
    fon_portfoy_dagilimi,
    fon_son_fiyat_ve_getiri,
    # Çoklu / bulk endpoint'ler
    fonlar_gunluk_detay,
    fonlar_gunluk_detay_hepsi,
    fonlar_gunluk_detay_aralik,
    fonlar_portfoy_dagilimi,
    fonlar_portfoy_dagilimi_aralik,
    fonlar_donemsel_getiri,
    fonlar_buyukluk,
    fonlar_yonetim_ucretleri,
    fonlar_son_fiyat_bulk,
    # Liste / arama
    tum_fonlar,
    fon_unvan_ara,
    fon_grup_listesi,
    fon_tur_listesi,
    doviz_listesi,
    # İstatistikler
    islem_hacmi,
    uye_stok_bakiye,
    hafta_listesi,
    fon_bazli_islem_hacmi,
    uye_bazli_islem_hacmi,
    # Duyuru / export
    duyurular,
    fund_returns_export,
)

__all__ = [
    "__version__",
    "TefasAPIError", "TefasRateLimitError", "TefasInvalidParameterError",
    "PERIYOD_HAFTA", "PERIYOD_1AY", "PERIYOD_3AY", "PERIYOD_6AY",
    "PERIYOD_1YIL", "PERIYOD_3YIL", "PERIYOD_5YIL",
    "PORTFOY_KOD_LABEL", "portfoy_dagilimi_normalize", "yyyymmdd",
    "fon_fiyat_gecmisi", "fon_5y_fiyat", "fon_son_iki_fiyat",
    "fon_anlik_bilgi", "fon_profil_detay", "fon_portfoy_dagilimi",
    "fon_son_fiyat_ve_getiri",
    "fonlar_gunluk_detay", "fonlar_gunluk_detay_hepsi", "fonlar_gunluk_detay_aralik",
    "fonlar_portfoy_dagilimi", "fonlar_portfoy_dagilimi_aralik",
    "fonlar_donemsel_getiri", "fonlar_buyukluk", "fonlar_yonetim_ucretleri",
    "fonlar_son_fiyat_bulk",
    "tum_fonlar", "fon_unvan_ara", "fon_grup_listesi", "fon_tur_listesi",
    "doviz_listesi",
    "islem_hacmi", "uye_stok_bakiye", "hafta_listesi",
    "fon_bazli_islem_hacmi", "uye_bazli_islem_hacmi",
    "duyurular", "fund_returns_export",
]
