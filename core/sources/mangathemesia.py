"""MangaThemesia (WordPress) загвар — "bsx" карт, ts_reader ашигладаг скан сайтууд."""
import base64
import json
import re

from .. import http
from .base import Source, img_src, chapter_number, text, dedupe

TS_RE = re.compile(r"ts_reader\.run\((\{.*?\})\);", re.S)


class MangaThemesia(Source):
    type = "mangathemesia"

    @property
    def mpath(self):
        return self.cfg.get("manga_path", "manga").strip("/")

    def _list(self, s):
        items = []
        for el in s.select(".listupd .bs, .bsx"):
            a = el.select_one("a")
            if not a or not a.get("href"):
                continue
            title = a.get("title") or text(el.select_one(".tt")) or text(a)
            items.append({"id": a["href"], "title": title.strip(), "cover": img_src(el.select_one("img"), self.base)})
        nxt = s.select_one(".hpage a.r, a.next.page-numbers, .pagination a.next, a.r")
        return {"items": dedupe(items), "has_next": bool(nxt)}

    def popular(self, page):
        s, _ = self.soup(f"{self.base}/{self.mpath}/", params={"page": page, "order": "popular"})
        return self._list(s)

    def latest(self, page):
        s, _ = self.soup(f"{self.base}/{self.mpath}/", params={"page": page, "order": "update"})
        return self._list(s)

    def search(self, query, page):
        url = f"{self.base}/" + (f"page/{page}/" if page > 1 else "")
        s, _ = self.soup(url, params={"s": query})
        return self._list(s)

    def details(self, manga_id):
        s, _ = self.soup(manga_id)
        status, author = "", ""
        info = {}  # шошго -> утга (англи, франц, испани гэх мэт сайтуудад)
        for tr in s.select(".infotable tr"):
            td = tr.select("td")
            if len(td) >= 2:
                info[text(td[0]).lower()] = text(td[-1])
        for el in s.select(".imptdt, .tsinfo .imptdt, .fmed"):
            val = text(el.select_one("i, a, span"))
            label = text(el).replace(val, "").strip(" :").lower() if val else ""
            if label and val:
                info.setdefault(label, val)
        for k, v in info.items():
            if not status and re.search(r"stat[uo]|estado|durum", k):
                status = v
            elif re.search(r"aut(h|e)?or|auteur|artist|dessinateur", k) and v and v != "-" and v not in author:
                author = f"{author}, {v}" if author else v
        chapters = []
        for li in s.select("#chapterlist li, .eplister li, .cl li"):
            a = li.select_one("a")
            if not a or not a.get("href"):
                continue
            name = text(li.select_one(".chapternum, .epl-num")) or text(a)
            num = li.get("data-num")
            try:
                num = float(num) if num else chapter_number(name)
            except ValueError:
                num = chapter_number(name)
            chapters.append({"id": a["href"], "name": name, "number": num,
                             "date": text(li.select_one(".chapterdate, .epl-date"))})
        return {
            "id": manga_id,
            "url": manga_id,
            "title": text(s.select_one("h1.entry-title, .seriestuheader h1, h1")),
            "cover": img_src(s.select_one(".thumb img, .infomanga img, .thumbook img, .seriestucontl img"), self.base),
            "description": text(s.select_one("div[itemprop=description], .entry-content-single, .summary .entry-content")),
            "author": author,
            "status": status,
            "genres": [text(a) for a in s.select(".mgen a, .seriestugenre a, .genxed a")],
            "chapters": dedupe(chapters),
        }

    def pages(self, chapter_id):
        s, r = self.soup(chapter_id)
        blobs = [r.text]
        for sc in s.select("script[src^='data:text/javascript;base64,']"):
            try:
                blobs.append(base64.b64decode(sc["src"].split(",", 1)[1]).decode("utf-8", "ignore"))
            except Exception:
                pass
        for blob in blobs:
            m = TS_RE.search(blob)
            if m:
                try:
                    data = json.loads(m.group(1))
                    for src in data.get("sources", []):
                        if src.get("images"):
                            return [u.strip() for u in src["images"] if u and u.strip()]
                except Exception:
                    pass
        urls = []
        for i in s.select("#readerarea img"):
            u = img_src(i, self.base)
            if u and u not in urls:
                urls.append(u)
        if not urls:
            raise http.HttpError("Зураг олдсонгүй.")
        return urls
