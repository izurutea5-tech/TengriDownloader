"""Татах дараалал: бүлэг бүрийг хуудас хуудсаар нь зэрэг татаж, хүсвэл CBZ болгож хадгална."""
import itertools
import os
import re
import shutil
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

from . import http, store

_ids = itertools.count(1)
EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif"}


_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def safe(name, n=120):
    """Windows, macOS, Linux бүгд дээр хүчинтэй файлын нэр."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")[:n].strip(" .")
    if name.split(".")[0].lower() in _RESERVED:
        name = "_" + name
    return name or "untitled"


def chapter_dir(settings, source_name, manga_title, chapter_name):
    return os.path.join(settings["download_dir"], safe(source_name), safe(manga_title), safe(chapter_name))


def is_downloaded(settings, source_name, manga_title, chapter_name):
    d = chapter_dir(settings, source_name, manga_title, chapter_name)
    return os.path.exists(d + ".cbz") or os.path.exists(os.path.join(d, ".done"))


class Downloader:
    def __init__(self, get_source):
        self.get_source = get_source
        self.jobs = {}  # id -> dict
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.paused = False
        self._workers = []
        self._ensure_workers()

    def _ensure_workers(self):
        n = max(1, int(store.load("settings")["chapter_workers"]))
        while len([w for w in self._workers if w.is_alive()]) < n:
            w = threading.Thread(target=self._loop, daemon=True)
            w.start()
            self._workers.append(w)

    # ---------- public ----------
    def add(self, source_id, manga, chapters):
        added = 0
        with self.cv:
            active = {(j["source_id"], j["chapter_id"]) for j in self.jobs.values() if j["status"] in ("queued", "downloading")}
            for ch in chapters:
                if (source_id, ch["id"]) in active:
                    continue
                jid = next(_ids)
                self.jobs[jid] = {
                    "id": jid, "source_id": source_id, "manga_id": manga["id"], "manga_title": manga["title"],
                    "cover": manga.get("cover"), "chapter_id": ch["id"], "chapter_name": ch["name"],
                    "chapter_number": ch.get("number", -1), "status": "queued", "done": 0, "total": 0, "error": "",
                }
                added += 1
            self.cv.notify_all()
        self._ensure_workers()
        return added

    def list(self):
        with self.lock:
            return [dict(j) for j in self.jobs.values()]

    def set_paused(self, p):
        with self.cv:
            self.paused = p
            self.cv.notify_all()

    def remove(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            if j and j["status"] != "downloading":
                del self.jobs[jid]
            elif j:
                j["status"] = "cancel"

    def retry(self, jid=None):
        with self.cv:
            for j in self.jobs.values():
                if j["status"] == "error" and (jid is None or j["id"] == jid):
                    j.update(status="queued", error="", done=0)
            self.cv.notify_all()

    def clear(self, which="finished"):
        with self.lock:
            for jid in list(self.jobs):
                st = self.jobs[jid]["status"]
                if which == "all" and st != "downloading" or st in ("done", "skipped"):
                    del self.jobs[jid]

    # ---------- worker ----------
    def _next(self):
        with self.cv:
            while True:
                if not self.paused:
                    for j in self.jobs.values():
                        if j["status"] == "queued":
                            j["status"] = "downloading"
                            return j
                self.cv.wait(1)

    def _loop(self):
        while True:
            job = self._next()
            try:
                self._run(job)
            except Exception as e:
                job["status"] = "error"
                job["error"] = str(e)[:300]

    def _run(self, job):
        settings = store.load("settings")
        src = self.get_source(job["source_id"])
        if src is None:
            raise RuntimeError("Эх сурвалж олдсонгүй (устгагдсан байж магадгүй)")
        d = chapter_dir(settings, src.name, job["manga_title"], job["chapter_name"])
        if is_downloaded(settings, src.name, job["manga_title"], job["chapter_name"]):
            job["status"] = "skipped"
            return
        urls = src.pages(job["chapter_id"])
        job["total"] = len(urls)
        os.makedirs(d, exist_ok=True)
        headers = src.img_headers()

        def fetch(i_url):
            i, url = i_url
            if job["status"] == "cancel":
                return
            existing = [f for f in os.listdir(d) if f.startswith(f"{i:03d}.")]
            if not existing:
                r = http.get(url, headers=headers, timeout=60, retries=4)
                ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
                if ctype.startswith("text/"):
                    raise http.HttpError(f"Зураг биш хариу ирлээ ({ctype}): {url}")
                ext = EXT.get(ctype) or os.path.splitext(url.split("?")[0])[1][:5] or ".jpg"
                tmp = os.path.join(d, f"{i:03d}{ext}.part")
                with open(tmp, "wb") as f:
                    f.write(r.content)
                os.replace(tmp, os.path.join(d, f"{i:03d}{ext}"))
            job["done"] += 1

        with ThreadPoolExecutor(max(1, int(settings["page_workers"]))) as ex:
            list(ex.map(fetch, enumerate(urls, 1)))

        if job["status"] == "cancel":
            shutil.rmtree(d, ignore_errors=True)
            with self.lock:
                self.jobs.pop(job["id"], None)
            return

        if settings.get("cbz"):
            info = (f'<?xml version="1.0"?>\n<ComicInfo><Title>{escape(job["chapter_name"])}</Title>'
                    f'<Series>{escape(job["manga_title"])}</Series>'
                    + (f'<Number>{job["chapter_number"]:g}</Number>' if job["chapter_number"] >= 0 else "")
                    + f'<PageCount>{len(urls)}</PageCount></ComicInfo>')
            tmp = d + ".cbz.part"
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
                for f in sorted(os.listdir(d)):
                    if not f.endswith(".part"):
                        z.write(os.path.join(d, f), f)
                z.writestr("ComicInfo.xml", info)
            os.replace(tmp, d + ".cbz")
            shutil.rmtree(d, ignore_errors=True)
        else:
            open(os.path.join(d, ".done"), "w").close()
        job["status"] = "done"
        job["finished_at"] = time.time()
