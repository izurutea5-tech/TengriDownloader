"""HTTP helper: curl_cffi (Chrome-ийн TLS дуурайдаг, Cloudflare-д илүү тэсвэртэй) байвал түүнийг, үгүй бол requests ашиглана."""
import threading
import time

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

try:
    from curl_cffi import requests as _r
    USING_CURL = True
except Exception:  # pragma: no cover
    import requests as _r
    USING_CURL = False

_local = threading.local()

# Cloudflare-тай сайтууд: хэрэглэгч өөрөө програмын цонхонд шалгалтыг давахад авсан cookie + User-Agent.
# {"manhuaus.com": {"cookies": {name: value}, "ua": "..."}}
_cf = {}
_cf_loaded = False


def _cf_store():
    global _cf_loaded
    if not _cf_loaded:
        try:
            from . import store
            _cf.update(store.load("cf") or {})
        except Exception:
            pass
        _cf_loaded = True
    return _cf


def _host(url):
    from urllib.parse import urlparse
    return urlparse(url).netloc.lower().removeprefix("www.")


def set_site_auth(url, cookies, ua):
    h = _host(url)
    _cf_store()[h] = {"cookies": cookies, "ua": ua}
    try:
        from . import store
        store.save("cf", _cf)
    except Exception:
        pass


def _auth_for(url):
    h = _host(url)
    d = _cf_store()
    for k, v in d.items():
        if h == k or h.endswith("." + k):
            return v
    return None


class HttpError(Exception):
    pass


def session():
    s = getattr(_local, "s", None)
    if s is None:
        if USING_CURL:
            s = _r.Session(impersonate="chrome")
        else:
            s = _r.Session()
            s.headers.update({"User-Agent": UA})
        _local.s = s
    return s


def _check(r, url):
    if r.status_code in (403, 503) and ("Just a moment" in r.text[:3000] or "cf-chl" in r.text[:5000]):
        raise HttpError(f"Cloudflare хамгаалалт: {url} — «Баталгаажуулах» товчоор сайтыг нэг удаа нээж шалгалтыг өөрөө давна уу.")
    if r.status_code >= 400:
        raise HttpError(f"HTTP {r.status_code}: {url}")
    return r


def request(method, url, referer=None, headers=None, retries=3, timeout=30, **kw):
    h = dict(headers or {})
    if referer:
        h.setdefault("Referer", referer)
    auth = _auth_for(url)
    if auth:
        if auth.get("ua"):
            h["User-Agent"] = auth["ua"]
        ck = "; ".join(f"{k}={v}" for k, v in (auth.get("cookies") or {}).items())
        if ck:
            h["Cookie"] = (h.get("Cookie") + "; " if h.get("Cookie") else "") + ck
    last = None
    for i in range(retries):
        try:
            r = session().request(method, url, headers=h, timeout=timeout, **kw)
            if r.status_code in (429, 502, 503, 504) and i < retries - 1:
                time.sleep(2 * (i + 1))
                continue
            return _check(r, url)
        except HttpError as e:
            last = e
            if "HTTP 4" in str(e) and "429" not in str(e):
                break
            time.sleep(1 + i)
        except Exception as e:
            last = HttpError(f"{type(e).__name__}: {e}")
            time.sleep(1 + i)
    raise last


def get(url, **kw):
    return request("GET", url, **kw)


def post(url, **kw):
    return request("POST", url, **kw)
