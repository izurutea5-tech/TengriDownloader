"""MangaDex — албан ёсны нээлттэй API."""
from .. import http
from .base import Source

API = "https://api.mangadex.org"
RATINGS = [("contentRating[]", r) for r in ("safe", "suggestive", "erotica")]


def _title(attr):
    t = attr.get("title", {})
    if "en" in t:
        return t["en"]
    for alt in attr.get("altTitles", []):
        if "en" in alt:
            return alt["en"]
    return next(iter(t.values()), "?")


class MangaDex(Source):
    type = "mangadex"

    def __init__(self, cfg):
        cfg.setdefault("base_url", "https://mangadex.org")
        super().__init__(cfg)

    def img_headers(self):
        return {}

    def _cover(self, m):
        for rel in m.get("relationships", []):
            if rel["type"] == "cover_art" and rel.get("attributes"):
                return f"https://uploads.mangadex.org/covers/{m['id']}/{rel['attributes']['fileName']}.256.jpg"
        return None

    def _query(self, page, extra):
        limit = 24
        params = [("limit", limit), ("offset", (page - 1) * limit), ("includes[]", "cover_art"),
                  ("availableTranslatedLanguage[]", self.lang), ("hasAvailableChapters", "true")] + RATINGS + extra
        d = http.get(API + "/manga", params=params).json()
        items = [{"id": m["id"], "title": _title(m["attributes"]), "cover": self._cover(m)} for m in d["data"]]
        return {"items": items, "has_next": d["offset"] + limit < d["total"]}

    def popular(self, page):
        return self._query(page, [("order[followedCount]", "desc")])

    def latest(self, page):
        return self._query(page, [("order[latestUploadedChapter]", "desc")])

    def search(self, query, page):
        return self._query(page, [("title", query), ("order[relevance]", "desc")])

    def details(self, manga_id):
        m = http.get(f"{API}/manga/{manga_id}", params=[("includes[]", "cover_art"), ("includes[]", "author")]).json()["data"]
        a = m["attributes"]
        chapters, offset = [], 0
        while True:
            d = http.get(f"{API}/manga/{manga_id}/feed", params=[
                ("translatedLanguage[]", self.lang), ("order[chapter]", "desc"), ("limit", 500),
                ("offset", offset), ("includeExternalUrl", 0), ("includes[]", "scanlation_group")] + RATINGS).json()
            for c in d["data"]:
                ca = c["attributes"]
                if ca.get("pages", 1) == 0:
                    continue
                name = (f"Vol.{ca['volume']} " if ca.get("volume") else "") + f"Ch.{ca.get('chapter') or '?'}"
                if ca.get("title"):
                    name += f" - {ca['title']}"
                grp = next((r["attributes"]["name"] for r in c["relationships"]
                            if r["type"] == "scanlation_group" and r.get("attributes")), "")
                try:
                    num = float(ca.get("chapter") or -1)
                except ValueError:
                    num = -1
                chapters.append({"id": c["id"], "name": name + (f" [{grp}]" if grp else ""), "number": num,
                                 "date": (ca.get("publishAt") or "")[:10]})
            offset += 500
            if offset >= d["total"]:
                break
        return {
            "id": manga_id,
            "url": f"https://mangadex.org/title/{manga_id}",
            "title": _title(a),
            "cover": self._cover(m),
            "description": a.get("description", {}).get("en", ""),
            "author": ", ".join(r["attributes"]["name"] for r in m["relationships"]
                                if r["type"] == "author" and r.get("attributes")),
            "status": a.get("status", ""),
            "genres": [t["attributes"]["name"].get("en", "") for t in a.get("tags", [])],
            "chapters": chapters,
        }

    def pages(self, chapter_id):
        d = http.get(f"{API}/at-home/server/{chapter_id}").json()
        ch = d["chapter"]
        return [f"{d['baseUrl']}/data/{ch['hash']}/{f}" for f in ch["data"]]
