import re
from urllib.parse import urlparse

from .. import http
from .generic import Generic
from .madara import Madara
from .mangadex import MangaDex
from .mangathemesia import MangaThemesia
from .nokara import Nokara

TYPES = {c.type: c for c in (MangaDex, Madara, MangaThemesia, Nokara, Generic)}


def build(cfg):
    return TYPES[cfg["type"]](dict(cfg))


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "site"


def detect(url):
    """URL-аас сайтын загварыг автоматаар таних. -> {type, base_url, name, manga_path}"""
    if not url.startswith("http"):
        url = "https://" + url
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    name = p.netloc.replace("www.", "").split(".")[0].replace("-", " ").title()
    if "mangadex.org" in p.netloc:
        return {"type": "mangadex", "base_url": base, "name": "MangaDex", "manga_path": ""}
    html = http.get(url).text
    low = html.lower()
    seg = [x for x in p.path.split("/") if x]
    dirs = ("manga", "series", "catalogue", "comics", "manhwa", "webtoon", "comic", "read", "manhua", "komik")
    if seg and seg[0] in dirs:
        mpath = seg[0]
    else:  # нүүр хуудаснаас: цувралын холбоосуудад хамгийн олон таарах хавтас
        hits = re.findall(r'href=["\'](?:%s)?/(%s)/[^"\'/]+/?["\']' % (re.escape(base), "|".join(dirs)), html)
        mpath = max(set(hits), key=hits.count) if hits else "manga"
    if "nokara" in low or "rk-novel-card" in low or "as-chrow" in low:
        t = "nokara"
    elif "wp-manga" in low or "madara" in low or "manga-chapters-holder" in low:
        t = "madara"
    elif "ts_reader" in low or 'id="chapterlist"' in low or 'class="bsx"' in low or "mangareader" in low:
        t = "mangathemesia"
    else:
        t = "generic"
    sn = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', html, re.I)
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if sn and sn.group(1).strip():
        name = sn.group(1).strip()[:40]
    elif m and t != "generic" and p.path in ("", "/"):
        name = re.split(r"[|\-–—]", m.group(1).strip())[0].strip()[:40] or name
    lang = re.search(r'<html[^>]+lang=["\']([a-zA-Z]{2})', html)
    return {"type": t, "base_url": base, "name": name, "manga_path": mpath, "lang": lang.group(1).lower() if lang else "en"}
