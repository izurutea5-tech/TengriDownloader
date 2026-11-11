"""Suwayomi-Server-ийн GraphQL API-аар дамжуулан түүнд суулгасан БҮХ өргөтгөлийг (Keiyoushi гэх мэт) ашиглана.
Suwayomi сервер (Suwayomi Launcher) ажиллаж байх шаардлагатай. Анхдагч хаяг: http://127.0.0.1:4567"""
import base64
import re
import threading
import time
from datetime import datetime
from urllib.parse import urljoin

from .. import http
from .base import Source

PREFIX = "sw:"

Q_SOURCES = "query { sources { nodes { id name displayName lang iconUrl isNsfw supportsLatest } } }"
M_BROWSE = """mutation($input: FetchSourceMangaInput!) { fetchSourceManga(input: $input) {
  hasNextPage mangas { id title thumbnailUrl } } }"""
M_MANGA = """mutation($id: Int!) { fetchManga(input: {id: $id}) { manga {
  id title description author artist status genre thumbnailUrl realUrl } } }"""
M_CHAPTERS = """mutation($id: Int!) { fetchChapters(input: {mangaId: $id}) { chapters {
  id name chapterNumber uploadDate sourceOrder scanlator } } }"""
M_PAGES = "mutation($id: Int!) { fetchChapterPages(input: {chapterId: $id}) { pages } }"
_F = "__typename ... on CheckBoxFilter { name } ... on TriStateFilter { name } ... on SelectFilter { name values }"
Q_FILTERS = "query($id: LongString!) { source(id: $id) { filters { %s ... on GroupFilter { name filters { %s } } } } }" % (_F, _F)
M_BROWSE_F = """mutation($input: FetchSourceMangaInput!) { fetchSourceManga(input: $input) {
  hasNextPage mangas { id title thumbnailUrl } } }"""
GENRE_RE = re.compile(r"genre|tag|categor|жанр|төрөл|género|catégorie|gênero", re.I)
M_LOGIN = "mutation($u: String!, $p: String!) { login(input: {username: $u, password: $p}) { accessToken } }"


class Client:
    def __init__(self, url, user="", password=""):
        self.url = (url or "http://127.0.0.1:4567").rstrip("/")
        self.user, self.password = user or "", password or ""
        self.token = None
        self.lock = threading.Lock()

    def auth_headers(self):
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        if self.user:
            return {"Authorization": "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()}
        return {}

    def _post(self, query, variables):
        return http.post(self.url + "/api/graphql", json={"query": query, "variables": variables or {}},
                         headers={**self.auth_headers(), "Content-Type": "application/json"}, retries=2, timeout=120)

    def gql(self, query, variables=None):
        try:
            r = self._post(query, variables)
        except http.HttpError as e:
            if "401" in str(e) and self.user and not self.token:
                self.login()
                r = self._post(query, variables)
            elif not str(e).startswith("HTTP "):
                raise http.HttpError(f"Suwayomi сервертэй холбогдож чадсангүй ({self.url}). Suwayomi асаалттай эсэхийг шалга.")
            else:
                raise
        d = r.json()
        if d.get("errors"):
            msg = d["errors"][0].get("message", "GraphQL алдаа")
            if "unauthor" in msg.lower() and self.user and not self.token:
                self.login()
                return self.gql(query, variables)
            msg = re.sub(r"^Exception while fetching data \([^)]*\) : ", "", msg.splitlines()[0] if msg else msg)
            raise http.HttpError("Suwayomi: " + msg[:300])
        return d["data"]

    def login(self):
        with self.lock:
            r = http.post(self.url + "/api/graphql", json={"query": M_LOGIN, "variables": {"u": self.user, "p": self.password}},
                          headers={"Content-Type": "application/json"}, retries=1)
            d = r.json()
            if d.get("errors"):
                raise http.HttpError("Suwayomi нэвтрэлт амжилтгүй: " + d["errors"][0].get("message", ""))
            self.token = d["data"]["login"]["accessToken"]

    def abs(self, u):
        return urljoin(self.url + "/", u) if u else None


_client = {"key": None, "c": None}
_sources = {"t": 0, "list": [], "key": None}


def client(settings):
    from ..engine import effective_url
    builtin = settings.get("engine_mode", "builtin") == "builtin"
    key = (effective_url(settings), "" if builtin else settings.get("suwayomi_user"), "" if builtin else settings.get("suwayomi_pass"))
    if _client["key"] != key:
        _client.update(key=key, c=Client(*key))
    return _client["c"]


def list_sources(settings, force=False):
    c = client(settings)
    if force or _sources["key"] != c.url or time.time() - _sources["t"] > 300:
        nodes = c.gql(Q_SOURCES)["sources"]["nodes"]
        out = [{"id": PREFIX + n["id"], "name": n["displayName"], "lang": n["lang"], "icon": c.abs(n["iconUrl"]),
                "nsfw": n["isNsfw"], "latest": n["supportsLatest"], "type": "suwayomi"}
               for n in nodes if n["id"] != "0"]  # 0 = Local source
        out.sort(key=lambda s: (s["lang"], s["name"].lower()))
        _sources.update(t=time.time(), list=out, key=c.url)
    return _sources["list"]


def build(sid, settings):
    info = next((s for s in list_sources(settings) if s["id"] == sid), None)
    if not info:
        info = next((s for s in list_sources(settings, force=True) if s["id"] == sid), None)
    if not info:
        return None
    return SuwayomiSource({"id": sid, "name": info["name"], "lang": info["lang"], "latest": info["latest"],
                           "base_url": client(settings).url}, client(settings))


def _date(ms):
    try:
        ms = int(ms)
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d") if ms > 0 else ""
    except (TypeError, ValueError):
        return ""


class SuwayomiSource(Source):
    type = "suwayomi"

    def __init__(self, cfg, c):
        super().__init__(cfg)
        self.c = c
        self.sw_id = cfg["id"][len(PREFIX):]

    def img_headers(self):
        return self.c.auth_headers()

    def _browse(self, kind, page, query=None):
        inp = {"source": self.sw_id, "type": kind, "page": page}
        if query:
            inp["query"] = query
        d = self.c.gql(M_BROWSE, {"input": inp})["fetchSourceManga"]
        return {"items": [{"id": str(m["id"]), "title": m["title"], "cover": self.c.abs(m["thumbnailUrl"])}
                          for m in d["mangas"]], "has_next": d["hasNextPage"]}

    def popular(self, page):
        return self._browse("POPULAR", page)

    def latest(self, page):
        return self._browse("LATEST" if self.cfg.get("latest", True) else "POPULAR", page)

    def search(self, query, page):
        return self._browse("SEARCH", page, query)

    def genres(self):
        """Өргөтгөлийн шүүлтүүрээс «Genre/Tags» бүлгийг олно. id: "g<бүлэг>.<мөр>.<c|t>" эсвэл "s<байрлал>.<утга>" """
        fs = self.c.gql(Q_FILTERS, {"id": self.sw_id})["source"]["filters"]
        out = []
        for gi, f in enumerate(fs):
            t, name = f.get("__typename"), f.get("name") or ""
            if t == "GroupFilter" and GENRE_RE.search(name):
                for ci, ch in enumerate(f.get("filters") or []):
                    k = {"CheckBoxFilter": "c", "TriStateFilter": "t"}.get(ch.get("__typename"))
                    if k and ch.get("name"):
                        out.append({"id": f"g{gi}.{ci}.{k}", "name": ch["name"]})
            elif t == "SelectFilter" and GENRE_RE.search(name):
                for vi, v in enumerate(f.get("values") or []):
                    if vi and v:  # 0 нь ихэвчлэн «Бүгд»
                        out.append({"id": f"s{gi}.{vi}", "name": v})
            if out:
                break
        return out

    def by_genre(self, genre_id, page):
        if genre_id.startswith("g"):
            gi, ci, k = genre_id[1:].split(".")
            inner = {"position": int(ci)}
            inner.update({"checkBoxState": True} if k == "c" else {"triState": "INCLUDE"})
            change = {"position": int(gi), "groupChange": inner}
        else:
            gi, vi = genre_id[1:].split(".")
            change = {"position": int(gi), "selectState": int(vi)}
        inp = {"source": self.sw_id, "type": "SEARCH", "page": page, "query": "", "filters": [change]}
        d = self.c.gql(M_BROWSE_F, {"input": inp})["fetchSourceManga"]
        return {"items": [{"id": str(m["id"]), "title": m["title"], "cover": self.c.abs(m["thumbnailUrl"])}
                          for m in d["mangas"]], "has_next": d["hasNextPage"]}

    def details(self, manga_id):
        mid = int(manga_id)
        m = self.c.gql(M_MANGA, {"id": mid})["fetchManga"]["manga"]
        chs = self.c.gql(M_CHAPTERS, {"id": mid})["fetchChapters"]["chapters"]
        chs.sort(key=lambda c: c["sourceOrder"], reverse=True)
        return {
            "id": str(m["id"]),
            "url": m.get("realUrl") or "",
            "title": m["title"],
            "cover": self.c.abs(m.get("thumbnailUrl")),
            "description": m.get("description") or "",
            "author": ", ".join(dict.fromkeys(x for x in (m.get("author"), m.get("artist")) if x)),
            "status": (m.get("status") or "").replace("_", " ").title(),
            "genres": m.get("genre") or [],
            "chapters": [{"id": str(c["id"]), "name": c["name"] + (f" [{c['scanlator']}]" if c.get("scanlator") else ""),
                          "number": c["chapterNumber"], "date": _date(c.get("uploadDate"))} for c in chs],
        }

    def pages(self, chapter_id):
        pages = self.c.gql(M_PAGES, {"id": int(chapter_id)})["fetchChapterPages"]["pages"]
        if not pages:
            raise http.HttpError("Хуудас олдсонгүй.")
        return [self.c.abs(p) for p in pages]


# ---------------- Өргөтгөл / repo удирдлага ----------------
EXT_FIELDS = "pkgName name lang versionName isInstalled hasUpdate isObsolete isNsfw iconUrl repo"
_ext = {"t": 0, "list": [], "key": None}


def extensions(settings, refresh=False):
    """refresh=True бол repo-уудаас шинэ жагсаалт татна (удаан байж болно)."""
    c = client(settings)
    if refresh or _ext["key"] != c.url or not _ext["list"] or time.time() - _ext["t"] > 1800:
        try:
            lst = c.gql("mutation { fetchExtensions(input: {}) { extensions { %s } } }" % EXT_FIELDS)["fetchExtensions"]["extensions"]
        except http.HttpError:
            if refresh:
                raise
            lst = c.gql("{ extensions { nodes { %s } } }" % EXT_FIELDS)["extensions"]["nodes"]
        for e in lst:
            e["icon"] = c.abs(e.get("iconUrl"))
        _ext.update(t=time.time(), list=lst, key=c.url)
    return _ext["list"]


def update_extension(settings, pkg, action):
    assert action in ("install", "update", "uninstall")
    c = client(settings)
    e = c.gql("mutation($id: String!, $p: UpdateExtensionPatchInput!) { updateExtension(input: {id: $id, patch: $p}) "
              "{ extension { %s } } }" % EXT_FIELDS, {"id": pkg, "p": {action: True}})["updateExtension"]["extension"]
    if e:
        e["icon"] = c.abs(e.get("iconUrl"))
        _ext["list"] = [e if x["pkgName"] == pkg else x for x in _ext["list"]]
    _sources["t"] = 0  # эх сурвалжийн жагсаалтыг шинэчлэх
    return e


def stores(settings):
    c = client(settings)
    try:
        return c.gql("{ extensionStores { nodes { name indexUrl badgeLabel isLegacy extensions { totalCount } } } }")["extensionStores"]["nodes"]
    except http.HttpError:  # хуучин сервер: settings.extensionRepos
        repos = c.gql("{ settings { extensionRepos } }")["settings"]["extensionRepos"]
        return [{"name": r.split("/")[3] if r.count("/") > 3 else r, "indexUrl": r, "badgeLabel": "", "isLegacy": True,
                 "extensions": {"totalCount": None}} for r in repos]


def add_store(settings, url):
    c = client(settings)
    try:
        r = c.gql("mutation($u: String!) { addExtensionStore(input: {indexUrl: $u}) { extensionStore { name indexUrl } } }", {"u": url})
        _ext["t"] = 0
        return r["addExtensionStore"]["extensionStore"]
    except http.HttpError as e:
        if "Cannot query field" not in str(e) and "Validation" not in str(e):
            raise http.HttpError(str(e).split("\n")[0].split("\r")[0][:300])
        repos = c.gql("{ settings { extensionRepos } }")["settings"]["extensionRepos"]
        if url not in repos:
            c.gql("mutation($r: [String!]!) { setSettings(input: {settings: {extensionRepos: $r}}) { clientMutationId } }", {"r": repos + [url]})
        _ext["t"] = 0
        return {"name": url, "indexUrl": url}


def remove_store(settings, url):
    c = client(settings)
    try:
        c.gql("mutation($u: String!) { removeExtensionStore(input: {indexUrl: $u}) { clientMutationId } }", {"u": url})
    except http.HttpError as e:
        if "Cannot query field" not in str(e) and "Validation" not in str(e):
            raise
        repos = c.gql("{ settings { extensionRepos } }")["settings"]["extensionRepos"]
        c.gql("mutation($r: [String!]!) { setSettings(input: {settings: {extensionRepos: $r}}) { clientMutationId } }", {"r": [r for r in repos if r != url]})
    _ext["t"] = 0
