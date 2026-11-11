import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import http


def img_src(tag, base):
    if tag is None:
        return None
    for a in ("data-src", "data-lazy-src", "data-cfsrc", "data-original", "data-url", "src"):
        v = (tag.get(a) or "").strip()
        if v and not v.startswith("data:"):
            return urljoin(base + "/", v)
    ss = tag.get("data-srcset") or tag.get("srcset")
    if ss:
        return urljoin(base + "/", ss.split(",")[-1].strip().split(" ")[0])
    return None


def chapter_number(name):
    m = re.search(r"(?:ch(?:apter|\.)?|ep(?:isode)?|第)\s*(\d+(?:\.\d+)?)", name, re.I)
    if not m:
        m = re.search(r"(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else -1


def text(el):
    return el.get_text(" ", strip=True) if el else ""


def dedupe(items, key="id"):
    seen, out = set(), []
    for it in items:
        if it[key] and it[key] not in seen:
            seen.add(it[key])
            out.append(it)
    return out


class Source:
    """Бүх эх сурвалжийн суурь класс.

    popular/latest/search -> {"items": [{id,title,cover}], "has_next": bool}
    details -> {id,title,cover,description,author,status,genres,url,chapters:[{id,name,number,date}]}
    pages   -> [зургийн URL, ...]
    """
    type = ""

    def __init__(self, cfg):
        self.cfg = cfg
        self.id = cfg["id"]
        self.name = cfg["name"]
        self.base = cfg.get("base_url", "").rstrip("/")
        self.lang = cfg.get("lang", "en")

    def soup(self, url, method="GET", **kw):
        r = http.request(method, url, referer=self.base + "/", **kw)
        return BeautifulSoup(r.text, "html.parser"), r

    def img_headers(self):
        return {"Referer": self.base + "/"}

    def popular(self, page):
        raise NotImplementedError

    def latest(self, page):
        return self.popular(page)

    def search(self, query, page):
        raise NotImplementedError

    def details(self, manga_id):
        raise NotImplementedError

    def pages(self, chapter_id):
        raise NotImplementedError
