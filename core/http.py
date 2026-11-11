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
        raise HttpError(f"Cloudflare хамгаалалт ({url}). Хэсэг хүлээгээд дахин оролдоно уу.")
    if r.status_code >= 400:
        raise HttpError(f"HTTP {r.status_code}: {url}")
    return r


def request(method, url, referer=None, headers=None, retries=3, timeout=30, **kw):
    h = dict(headers or {})
    if referer:
        h.setdefault("Referer", referer)
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
