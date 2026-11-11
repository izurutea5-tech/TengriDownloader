"""Ерөнхий (generic) эх сурвалж — ямар ч загварт таарахгүй сайтад "аль болох" ажиллах оролдлого.
Манга хуудаснаас 'chapter' гэсэн холбоосуудыг, бүлгийн хуудаснаас том зургуудыг цуглуулна."""
import re
from urllib.parse import urljoin, urlparse

from .. import http
from .base import Source, img_src, chapter_number, text, dedupe

SKIP = re.compile(r"logo|avatar|icon|banner|ads?[-_/]|gravatar|emoji|sprite|\.svg|\.gif", re.I)


class Generic(Source):
    type = "generic"

    def popular(self, page):
        return {"items": [], "has_next": False}

    def search(self, query, page):
        return {"items": [], "has_next": False}

    def details(self, manga_id):
        s, _ = self.soup(manga_id)
        host = urlparse(manga_id).netloc
        chapters = []
        for a in s.select("a[href]"):
            href = urljoin(manga_id, a["href"])
            if urlparse(href).netloc != host:
                continue
            if re.search(r"chapter|/ch[-_/]?\d|episode|/c\d", href, re.I) and href.rstrip("/") != manga_id.rstrip("/"):
                name = text(a) or href.rstrip("/").rsplit("/", 1)[-1]
                chapters.append({"id": href, "name": name[:120], "number": chapter_number(name + " " + href), "date": ""})
        chapters = dedupe(chapters)
        chapters.sort(key=lambda c: c["number"], reverse=True)
        og = s.select_one("meta[property='og:image']")
        md = s.select_one("meta[name=description]")
        return {
            "id": manga_id, "url": manga_id,
            "title": text(s.select_one("h1")) or text(s.select_one("title")),
            "cover": og["content"] if og and og.get("content") else None,
            "description": md.get("content", "") if md else "",
            "author": "", "status": "", "genres": [], "chapters": chapters,
        }

    def pages(self, chapter_id):
        s, _ = self.soup(chapter_id)
        urls = []
        for i in s.select("img"):
            u = img_src(i, self.base)
            if not u or SKIP.search(u) or u in urls:
                continue
            w = i.get("width")
            if w and w.isdigit() and int(w) < 300:
                continue
            urls.append(u)
        if not urls:
            raise http.HttpError("Зураг олдсонгүй.")
        return urls
