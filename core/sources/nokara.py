"""«Nokara» WordPress загвар (nebula.mn гэх мэт монгол сайтууд).
Жагсаалт: /manga/page/N/?sort=trending|new · Хайлт: /manga/?s=… · Бүлэг: a.as-chrow (data-locked=1 → Crown эрхтэй).
Түгжээтэй (👑 Crown) бүлгүүдийг жагсаалтад харуулна, гэхдээ уншиж/татах боломжгүй (сайтын эрх шаардана)."""
from .. import http
from .base import Source, img_src, chapter_number, text, dedupe

LOCKED = "locked:"


class Nokara(Source):
    type = "nokara"

    @property
    def mpath(self):
        return (self.cfg.get("manga_path") or "manga").strip("/")

    def _list(self, s):
        items = []
        for a in s.select("a.rk-novel-card"):
            if not a.get("href"):
                continue
            items.append({"id": a["href"], "title": text(a.select_one(".rk-novel-title, h3")) or (a.select_one("img") or {}).get("alt", ""),
                          "cover": img_src(a.select_one("img"), self.base)})
        nxt = s.select_one(".nk-pagination a.next, a.next.page-numbers")
        return {"items": dedupe(items), "has_next": bool(nxt)}

    def _url(self, page):
        return f"{self.base}/{self.mpath}/" + (f"page/{page}/" if page > 1 else "")

    def popular(self, page):
        s, _ = self.soup(self._url(page), params={"sort": "trending"})
        return self._list(s)

    def latest(self, page):
        s, _ = self.soup(self._url(page), params={"sort": "new"})
        return self._list(s)

    def search(self, query, page):
        s, _ = self.soup(self._url(page), params={"s": query})
        return self._list(s)

    def details(self, manga_id):
        s, _ = self.soup(manga_id)
        og = s.select_one("meta[property='og:image']")
        cover = img_src(s.select_one("img.mh-cover__img"), self.base) or (og.get("content") if og else None)
        chapters = []
        for a in s.select("a.as-chrow"):
            locked = a.get("data-locked") == "1"
            name = text(a.select_one(".as-ch-name")) or a.get("data-ch-title") or ""
            try:
                num = float(a.get("data-ch-no"))
            except (TypeError, ValueError):
                num = chapter_number(name)
            href = a.get("href") or ""
            if locked or "/chapter/" not in href:
                cid = LOCKED + (a.get("data-ch") or name)
                locked = True
            else:
                cid = href
            chapters.append({"id": cid, "name": name + (" 👑" if locked else ""), "number": num,
                             "date": text(a.select_one(".as-ch-time")), "locked": locked})
        genres = [text(x) for x in s.select(".mh-genres a, a[rel=tag], .mh-tags a")]
        return {
            "id": manga_id, "url": manga_id,
            "title": text(s.select_one("h1.mh-title, h1")),
            "cover": cover,
            "description": text(s.select_one("#asDesc, .as-desc")),
            "author": "",
            "status": text(s.select_one(".mh-status-pill")),
            "genres": [g for g in genres if g][:20],
            "chapters": dedupe(chapters),
        }

    def pages(self, chapter_id):
        if chapter_id.startswith(LOCKED):
            raise http.HttpError("👑 Энэ бүлэг Crown эрх шаарддаг — сайтын эрхгүйгээр унших, татах боломжгүй.")
        s, r = self.soup(chapter_id)
        urls = []
        for im in s.select(".pg-wrap img, #nkBody img"):
            u = img_src(im, self.base)
            if u and u not in urls:
                urls.append(u)
        if not urls:
            if "Түгжээтэй бүлэг" in r.text or "Crown эрх" in r.text:
                raise http.HttpError("👑 Энэ бүлэг Crown эрх шаарддаг — сайтын эрхгүйгээр унших, татах боломжгүй.")
            raise http.HttpError("Зураг олдсонгүй.")
        return urls
