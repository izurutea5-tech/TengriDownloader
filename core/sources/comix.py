"""comix.mn — монгол орчуулгын сайт (Next.js + JSON API).
Жагсаалт: /api/mangas?page=N[&search=…][&genres=slug] · Цуврал: /api/mangas/<id>
Бүлгүүд: /api/mangas/<id>/chapters?pageSize=1000 (isFree) · Зураг: /api/mangas/<id>/chapters/<n> → images[]
Төлбөртэй (эрхтэй) бүлгүүдийг жагсаалтад 🔒 тэмдэгтэй харуулна, гэхдээ уншиж/татах боломжгүй (сайтын эрх шаардана)."""
import json
import re

from .. import http
from .base import Source

LOCKED = "locked:"

# Сайтын төрлийн slug → сайт дээр харагддаг монгол нэр
GENRE_MN = {
    "action": "Тулаант", "adventure": "Адал явдал", "comedy": "Инээдмийн", "drama": "Драм", "fantasy": "Фэнтэзи",
    "romance": "Романтик", "horror": "Аймшиг", "mystery": "Нууцлаг", "murim": "Мурим", "reincarnation": "Дахин төрөлт",
    "revenge": "Өшөө авалт", "regression": "Буцаж ирэлт", "system": "Систем", "magic": "Ид шид", "villain": "Хорон санаатан",
    "sci-fi": "Шинжлэх ухааны уран зөгнөл", "slice-of-life": "Өдөр тутмын", "school": "Сургууль", "sports": "Спорт",
    "supernatural": "Ер бусын", "thriller": "Триллер", "isekai": "Исекай", "historical": "Түүхэн", "psychological": "Сэтгэл зүйн",
    "martial-arts": "Тулааны урлаг", "game": "Тоглоом", "dungeon": "Шорон", "military": "Цэргийн", "tragedy": "Эмгэнэлт",
}


def genre_name(slug):
    return GENRE_MN.get(slug, slug.replace("-", " ").title())


class Comix(Source):
    type = "comix"

    def _get(self, path, **params):
        r = http.get(self.base + path, params=params or None, referer=self.base + "/")
        try:
            return json.loads(r.text)
        except ValueError:
            raise http.HttpError("comix.mn: хариу уншигдсангүй")

    def _card(self, m):
        return {"id": str(m["id"]), "title": m.get("title") or "?", "cover": m.get("coverImage") or m.get("mangaImage")}

    def _list(self, page, **params):
        d = self._get("/api/mangas", page=page, **params)
        return {"items": [self._card(m) for m in d.get("data") or []],
                "has_next": page < int(d.get("totalPages") or 1)}

    def popular(self, page):
        return self._list(page)

    def latest(self, page):
        return self._list(page)

    def search(self, query, page):
        return self._list(page, search=query)

    def genres(self):
        seen, page = set(), 1
        while page <= 20:
            d = self._get("/api/mangas", page=page)
            for m in d.get("data") or []:
                seen.update(g for g in m.get("genres") or [] if g)
            if page >= int(d.get("totalPages") or 1):
                break
            page += 1
        return sorted(({"id": g, "name": genre_name(g)} for g in seen), key=lambda g: g["name"].lower())

    def by_genre(self, genre_id, page):
        return self._list(page, genres=genre_id)

    def details(self, manga_id):
        hit = re.search(r"/projects/(\d+)", manga_id)  # хуулсан холбоос: comix.mn/projects/9412[/read/2]
        if hit:
            manga_id = hit.group(1)
        m = self._get(f"/api/mangas/{manga_id}")["data"]
        chs = self._get(f"/api/mangas/{manga_id}/chapters", pageSize=1000).get("data") or []
        chapters = []
        for c in chs:
            num = c.get("chapterNumber")
            free = bool(c.get("isFree"))
            cid = f"{manga_id}/{c.get('id') or num}"  # pages() нь цувралын id-г шаарддаг
            chapters.append({"id": cid if free else LOCKED + cid,
                             "name": f"Бүлэг {num if num is not None else c.get('id')}" + ("" if free else " 🔒"),
                             "number": float(num) if num is not None else None,
                             "date": (c.get("createdAt") or "")[:10], "locked": not free})
        kind = {"manhwa": "Манхва", "manga": "Манга", "manhua": "Манхуа"}.get(m.get("type"), m.get("type") or "")
        status = {"ongoing": "Гарч байгаа", "completed": "Дууссан"}.get(m.get("status"), m.get("status") or "")
        return {
            "id": str(manga_id), "url": f"{self.base}/projects/{manga_id}",
            "title": m.get("title") or "",
            "cover": m.get("coverImage") or m.get("mangaImage"),
            "description": m.get("description") or "",
            "author": kind,
            "status": status,
            "genres": [genre_name(g) for g in m.get("genres") or []],
            "chapters": chapters,
        }

    def pages(self, chapter_id):
        if chapter_id.startswith(LOCKED):
            raise http.HttpError("🔒 Энэ бүлэг төлбөртэй — comix.mn-ийн эрхгүйгээр унших, татах боломжгүй.")
        mid, _, n = chapter_id.partition("/")
        d = self._get(f"/api/mangas/{mid}/chapters/{n}")
        imgs = (d.get("data") or {}).get("images") or []
        if not imgs:
            raise http.HttpError("Энэ бүлэгт зураг олдсонгүй")
        return imgs
