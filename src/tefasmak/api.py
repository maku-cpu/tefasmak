#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TEFAS API Wrapper — Yeni Site (Next.js, Nisan 2026+)
=====================================================
Eski tefas-crawler paketinin kullandığı /api/DB/BindHistoryInfo endpoint'i
TEFAS sitesinin yeniden yazılmasıyla kalıcı kaldırıldı.

Yeni site (https://www.tefas.gov.tr/tr) Next.js + Akamai TSPD.
HTML sayfaları bot korumalı, API endpoint'leri ise sadece /tr ana sayfasına
bir GET (cookie almak için) sonrası Python'dan çağrılabiliyor.

Ortak'taki diğer modüllerle aynı interface stilini takip eder:
  - `fvt_api.py` ile uyumlu fonksiyon adları (gerektiğinde)
  - HTTP isteklerinde session reuse + 10dk TTL ile cookie tazeleme
"""

import time
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple, Callable, Iterator

# curl_cffi: Chrome TLS fingerprint impersonation — Akamai TSPD bypass için
# vanilla requests'ten çok daha sağlam. 0.13+ gerekli.
try:
    from curl_cffi import requests as _http
    _HTTP_BACKEND = "curl_cffi"
except ImportError:
    import requests as _http  # type: ignore
    _HTTP_BACKEND = "requests"

# Network/HTTP istisnaları için ortak yakalama (her iki backend'de de geçerli).
_HTTPError = getattr(_http, "HTTPError", Exception)
_RequestException = getattr(_http, "RequestException", Exception)

BASE_URL = "https://www.tefas.gov.tr"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_IMPERSONATE = "chrome131"

_session = None
_session_init_time: float = 0.0
_SESSION_TTL = 600  # 10 dk

# TEFAS dakikada ~6 istek sınırına sahip → ardışık chunked çağrılar için
# minimum aralık (saniye). _post içinde global olarak uygulanır.
# curl_cffi ile TLS challenge azaldığı için 8sn'ye çekildi (önceki 10sn).
_MIN_REQUEST_INTERVAL = 8.0
_last_request_time: float = 0.0

# Tek POST içinde TEFAS'ın kabul ettiği maksimum tarih aralığı (~1 ay).
# Daha uzun aralıklar sessizce kırpılır → chunking ile parçalanır.
_MAX_DATE_WINDOW_DAYS = 28


# ============================================================
#  CUSTOM EXCEPTIONS
# ============================================================
class TefasAPIError(Exception):
    """TEFAS API'sinden gelen genel hata."""


class TefasRateLimitError(TefasAPIError):
    """TEFAS rate-limit aşıldı (HTTP 429 ya da challenge)."""


class TefasInvalidParameterError(TefasAPIError, ValueError):
    """Geçersiz parametre — eski kod ValueError ile yakalamaya devam edebilir."""


# ============================================================
#  PERİYOD KODLARI
# ============================================================
PERIYOD_HAFTA = 13      # ~5 iş günü
PERIYOD_1AY = 1
PERIYOD_3AY = 3
PERIYOD_6AY = 6
PERIYOD_1YIL = 12
PERIYOD_3YIL = 36
PERIYOD_5YIL = 60       # ⭐ tam tarihçe için


# ============================================================
#  PORTFÖY KISA KOD → İNSAN-OKURABİLİR LABEL
# ============================================================
# dagilimSiraliGetirT response'unun field isimleri kısa.
# AAK örneği üzerinden UI ile birebir eşleştirilen ana kategoriler ve
# TEFAS terminolojisi tahminleri.
PORTFOY_KOD_LABEL: Dict[str, str] = {
    # Kesin (UI ile eşleşti)
    "hs":    "Hisse Senedi",
    "tr":    "Ters Repo",
    "vint":  "Vadeli İşlemler Nakit Teminatları",
    "yyf":   "Yatırım Fonları Katılma Payları",
    "fb":    "Finansman Bonosu",
    "ost":   "Özel Sektör Tahvili",
    "d":     "Diğer",
    # TEFAS terminolojisinden tahmini
    "bb":    "Banka Bonosu",
    "byf":   "Borsa Yatırım Fonu",
    "db":    "Devlet Tahvili",
    "bpp":   "Borsa Para Piyasası",
    "btaa":  "Borçlanma Aracı (Alış)",
    "btas":  "Borçlanma Aracı (Satış)",
    "dt":    "Devlet Tahvili",
    "dot":   "Dövize Endeksli Tahvil",
    "eut":   "Eurobond",
    "fkb":   "Fon Katılma Belgesi",
    "gas":   "Gümüş",
    "gsykb": "Girişim Sermayesi YF Katılma Belgesi",
    "gsyy":  "Girişim Sermayesi YO",
    "gykb":  "Gayrimenkul Yatırım Fonu Katılma Belgesi",
    "gyy":   "Gayrimenkul Yatırım Ortaklığı",
    "hb":    "Hazine Bonosu",
    "kba":   "Kamu Borçlanma Aracı",
    "kh":    "Katılım Hesabı",
    "khau":  "Altın Katılma Hesabı",
    "khd":   "Döviz Katılma Hesabı",
    "khtl":  "TL Katılma Hesabı",
    "kks":   "Kamu Kira Sertifikası",
    "kksd":  "Kamu Kira Sertifikası (Döviz)",
    "kkstl": "Kamu Kira Sertifikası (TL)",
    "kksyd": "Kamu Kira Sertifikası (YD)",
    "km":    "Kıymetli Madenler",
    "kmbyf": "Kıymetli Maden BYF",
    "kmkba": "Kıymetli Maden Kamu Borçlanma",
    "kmkks": "Kıymetli Maden Kamu Kira Sert.",
    "kibd":  "Kira Sertifikası İhracı Borçlanma",
    "osks":  "Özel Sektör Kira Sertifikası",
    "osdb":  "Özel Sektör Dövize Endeksli",
    "r":     "Repo",
    "t":     "Takasbank",
    "tpp":   "Takasbank Para Piyasası",
    "vdm":   "Vadeli Mevduat",
    "vm":    "Vadeli Mevduat",
    "vmau":  "Altın Vadeli Mevduat",
    "vmd":   "Döviz Vadeli Mevduat",
    "vmtl":  "TL Vadeli Mevduat",
    "yba":   "Yabancı Borçlanma Aracı",
    "ybkb":  "Yabancı Kamu Borçlanma",
    "ybosb": "Yabancı Özel Sektör Borçlanma",
    "ybyf":  "Yabancı Borsa Yatırım Fonu",
    "yhs":   "Yabancı Hisse Senedi",
    "ymk":   "Yabancı Menkul Kıymet",
    "oksyd": "Özel Sektör Kira Sert. (YD)",
}


# ============================================================
#  SESSION YÖNETİMİ
# ============================================================
def _get_session():
    global _session, _session_init_time
    now = time.time()
    if _session is None or now - _session_init_time > _SESSION_TTL:
        if _HTTP_BACKEND == "curl_cffi":
            s = _http.Session(impersonate=_IMPERSONATE)
        else:
            s = _http.Session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/tr/",
            "Content-Type": "application/json",
            "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        })
        nav_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        }
        # Cookie warmup. curl_cffi'nin TLS fingerprint'i sayesinde tek GET yetiyor;
        # vanilla requests fallback'inde Akamai TSPD challenge için ikinci sayfa da gerekli.
        try:
            s.get(f"{BASE_URL}/tr/", timeout=15, headers=nav_headers)
            if _HTTP_BACKEND != "curl_cffi":
                s.get(
                    f"{BASE_URL}/tr/FonAnaliz/FonKarsilastirma.aspx",
                    timeout=15,
                    headers={**nav_headers, "Sec-Fetch-Site": "same-origin",
                             "Referer": f"{BASE_URL}/tr/"},
                )
        except Exception:
            pass
        _session = s
        _session_init_time = now
    return _session


def _wait_for_rate_limit() -> None:
    """Ardışık çağrılar arasında min interval bekle (chunked kullanımda 429 önler)."""
    global _last_request_time
    now = time.time()
    delta = now - _last_request_time
    if 0 < delta < _MIN_REQUEST_INTERVAL and _last_request_time > 0:
        time.sleep(_MIN_REQUEST_INTERVAL - delta)
    _last_request_time = time.time()


def _post(path: str, body: Dict[str, Any], timeout: int = 25,
          max_retry: int = 5, throttle: bool = False) -> Dict[str, Any]:
    """TEFAS'a POST isteği. 429/boş-yanıt durumlarında exponential backoff ile retry.

    throttle=True → çağrı öncesi global min-interval bekleme uygulanır
    (uzun chunked çağrı serileri için). Tek seferlik çağrılar için False.

    Her HTTP isteğinin zaman damgası global olarak tutulur — ardından gelen
    `_wait_for_rate_limit()` çağrıları gerçek istek zamanına göre bekler.
    """
    global _session, _session_init_time, _last_request_time
    if throttle:
        _wait_for_rate_limit()
    s = _get_session()
    url = f"{BASE_URL}{path}"
    last_err: Optional[str] = None
    for attempt in range(max_retry):
        try:
            r = s.post(url, json=body, timeout=timeout)
            _last_request_time = time.time()
        except _RequestException as e:
            last_err = f"network: {e}"
            time.sleep(min(2 ** attempt, 30))
            continue

        if r.status_code == 429:
            # Retry-After header varsa onu, yoksa exponential backoff
            ra = r.headers.get("Retry-After")
            wait = float(ra) if (ra and ra.isdigit()) else min(2 ** attempt * 5, 60)
            if attempt == max_retry - 1:
                raise TefasRateLimitError(
                    f"TEFAS rate-limit aşıldı (429), {max_retry} deneme tükendi"
                )
            time.sleep(wait)
            continue

        try:
            r.raise_for_status()
        except _HTTPError as e:
            if attempt == max_retry - 1:
                raise TefasAPIError(f"HTTP {r.status_code}: {e}") from e
            time.sleep(min(2 ** attempt, 30))
            continue

        # TEFAS bazen ilk POST'ta boş gövde + text/html döndürür (Akamai TSPD challenge).
        # Bu POST cevabıyla birlikte challenge cookie'leri set olur — AYNI session ile
        # ufak bir bekleyişle tekrar denersek geçer. Session'ı silmek cookie'leri kaybeder
        # ve sonsuz döngüye sokar.
        if r.text and "json" in (r.headers.get("content-type") or "").lower():
            return r.json()

        last_err = f"boş yanıt (CT={r.headers.get('content-type')}, LEN={len(r.text)})"
        # Boş yanıt iki sebepten gelebilir:
        # (a) ilk POST'taki TSPD challenge → kısa bekleme yeter
        # (b) rate-limit aşımı (TEFAS 6 req/dk için boş 200 döndürür, 429 değil)
        # → ilk denemede kısa, sonrakilerde ≥10s bekle. Son denemede session refresh.
        wait = 0.6 if attempt == 0 else min(_MIN_REQUEST_INTERVAL + attempt * 2, 25)
        if attempt == max_retry - 2:
            _session = None
            _session_init_time = 0
            s = _get_session()
        time.sleep(wait)

    raise TefasAPIError(f"TEFAS yanıtı alınamadı: {last_err}")


def _bugun_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def _son_isgunu_yyyymmdd() -> str:
    """Hafta sonuysa son Cuma'yı, hafta içiyse bugünü döndür."""
    dt = datetime.now()
    while dt.weekday() >= 5:  # 5=Cumartesi, 6=Pazar
        dt -= timedelta(days=1)
    return dt.strftime("%Y%m%d")


def yyyymmdd(dt) -> str:
    """Tarih input'unu TEFAS YYYYMMDD formatına çevir."""
    if isinstance(dt, str):
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y%m%d"):
            try:
                return datetime.strptime(dt, fmt).strftime("%Y%m%d")
            except ValueError:
                continue
        raise TefasInvalidParameterError(f"Tarih formatı tanınmadı: {dt}")
    return dt.strftime("%Y%m%d")


def _date_windows(bas: str, bit: str,
                  pencere_gun: int = _MAX_DATE_WINDOW_DAYS) -> Iterator[Tuple[str, str]]:
    """[bas, bit] aralığını ≤pencere_gun parçalara böler (YYYYMMDD)."""
    bas_dt = datetime.strptime(bas, "%Y%m%d")
    bit_dt = datetime.strptime(bit, "%Y%m%d")
    if bas_dt > bit_dt:
        raise TefasInvalidParameterError(f"bas_tarih > bit_tarih: {bas} > {bit}")
    cur = bas_dt
    while cur <= bit_dt:
        chunk_end = min(cur + timedelta(days=pencere_gun - 1), bit_dt)
        yield cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")
        cur = chunk_end + timedelta(days=1)


# ============================================================
#  1) GÜNLÜK / TARİHSEL FİYAT — fonFiyatBilgiGetir
# ============================================================
def fon_fiyat_gecmisi(fon_kodu: str, periyod: int = PERIYOD_HAFTA) -> List[Dict[str, Any]]:
    """Bir fonun günlük fiyat geçmişi.

    POST /api/funds/fonFiyatBilgiGetir
    Body: {fonKodu, dil:"TR", periyod}

    Periyod: 13=hafta(~5 gün), 1=1ay, 3=3ay, 6=6ay, 12=1yıl, 36=3yıl, 60=5yıl
    Döner: [{fonKodu, fonUnvan, tarih:"YYYY-MM-DD", fiyat, kategoriDerece, kategoriFonSay}]
    """
    j = _post("/api/funds/fonFiyatBilgiGetir",
              {"fonKodu": fon_kodu.upper(), "dil": "TR", "periyod": periyod})
    return j.get("resultList") or []


def fon_son_iki_fiyat(fon_kodu: str) -> Dict[str, Any]:
    """Son iki iş gününün fiyat & getiri özeti (eski tefas-crawler tarzı)."""
    rows = fon_fiyat_gecmisi(fon_kodu, periyod=PERIYOD_HAFTA)
    if len(rows) < 2:
        return {}
    son, onc = rows[-1], rows[-2]
    sf, of = son["fiyat"], onc["fiyat"]
    return {
        "fon_kodu": fon_kodu.upper(),
        "son_tarih": son["tarih"],
        "son_fiyat": sf,
        "onceki_tarih": onc["tarih"],
        "onceki_fiyat": of,
        "gunluk_getiri": round((sf / of - 1) * 100, 4) if of > 0 else 0,
    }


def fon_5y_fiyat(fon_kodu: str) -> List[Dict[str, Any]]:
    """5 yıllık günlük fiyat geçmişi — getiri grafiği üretmek için."""
    return fon_fiyat_gecmisi(fon_kodu, PERIYOD_5YIL)


# ============================================================
#  2) ANLIK FON BİLGİSİ — fonBilgiGetir
# ============================================================
def fon_anlik_bilgi(fon_kodu: str) -> Optional[Dict[str, Any]]:
    """Tek fonun güncel anlık bilgisi (sonFiyat, gunlukGetiri, portBuyukluk vb.)."""
    j = _post("/api/funds/fonBilgiGetir",
              {"fonKodu": fon_kodu.upper(), "dil": "TR"})
    rl = j.get("resultList") or []
    return rl[0] if rl else None


def fon_profil_detay(fon_kodu: str, periyod: int = PERIYOD_1YIL) -> Optional[Dict[str, Any]]:
    """Kategori derecesi + fon türü ortalama getirisi."""
    j = _post("/api/funds/fonProfilDtyGetir",
              {"fonKodu": fon_kodu.upper(), "dil": "TR", "periyod": periyod})
    rl = j.get("resultList") or []
    return rl[0] if rl else None


# ============================================================
#  3) TARİH ARALIĞI - SAYFALI FON LİSTESİ — fonGnlBlgSiraliGetir
# ============================================================
def fonlar_gunluk_detay(
    fon_tipi: str = "YAT",
    bas_tarih: Optional[str] = None,
    bit_tarih: Optional[str] = None,
    bas_sira: int = 1,
    bit_sira: int = 100,
    fon_turu: Optional[str] = None,
    kurucu: Optional[str] = None,
    arama: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Tarih aralığında tüm fonların günlük detayı (sayfalı).

    POST /api/funds/fonGnlBlgSiraliGetir
    Döner: [{fonKodu, fonUnvan, tarih, fiyat, tedPaySayisi, kisiSayisi,
             portfoyBuyukluk}, ...]

    Tek istekte ~25-100 fon. Pagination için bas_sira/bit_sira.
    BULK günlük fiyat almak için en hızlı yol.
    """
    body = {
        "fonTipi": fon_tipi, "fonKodu": None, "aramaMetni": arama,
        "fonTurKod": fon_turu, "fonGrubu": None, "sfonTurKod": None,
        "basTarih": bas_tarih or _son_isgunu_yyyymmdd(),
        "bitTarih": bit_tarih or _son_isgunu_yyyymmdd(),
        "basSira": bas_sira, "bitSira": bit_sira,
        "fonTurAciklama": None, "dil": "TR", "kurucuKod": kurucu,
    }
    j = _post("/api/funds/fonGnlBlgSiraliGetir", body)
    return j.get("resultList") or []


def fonlar_gunluk_detay_hepsi(fon_tipi: str = "YAT",
                                bas_tarih: Optional[str] = None,
                                bit_tarih: Optional[str] = None,
                                sayfa_boyutu: int = 1000) -> List[Dict[str, Any]]:
    """fonlar_gunluk_detay'ın tüm fonları çeken hali (otomatik sayfalama).

    Sayfalar arası TEFAS rate-limit'ine (6 req/dk) saygılı: ilk sayfa
    anında, sonraki sayfalar arası min ~10sn bekleme uygular.
    """
    sonuc: List[Dict[str, Any]] = []
    sira = 1
    ilk = True
    while True:
        if not ilk:
            _wait_for_rate_limit()
        ilk = False
        chunk = fonlar_gunluk_detay(
            fon_tipi=fon_tipi, bas_tarih=bas_tarih, bit_tarih=bit_tarih,
            bas_sira=sira, bit_sira=sira + sayfa_boyutu - 1,
        )
        if not chunk:
            break
        sonuc.extend(chunk)
        if len(chunk) < sayfa_boyutu:
            break
        sira += sayfa_boyutu
        if sira > 5000:  # safety
            break
    return sonuc


def fonlar_gunluk_detay_aralik(fon_tipi: str = "YAT",
                                 bas_tarih: str = "",
                                 bit_tarih: str = "",
                                 sayfa_boyutu: int = 1000,
                                 fon_kodu: Optional[str] = None,
                                 pencere_gun: int = _MAX_DATE_WINDOW_DAYS,
                                 ) -> List[Dict[str, Any]]:
    """Uzun tarih aralığı için chunked + paginated bulk çekim.

    TEFAS tek istekte ~1 ay sınırı uygular; bu fonksiyon aralığı `pencere_gun`
    parçalara böler, her parçada `fonlar_gunluk_detay` ile sayfalı çeker ve
    (fonKodu, tarih) bazında dedupe eder. Ardışık çağrılar arasında otomatik
    rate-limit beklemesi uygular (TEFAS 6 req/dk).
    """
    if not (bas_tarih and bit_tarih):
        raise TefasInvalidParameterError("bas_tarih ve bit_tarih zorunludur (YYYYMMDD).")
    bas = yyyymmdd(bas_tarih)
    bit = yyyymmdd(bit_tarih)

    seen: set = set()
    sonuc: List[Dict[str, Any]] = []
    for w_bas, w_bit in _date_windows(bas, bit, pencere_gun):
        sira = 1
        while True:
            _wait_for_rate_limit()
            if fon_kodu:
                chunk = fonlar_gunluk_detay(
                    fon_tipi=fon_tipi, bas_tarih=w_bas, bit_tarih=w_bit,
                    bas_sira=sira, bit_sira=sira + sayfa_boyutu - 1,
                    arama=fon_kodu.upper(),
                )
            else:
                chunk = fonlar_gunluk_detay(
                    fon_tipi=fon_tipi, bas_tarih=w_bas, bit_tarih=w_bit,
                    bas_sira=sira, bit_sira=sira + sayfa_boyutu - 1,
                )
            if not chunk:
                break
            for row in chunk:
                key = (row.get("fonKodu"), row.get("tarih"))
                if key in seen:
                    continue
                seen.add(key)
                sonuc.append(row)
            if len(chunk) < sayfa_boyutu:
                break
            sira += sayfa_boyutu
            if sira > 5000:
                break
    return sonuc


# ============================================================
#  4) PORTFÖY DAĞILIMI — dagilimSiraliGetirT  ⭐
# ============================================================
def fon_portfoy_dagilimi(fon_kodu: str, tarih: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Tek fonun portföy dağılımı (kısa kod → yüzde).

    POST /api/funds/dagilimSiraliGetirT

    Döner: {fonKodu, fonUnvan, tarih, hs:%, tr:%, vint:%, yyf:%, fb:%, ost:%, ...}
    Yüzdeler için PORTFOY_KOD_LABEL ile insan-okurabilir karşılığı al.
    """
    t = tarih or _son_isgunu_yyyymmdd()
    body = {
        "fonTipi": "YAT", "fonKodu": None, "aramaMetni": None,
        "fonTurKod": None, "fonGrubu": None, "sfonTurKod": None,
        "basTarih": t, "bitTarih": t,
        "basSira": 1, "bitSira": 1,
        "fonTurAciklama": None, "dil": "TR", "kurucuKod": None,
        "sFonTurKod": "", "fonKod": fon_kodu.upper(),
        "fonGrup": "", "fonUnvanTip": "",
    }
    rl = _post("/api/funds/dagilimSiraliGetirT", body).get("resultList") or []
    return rl[0] if rl else None


def portfoy_dagilimi_normalize(satir: Dict[str, Any]) -> Dict[str, float]:
    """Kısa kod → label → yüzde sözlüğü (sadece null olmayan ve >0 olanlar)."""
    sonuc: Dict[str, float] = {}
    for kod, label in PORTFOY_KOD_LABEL.items():
        v = satir.get(kod)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v > 0:
            sonuc[label] = v
    return sonuc


def fonlar_portfoy_dagilimi(
    fon_tipi: str = "YAT",
    tarih: Optional[str] = None,
    bas_sira: int = 1,
    bit_sira: int = 1000,
) -> List[Dict[str, Any]]:
    """Birden çok fonun portföy dağılımı (sayfalı)."""
    t = tarih or _son_isgunu_yyyymmdd()
    body = {
        "fonTipi": fon_tipi, "fonKodu": None, "aramaMetni": None,
        "fonTurKod": None, "fonGrubu": None, "sfonTurKod": None,
        "basTarih": t, "bitTarih": t,
        "basSira": bas_sira, "bitSira": bit_sira,
        "fonTurAciklama": None, "dil": "TR", "kurucuKod": None,
        "sFonTurKod": "", "fonKod": None, "fonGrup": "", "fonUnvanTip": "",
    }
    return _post("/api/funds/dagilimSiraliGetirT", body).get("resultList") or []


def fonlar_portfoy_dagilimi_aralik(
    fon_tipi: str = "YAT",
    bas_tarih: str = "",
    bit_tarih: str = "",
    sayfa_boyutu: int = 1000,
    fon_kodu: Optional[str] = None,
    pencere_gun: int = _MAX_DATE_WINDOW_DAYS,
) -> List[Dict[str, Any]]:
    """Tarih aralığında portföy dağılımı geçmişi (chunked + paginated).

    TEFAS 1 ay sınırı için aralığı `pencere_gun` parçalara böler ve her
    parçada `dagilimSiraliGetirT`'i sayfalayarak çağırır. Çağrılar arası
    rate-limit otomatik. (fonKodu, tarih) bazında dedupe.
    """
    if not (bas_tarih and bit_tarih):
        raise TefasInvalidParameterError("bas_tarih ve bit_tarih zorunludur (YYYYMMDD).")
    bas = yyyymmdd(bas_tarih)
    bit = yyyymmdd(bit_tarih)

    seen: set = set()
    sonuc: List[Dict[str, Any]] = []
    for w_bas, w_bit in _date_windows(bas, bit, pencere_gun):
        sira = 1
        while True:
            _wait_for_rate_limit()
            body = {
                "fonTipi": fon_tipi, "fonKodu": None, "aramaMetni": None,
                "fonTurKod": None, "fonGrubu": None, "sfonTurKod": None,
                "basTarih": w_bas, "bitTarih": w_bit,
                "basSira": sira, "bitSira": sira + sayfa_boyutu - 1,
                "fonTurAciklama": None, "dil": "TR", "kurucuKod": None,
                "sFonTurKod": "",
                "fonKod": fon_kodu.upper() if fon_kodu else None,
                "fonGrup": "", "fonUnvanTip": "",
            }
            chunk = _post("/api/funds/dagilimSiraliGetirT", body).get("resultList") or []
            if not chunk:
                break
            for row in chunk:
                key = (row.get("fonKodu"), row.get("tarih"))
                if key in seen:
                    continue
                seen.add(key)
                sonuc.append(row)
            if len(chunk) < sayfa_boyutu:
                break
            sira += sayfa_boyutu
            if sira > 5000:
                break
    return sonuc


# ============================================================
#  5) DÖNEMSEL GETİRİLER — fonGetiriBazliBilgiGetir
# ============================================================
def fonlar_donemsel_getiri(fon_tipi: str = "YAT",
                            bas_tarih: Optional[str] = None,
                            bit_tarih: Optional[str] = None) -> List[Dict[str, Any]]:
    """Tüm fonların dönemsel getiri yüzdeleri (TEK İSTEKTE).

    POST /api/funds/fonGetiriBazliBilgiGetir
    bas/bit verilirse: getiriOrani o aralık için döner; verilmezse 1a/3a/6a/yb/1y/3y/5y.
    """
    aralikli = bool(bas_tarih and bit_tarih)
    body = {
        "dil": "TR", "fonTipi": fon_tipi, "kurucuKodu": None,
        "sfonTurKod": None, "fonTurAciklama": None, "islem": 1,
        "fonTurKod": None, "fonGrubu": None,
        "donemGetiri1a": "0" if aralikli else "1",
        "donemGetiri3a": "0" if aralikli else "1",
        "donemGetiri6a": "0" if aralikli else "1",
        "donemGetiri1y": "0" if aralikli else "1",
        "donemGetiriyb": "0" if aralikli else "1",
        "donemGetiri3y": "0" if aralikli else "1",
        "donemGetiri5y": "0" if aralikli else "1",
        "basTarih": bas_tarih, "bitTarih": bit_tarih,
        "calismaTipi": 1 if aralikli else 2,
        "getiriOrani": "1",
    }
    return _post("/api/funds/fonGetiriBazliBilgiGetir", body).get("resultList") or []


# ============================================================
#  6) BÜYÜKLÜK / YÖNETİM ÜCRETİ
# ============================================================
def fonlar_buyukluk(fon_tipi: str = "YAT", bas_tarih: str = "", bit_tarih: str = "") -> List[Dict[str, Any]]:
    """Portföy büyüklüğü ve pay adedi değişimi."""
    body = {
        "dil": "TR", "fonTipi": fon_tipi, "islem": 1,
        "kurucuKodu": None, "sfonTurKod": None, "fonTurKod": None,
        "fonGrubu": None, "fonTurAciklama": None,
        "basTarih": bas_tarih or _son_isgunu_yyyymmdd(),
        "bitTarih": bit_tarih or _son_isgunu_yyyymmdd(),
        "calismaTipi": 1,
    }
    return _post("/api/funds/fonBuyuklukBazliBilgiGetir", body).get("resultList") or []


def fonlar_yonetim_ucretleri(fon_tipi: str = "YAT", bas_tarih: str = "", bit_tarih: str = "") -> List[Dict[str, Any]]:
    """Yönetim ücreti ve toplam gider kesintisi."""
    body = {
        "dil": "TR", "fonTipi": fon_tipi, "islem": 1,
        "kurucuKodu": None, "sfonTurKod": None, "fonTurKod": None,
        "fonGrubu": None, "fonTurAciklama": None,
        "basTarih": bas_tarih or _son_isgunu_yyyymmdd(),
        "bitTarih": bit_tarih or _son_isgunu_yyyymmdd(),
        "calismaTipi": 1,
    }
    return _post("/api/funds/fonYonetimBazliBilgiGetir", body).get("resultList") or []


# ============================================================
#  7) ARAMA / SÖZLÜK
# ============================================================
def fon_unvan_ara(arama: str = "") -> List[Dict[str, Any]]:
    """Fon kodu/ünvanından arama."""
    return _post("/api/funds/fonUnvanAra",
                 {"aramaMetni": arama} if arama else {}).get("resultList") or []


def fon_grup_listesi() -> List[Dict[str, Any]]:
    return _post("/api/funds/fonGrupGetir", {}).get("resultList") or []


def fon_tur_listesi() -> List[Dict[str, Any]]:
    return _post("/api/funds/fonTurGetir", {}).get("resultList") or []


def doviz_listesi() -> List[Dict[str, Any]]:
    return _post("/api/statistics/tefas/getFplDovizList/v2", {}).get("data") or []


def tum_fonlar(fon_tipi: str = "YAT") -> List[Dict[str, Any]]:
    """Tüm fonların kod/ünvan/kurucu listesi."""
    return _post("/api/statistics/tefas/getFplFonList",
                 {"fonTipi": fon_tipi}).get("data") or []


# ============================================================
#  8) İSTATİSTİKLER
# ============================================================
def islem_hacmi(bas_yil: str = "", bas_ay: str = "", bit_yil: str = "", bit_ay: str = "",
                para_birimi: str = "") -> List[Dict[str, Any]]:
    """Toplam işlem hacmi raporu.

    POST /api/statistics/tefas/getFplToplamIslemHacmi
    """
    body = {
        "basYil": bas_yil or str(datetime.now().year),
        "basAy": bas_ay, "basHafta": "",
        "bitYil": bit_yil or str(datetime.now().year),
        "bitAy": bit_ay, "bitHafta": "",
        "paraBirimi": para_birimi, "dil": "TR",
    }
    return _post("/api/statistics/tefas/getFplToplamIslemHacmi", body).get("data") or []


def uye_stok_bakiye(yil: str = "", ay: str = "", para_birimi: str = "TL") -> List[Dict[str, Any]]:
    """Üye stok bakiyeleri raporu.

    POST /api/statistics/tefas/getFplMkkStokBakiye
    """
    body = {
        "yil": yil or str(datetime.now().year),
        "ay": ay or f"{datetime.now().month:02d}",
        "fonTuru": "", "uye": "", "paraBirimi": para_birimi, "dil": "TR",
    }
    return _post("/api/statistics/tefas/getFplMkkStokBakiye", body).get("data") or []


def hafta_listesi() -> List[Dict[str, Any]]:
    return _post("/api/statistics/tefas/getFplHaftaList", {}).get("data") or []


def fon_bazli_islem_hacmi() -> List[Dict[str, Any]]:
    return _post("/api/statistics/tefas/getFplFonBazliIslemHacmi", {}).get("data") or []


def uye_bazli_islem_hacmi() -> List[Dict[str, Any]]:
    return _post("/api/statistics/tefas/getFplUyeBazliIslemHacmi", {}).get("data") or []


# ============================================================
#  9) DUYURULAR / EXPORT
# ============================================================
def duyurular() -> List[Dict[str, Any]]:
    return _post("/api/announcements/fonTefasDuyuruGetir", {}).get("data") or []


def fund_returns_export(listing_type: str = "return", fon_tipi: str = "YAT") -> List[Dict[str, Any]]:
    """Excel export'un JSON karşılığı.
    listing_type: return | management | operatingExpense | size
    """
    j = _post("/api/fund-returns/export", {
        "format": "json", "listingType": listing_type,
        "fundType": fon_tipi, "locale": "tr",
    })
    return j if isinstance(j, list) else []


# ============================================================
#  10) FVT-UYUMLU YÜKSEK SEVİYE WRAPPER'LAR
# ============================================================
def fvt_uyumlu_tum_fonlar() -> List[Dict[str, Any]]:
    """fvt_api.fvt_tum_fonlar() ile uyumlu format döner.

    Eğer bir kod fvt_api.fvt_tum_fonlar() bekliyorsa bunu fallback olarak
    kullanabilir. Sadece minimum alanlar: fon_kodu, fon_adi, fiyat, getiri,
    sirket_kodu, kategori (basit).
    """
    fonlar = tum_fonlar("YAT")
    sonuc = []
    for f in fonlar:
        sonuc.append({
            "fon_kodu": f.get("fonKod", ""),
            "fon_adi": f.get("unvan", ""),
            "sirket_kodu": f.get("kurucuKod", ""),
            "kategori": "",
            "fiyat": None,  # tum_fonlar fiyat vermiyor; gerekirse fon_anlik_bilgi
            "getiri": None,
        })
    return sonuc


def fon_son_fiyat_ve_getiri(fon_kodu: str) -> Tuple[Optional[float], Optional[float], str]:
    """fvt_api'den son fiyat + günlük getiri muadili.
    Returns: (son_fiyat, gunluk_getiri_yuzde, son_tarih)
    """
    info = fon_anlik_bilgi(fon_kodu)
    if not info:
        return (None, None, "")
    fiyat = info.get("sonFiyat")
    getiri = info.get("gunlukGetiri")
    # Tarih ayrıca lazım — fonFiyatBilgi'den son satır
    rows = fon_fiyat_gecmisi(fon_kodu, PERIYOD_HAFTA)
    son_tarih = rows[-1]["tarih"] if rows else ""
    return (fiyat, getiri, son_tarih)


def fonlar_son_fiyat_bulk(fon_tipi: str = "YAT", tarih: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """BULK son fiyat — tek istekte tüm fonlar için fiyat.

    fonGnlBlgSiraliGetir kullanarak tüm fonların {fonKodu: {fiyat, tarih, ...}} eşlemesini döner.
    Yaklaşık 4-10 istek (250'lik sayfa) ile 1000+ fon.
    """
    rows = fonlar_gunluk_detay_hepsi(fon_tipi=fon_tipi,
                                       bas_tarih=tarih, bit_tarih=tarih)
    return {r["fonKodu"]: r for r in rows if r.get("fonKodu")}


# ============================================================
#  CLI / SMOKE TEST
# ============================================================
if __name__ == "__main__":
    print(f"=== TEFAS API smoke test (backend={_HTTP_BACKEND}) ===\n")
    KOD = "IPB"

    print(f"[1] fon_fiyat_gecmisi('{KOD}', haftalık):")
    for r in fon_fiyat_gecmisi(KOD, PERIYOD_HAFTA):
        print(f"   {r['tarih']}  {r['fiyat']}")

    print(f"\n[2] fon_5y_fiyat('{KOD}') sayım:")
    p5 = fon_5y_fiyat(KOD)
    if p5:
        print(f"   {len(p5)} gün, ilk={p5[0]['tarih']} son={p5[-1]['tarih']} fiyat={p5[-1]['fiyat']}")

    print(f"\n[3] fon_anlik_bilgi('{KOD}'):")
    print("  ", fon_anlik_bilgi(KOD))

    print(f"\n[4] fon_portfoy_dagilimi('{KOD}'):")
    p = fon_portfoy_dagilimi(KOD)
    if p:
        print("  ", portfoy_dagilimi_normalize(p))

    print("\n[5] fonlar_son_fiyat_bulk — sayım:")
    bulk = fonlar_son_fiyat_bulk("YAT")
    print(f"   {len(bulk)} fon. {KOD} örnek: {bulk.get(KOD)}")

    print("\n[6] tum_fonlar -> fvt_uyumlu_tum_fonlar -> ilk 2:")
    for f in fvt_uyumlu_tum_fonlar()[:2]:
        print("  ", f)
