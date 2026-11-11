"""Madara (WordPress "wp-manga") загвар — олон зуун скан сайт энэ загвар дээр ажилладаг."""
import re

from bs4 import BeautifulSoup

from .. import http
from .base import Source, img_src, chapter_number, text, dedupe, genre_links


class Madara(Source):
    type = "madara"

    @property
    def mpath(self):
        return self.cfg.get("manga_path", "manga").strip("/")

    def _list(self, s):
        items = []
        for el in s.select("div.page-item-detail, div.c-tabs-item__content, div.manga-item, div.manga__item"):
            a = el.select_one(".post-title a, h3 a, h4 a, .item-summary a, .manga__content a")
            if not a or not a.get("href"):
                continue
            items.append({"id": a["href"], "title": text(a), "cover": img_src(el.select_one("img"), self.base)})
        nxt = s.select_one("a.nextpostslink, .nav-previous a, a.next.page-numbers, .wp-pagenavi a.next, a.last")
        return {"items": dedupe(items), "has_next": bool(nxt)}

    def _listing(self, order, page):
        url = f"{self.base}/{self.mpath}/" + (f"page/{page}/" if page > 1 else "")
        s, _ = self.soup(url, params={"m_orderby": order})
        return self._list(s)

    def popular(self, page):
        return self._listing("views", page)

    def latest(self, page):
        return self._listing("latest", page)

    def search(self, query, page):
        url = f"{self.base}/" + (f"page/{page}/" if page > 1 else "")
        s, _ = self.soup(url, params={"s": query, "post_type": "wp-manga"})
        return self._list(s)

    def genres(self):
        s, _ = self.soup(f"{self.base}/{self.mpath}/")
        g = genre_links(s, self.base, r"/manga-genre/([^/?#]+)/?")
        if not g:
            s, _ = self.soup(self.base + "/")
            g = genre_links(s, self.base, r"/manga-genre/([^/?#]+)/?")
        return g

    def by_genre(self, genre_id, page):
        url = f"{self.base}/manga-genre/{genre_id}/" + (f"page/{page}/" if page > 1 else "")
        s, _ = self.soup(url, params={"m_orderby": "views"})
        return self._list(s)

    def _info(self, s, label):
        for item in s.select(".post-content_item, .summary-content_wrap .post-content_item"):
            if re.search(label, text(item.select_one(".summary-heading")), re.I):
                return text(item.select_one(".summary-content"))
        return ""

    def details(self, manga_id):
        s, _ = self.soup(manga_id)
        t = s.select_one(".post-title h1, .post-title h3, .post-title, h1")
        if t:
            for b in t.select(".manga-title-badges, span"):
                b.decompose()
        return {
            "id": manga_id,
            "url": manga_id,
            "title": text(t),
            "cover": img_src(s.select_one(".summary_image img"), self.base),
            "description": text(s.select_one(".description-summary, .summary__content, .manga-excerpt, .manga-summary")),
            "author": ", ".join(text(a) for a in s.select(".author-content a")),
            "status": self._info(s, "status|төлөв"),
            "genres": [text(a) for a in s.select(".genres-content a")],
            "chapters": self._chapters(s, manga_id),
        }

    def _chapters(self, s, manga_id):
        lis = s.select("li.wp-manga-chapter")
        hdr = {"X-Requested-With": "XMLHttpRequest"}
        if not lis:  # шинэ Madara: ajax/chapters
            try:
                r = http.post(manga_id.rstrip("/") + "/ajax/chapters/", referer=manga_id, headers=hdr)
                lis = BeautifulSoup(r.text, "html.parser").select("li.wp-manga-chapter")
            except Exception:
                pass
        if not lis:  # хуучин Madara: admin-ajax
            holder = s.select_one("#manga-chapters-holder")
            mid = holder.get("data-id") if holder else None
            if not mid:
                inp = s.select_one("input.rating-post-id, #manga-reading-nav-head")
                mid = inp.get("value") or inp.get("data-id") if inp else None
            if mid:
                try:
                    r = http.post(self.base + "/wp-admin/admin-ajax.php", referer=manga_id, headers=hdr,
                                  data={"action": "manga_get_chapters", "manga": mid})
                    lis = BeautifulSoup(r.text, "html.parser").select("li.wp-manga-chapter")
                except Exception:
                    pass
        out = []
        for li in lis:
            a = li.select_one("a")
            if not a or not a.get("href"):
                continue
            for x in a.select("span, i"):
                x.extract()
            name = text(a)
            out.append({"id": a["href"], "name": name, "number": chapter_number(name),
                        "date": text(li.select_one(".chapter-release-date"))})
        return dedupe(out)

    def pages(self, chapter_id):
        url = chapter_id + ("&" if "?" in chapter_id else "?") + "style=list"
        s, _ = self.soup(url)
        imgs = s.select("div.page-break img, .reading-content img, .read-container img")
        urls = []
        for i in imgs:
            u = img_src(i, self.base)
            if u and u not in urls:
                urls.append(u)
        if not urls:
            if s.select_one("#chapter-protector-data, script#chapter-protector-data"):
                raise http.HttpError("Энэ бүлэг шифрлэгдсэн (chapter protector) — дэмжигдээгүй.")
            raise http.HttpError("Зураг олдсонгүй (бүлэг түгжээтэй эсвэл нэвтрэх шаардлагатай байж магадгүй).")
        return urls
