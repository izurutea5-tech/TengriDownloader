"""Tengri Downloader (by tengritoon.site) — Suwayomi маягийн манга/манхва татагч.
Ажиллуулах: python app.py   ->  http://127.0.0.1:4568
"""
import hashlib
import io
import os
import signal
import socket
import sys
import threading
import time
import webbrowser
import zipfile
from urllib.parse import urlparse

from werkzeug.exceptions import HTTPException
from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory

# Компьютерийн proxy тохиргоо байсан ч дотоод (127.0.0.1) холболт proxy-гоор дамжихгүй
for _k in ("NO_PROXY", "no_proxy"):
    _v = os.environ.get(_k, "")
    if "127.0.0.1" not in _v:
        os.environ[_k] = ",".join(x for x in (_v, "127.0.0.1,localhost,::1") if x)

from core import engine, http, lan, osutil, store, updater
from core import sources as S
import json
import shutil
from concurrent.futures import ThreadPoolExecutor

from core.downloader import Downloader, chapter_dir, is_downloaded, safe
from core.sources import suwayomi as SW

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("IZURU_PORT", 4568))
APP_NAME = "Tengri Downloader"
app = Flask(__name__, static_folder=None)

_src_cache = {}


def get_source(sid):
    if sid.startswith(SW.PREFIX):
        try:
            return SW.build(sid, store.load("settings"))
        except Exception:
            return None
    for cfg in store.load("sites"):
        if cfg["id"] == sid:
            key = repr(sorted(cfg.items()))
            if _src_cache.get(sid, (None,))[0] != key:
                _src_cache[sid] = (key, S.build(cfg))
            return _src_cache[sid][1]
    return None


dl = Downloader(get_source)


def err(msg, code=400):
    return jsonify({"error": str(msg)}), code


def need_source(sid):
    if sid.startswith(SW.PREFIX):
        try:
            src = SW.build(sid, store.load("settings"))
        except Exception as e:
            abort(502, str(e))
        if not src:
            abort(404, "Suwayomi дээр энэ эх сурвалж олдсонгүй")
        return src
    src = get_source(sid)
    if not src:
        abort(404, "source not found")
    return src


# ---------------- Утаснаас холбогдох (LAN) хамгаалалт ----------------
LOCAL = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
OPEN_PATHS = ("/web/", "/manifest.webmanifest", "/login", "/api/whoami", "/favicon.ico")
LOGIN_HTML = """<!DOCTYPE html><html lang="mn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Tengri Downloader — нэвтрэх</title><meta name="theme-color" content="#06141a"><link rel="icon" href="/web/favicon.png"><link rel="apple-touch-icon" href="/web/apple-touch-icon.png">
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(600px 400px at 70% 0,#0e7a9033,transparent),#050f13;color:#e7f7fb;font:16px -apple-system,system-ui,Segoe UI,Roboto,sans-serif}
form{width:min(340px,88vw);text-align:center}img{width:min(300px,80vw)}p{color:#89aab6;font-size:14px}
input{width:100%;box-sizing:border-box;font-size:28px;letter-spacing:10px;text-align:center;padding:14px;border-radius:14px;border:1px solid #215066;background:#0d2530;color:#fff;outline:none}
input:focus{border-color:#3fe3ff;box-shadow:0 0 0 3px #3fe3ff33}button{margin-top:14px;width:100%;padding:14px;border:0;border-radius:14px;font-size:16px;font-weight:700;color:#04222b;background:linear-gradient(135deg,#9af1ff,#3fe3ff 45%,#0e7a90)}
.e{color:#ff5d73}</style></head><body><form method="post" action="/login"><img src="/web/wordmark.png" alt="Tengri Downloader">
<p>Компьютер дээрх Tengri Downloader → Тохиргоо → «Утаснаас холбогдох» хэсэгт байгаа 6 оронтой PIN кодыг оруулна уу.</p>
%s<input name="pin" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code" autofocus placeholder="••••••"><button>Нэвтрэх</button></form></body></html>"""


def _remote():
    return request.remote_addr not in LOCAL


@app.before_request
def lan_guard():
    if not _remote():
        return None
    if not store.load("settings").get("lan_enabled"):
        return Response("Утаснаас холбогдох тохиргоо унтраалттай байна.", 403)
    p = request.path
    if p.startswith(OPEN_PATHS) or p == "/web":
        return None
    k = request.args.get("k")
    if k and lan.check_token(k):  # QR кодоор орж ирсэн: cookie тавиад цэвэр хаяг руу шилжинэ
        from flask import redirect
        resp = redirect("/")
        resp.set_cookie("tk", k, max_age=400 * 86400, httponly=True, samesite="Lax")
        return resp
    if lan.check_token(request.cookies.get("tk")):
        # Компьютер дээрх файл, програм удирддаг үйлдлүүдийг зөвхөн компьютерээс нь хийнэ
        if request.method != "GET" and p.startswith(("/api/pick", "/api/engine/", "/api/restore", "/api/backup",
                                                     "/api/local/open-folder", "/api/lan")):
            return err("Энэ үйлдлийг зөвхөн компьютер дээрээс хийнэ", 403)
        return None
    if p.startswith("/api/"):
        return err("Нэвтрээгүй байна", 401)
    return Response(LOGIN_HTML % "", mimetype="text/html")


_login_fail = {}


@app.route("/login", methods=["GET", "POST"])
def login():
    from flask import redirect
    if request.method == "GET":
        return Response(LOGIN_HTML % "", mimetype="text/html")
    ip = request.remote_addr or "?"
    fails = _login_fail.get(ip, [])
    fails = [t for t in fails if time.time() - t < 300]
    if len(fails) >= 8:
        return Response(LOGIN_HTML % '<p class="e">Хэт олон буруу оролдлого. 5 минутын дараа дахин оролдоно уу.</p>', mimetype="text/html", status=429)
    if lan.check_pin(request.form.get("pin", "")):
        _login_fail.pop(ip, None)
        resp = redirect("/")
        resp.set_cookie("tk", store.load("settings")["lan_token"], max_age=400 * 86400, httponly=True, samesite="Lax")
        return resp
    fails.append(time.time())
    _login_fail[ip] = fails
    time.sleep(0.6)
    return Response(LOGIN_HTML % '<p class="e">PIN буруу байна.</p>', mimetype="text/html", status=401)


@app.after_request
def cors_whoami(resp):
    if request.path == "/api/whoami":  # Android апп сүлжээнээс компьютерийг хайж олоход
        resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.get("/api/lan")
def lan_info():
    s = lan.ensure_secrets()
    us = lan.urls()
    return jsonify({**lan.state, "enabled": bool(s.get("lan_enabled")), "pin": s["lan_pin"], "urls": us,
                    "qr": lan.qr_svg(f"{us[0]}/?k={s['lan_token']}") if us and lan.state["running"] else "",
                    "remote": _remote()})


@app.post("/api/lan")
def lan_set():
    if _remote():
        abort(403)
    j = request.get_json(silent=True) or {}
    if j.get("regenerate"):
        lan.regenerate()
    if "enabled" in j:
        s = store.load("settings")
        s["lan_enabled"] = bool(j["enabled"])
        if j.get("port"):
            s["lan_port"] = int(j["port"])
        store.save("settings", s)
        lan.stop()
        if s["lan_enabled"]:
            lan.start(app)
    return lan_info()


@app.get("/manifest.webmanifest")
def manifest():
    return jsonify({"name": "Tengri Downloader", "short_name": "Tengri", "start_url": "/", "scope": "/",
                    "display": "standalone", "background_color": "#050f13", "theme_color": "#06141a",
                    "description": "Манга, манхва унших, татах — by tengritoon.site",
                    "icons": [{"src": "/web/icon-192.png", "sizes": "192x192", "type": "image/png"},
                              {"src": "/web/icon.png", "sizes": "512x512", "type": "image/png"},
                              {"src": "/web/icon-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]})


# ---------------- UI ----------------
@app.get("/")
def index():
    return send_from_directory(os.path.join(store.ASSETS, "web"), "index.html")


@app.get("/web/<path:name>")
def web_asset(name):
    resp = send_from_directory(os.path.join(store.ASSETS, "web"), name)
    resp.headers["Cache-Control"] = "max-age=86400"
    return resp


# ---------------- Sources ----------------
@app.get("/api/sources")
def sources_list():
    return jsonify(store.load("sites"))


@app.get("/api/suwayomi/sources")
def suwayomi_sources():
    try:
        return jsonify(SW.list_sources(store.load("settings"), force=bool(request.args.get("refresh"))))
    except Exception as e:
        return err(e, 502)


# ---------------- Engine (built-in Suwayomi) ----------------
@app.get("/api/engine")
def engine_state():
    st = store.load("settings")
    java, jar, folder = engine.find(st)
    return jsonify({**engine.state, "mode": st.get("engine_mode", "builtin"), "url": engine.effective_url(st),
                    "found": {"java": java, "jar": jar, "folder": folder}, "can_pick": True,
                    "platform": osutil.platform_name(), "java_min": engine.JAVA_MIN})


@app.post("/api/engine/<action>")
def engine_action(action):
    try:
        if action == "start":
            threading.Thread(target=engine.start, daemon=True).start()
        elif action == "stop":
            engine.stop()
        elif action == "restart":
            threading.Thread(target=engine.restart, daemon=True).start()
        elif action == "import":
            engine.import_from(request.json["path"])
        elif action == "download":
            engine.auto_download()
        elif action == "cancel":
            if engine.state.get("import"):
                engine.state["import"]["cancel"] = True
        elif action == "pick":
            return pick_endpoint()
        else:
            abort(404)
    except Exception as e:
        return err(e)
    return jsonify({"ok": True})


@app.post("/api/pick")
def pick_endpoint():
    """Хавтас/файл сонгох цонх: десктоп цонхонд pywebview-ийн, хөтөч горимд системийн (PowerShell / osascript / zenity)."""
    kind = (request.get_json(silent=True) or {}).get("kind", "folder")
    pick = app.config.get("pick_path") or osutil.pick
    try:
        return jsonify({"path": pick(kind) or ""})
    except Exception as e:
        try:
            return jsonify({"path": osutil.pick(kind) or ""})
        except Exception:
            return err(f"Сонгох цонх нээгдсэнгүй — замаа гараар бичнэ үү ({e})")


# ---------------- Extensions & repos ----------------
@app.get("/api/ext")
def ext_list():
    try:
        return jsonify(SW.extensions(store.load("settings"), refresh=bool(request.args.get("refresh"))))
    except Exception as e:
        return err(e, 502)


@app.post("/api/ext/<action>")
def ext_action(action):
    if action not in ("install", "update", "uninstall"):
        abort(404)
    try:
        return jsonify(SW.update_extension(store.load("settings"), request.json["pkg"], action) or {})
    except Exception as e:
        return err(e, 502)


@app.get("/api/stores")
def stores_list():
    try:
        return jsonify(SW.stores(store.load("settings")))
    except Exception as e:
        return err(e, 502)


@app.post("/api/stores")
def stores_add():
    try:
        return jsonify(SW.add_store(store.load("settings"), request.json["url"].strip()))
    except Exception as e:
        return err(e, 502)


@app.delete("/api/stores")
def stores_del():
    try:
        SW.remove_store(store.load("settings"), request.args["url"])
        return jsonify({"ok": True})
    except Exception as e:
        return err(e, 502)


@app.get("/api/ui")
def ui_get():
    return jsonify(store.load("ui"))


@app.post("/api/ui/<what>")
def ui_set(what):
    ui = store.load("ui")
    sid = request.json["id"]
    if what == "pin":
        ui["pinned"] = [x for x in ui["pinned"] if x != sid] + ([] if sid in ui["pinned"] else [sid])
    elif what == "used":
        ui["last_used"] = ([sid] + [x for x in ui["last_used"] if x != sid])[:5]
    store.save("ui", ui)
    return jsonify(ui)


@app.post("/api/detect")
def detect():
    try:
        return jsonify(S.detect(request.json["url"].strip()))
    except Exception as e:
        return err(e)


def _add_site(info):
    sites = store.load("sites")
    host = urlparse(info["base_url"]).netloc
    for s in sites:
        if urlparse(s.get("base_url", "")).netloc == host and s["type"] == info["type"] and s.get("lang", "en") == info.get("lang", "en"):
            return s
    sid, n = S.slug(info["name"]), 2
    while any(s["id"] == sid for s in sites):
        sid = f"{S.slug(info['name'])}-{n}"
        n += 1
    cfg = {"id": sid, "name": info["name"], "type": info["type"], "base_url": info["base_url"].rstrip("/"),
           "lang": info.get("lang", "en"), "manga_path": info.get("manga_path", "manga")}
    sites.append(cfg)
    store.save("sites", sites)
    return cfg


@app.post("/api/sources")
def sources_add():
    info = request.json
    if info.get("type") not in S.TYPES:
        return err("Буруу төрөл")
    return jsonify(_add_site(info))


@app.put("/api/sources/<sid>")
def sources_edit(sid):
    sites = store.load("sites")
    for s in sites:
        if s["id"] == sid:
            for k in ("name", "type", "base_url", "lang", "manga_path"):
                if k in request.json:
                    s[k] = request.json[k]
    store.save("sites", sites)
    return jsonify({"ok": True})


@app.delete("/api/sources/<sid>")
def sources_del(sid):
    store.save("sites", [s for s in store.load("sites") if s["id"] != sid])
    return jsonify({"ok": True})


@app.post("/api/open")
def open_url():
    """Ямар ч манга хуудасны URL өгөхөд сайтыг нь таньж (шаардлагатай бол нэмж) нээнэ."""
    url = request.json["url"].strip()
    if not url.startswith("http"):
        url = "https://" + url
    p = urlparse(url)
    try:
        if "mangadex.org" in p.netloc:
            mid = next((x for x in p.path.split("/") if len(x) == 36), None)
            site = next((s for s in store.load("sites") if s["type"] == "mangadex"), None) or _add_site(S.detect(url))
            return jsonify({"source_id": site["id"], "manga_id": mid})
        site = next((s for s in store.load("sites") if urlparse(s.get("base_url", "")).netloc == p.netloc), None)
        if not site:
            site = _add_site(S.detect(url))
        return jsonify({"source_id": site["id"], "manga_id": url})
    except Exception as e:
        return err(e)


# ---------------- Browse / details ----------------
@app.get("/api/browse/<sid>")
def browse(sid):
    src = need_source(sid)
    mode, q, page = request.args.get("mode", "popular"), request.args.get("q", ""), int(request.args.get("page", 1))
    try:
        if mode == "search" and q:
            return jsonify(src.search(q, page))
        if mode == "genre" and request.args.get("g"):
            return jsonify(src.by_genre(request.args["g"], page))
        return jsonify(src.latest(page) if mode == "latest" else src.popular(page))
    except Exception as e:
        return err(e, 502)


_details_cache = {}
_genre_cache = {}


@app.get("/api/genres/<sid>")
def genres(sid):
    src = need_source(sid)
    hit = _genre_cache.get(sid)
    if hit and time.time() - hit[0] < 6 * 3600 and not request.args.get("refresh"):
        return jsonify({"genres": hit[1]})
    try:
        g = src.genres()
    except NotImplementedError:
        g = []
    except Exception as e:
        return jsonify({"genres": [], "error": str(e)[:200]})
    _genre_cache[sid] = (time.time(), g)
    return jsonify({"genres": g})


@app.get("/api/manga")
def manga():
    sid, mid = request.args["source"], request.args["id"]
    src = need_source(sid)
    key = (sid, mid)
    try:
        if request.args.get("refresh") or key not in _details_cache or time.time() - _details_cache[key][0] > 600:
            _details_cache[key] = (time.time(), src.details(mid))
        d = dict(_details_cache[key][1])
    except Exception as e:
        return err(e, 502)
    settings = store.load("settings")
    pkey = f"{sid}|{mid}"
    prog = store.load("progress").get(pkey, {})
    pch = prog.get("chapters", {})
    d["chapters"] = [dict(c, downloaded=is_downloaded(settings, src.name, d["title"], c["name"]),
                          read=bool(pch.get(c["id"], {}).get("read")), page=pch.get(c["id"], {}).get("page", 0),
                          total=pch.get(c["id"], {}).get("total", 0)) for c in d["chapters"]]
    lib = store.load("library")
    d["in_library"] = pkey in lib
    d["category"] = lib.get(pkey, {}).get("category", "")
    d["source_id"], d["source_name"] = sid, src.name
    d["resume"] = _resume(_asc(d["chapters"]), prog)
    return jsonify(d)


def _asc(chs):
    """Бүлгүүдийг хуучнаас шинэ рүү эрэмбэлнэ (эх сурвалжууд ихэвчлэн шинээс нь эхэлж өгдөг)."""
    if len(chs) > 1 and 0 <= chs[0]["number"] < chs[-1]["number"]:
        return list(chs)
    return list(chs)[::-1]


def _resume(asc, prog):
    if not asc:
        return None
    pch = prog.get("chapters", {})
    last = (prog.get("last") or {}).get("id")
    ids = [c["id"] for c in asc]
    if last in ids and not pch.get(last, {}).get("read"):
        c = asc[ids.index(last)]
        return {"id": c["id"], "name": c["name"], "started": True}
    read_idx = [i for i, c in enumerate(asc) if pch.get(c["id"], {}).get("read")]
    i = (max(read_idx) + 1) if read_idx else 0
    while i < len(asc) and asc[i].get("locked"):  # 👑 түгжээтэй бүлгийг алгасна
        i += 1
    if i >= len(asc):
        return None
    return {"id": asc[i]["id"], "name": asc[i]["name"], "started": bool(read_idx)}


# ---------------- Reader / progress / history ----------------
_pages_cache = {}


@app.get("/api/reader")
def reader():
    sid, mid, cid = request.args["source"], request.args["manga"], request.args["chapter"]
    src = need_source(sid)
    key = (sid, mid)
    try:
        if key not in _details_cache or time.time() - _details_cache[key][0] > 1800:
            _details_cache[key] = (time.time(), src.details(mid))
        d = _details_cache[key][1]
        asc = _asc(d["chapters"])
        ids = [c["id"] for c in asc]
        if cid not in ids:
            return err("Бүлэг олдсонгүй", 404)
        i = ids.index(cid)
        c = asc[i]
        settings = store.load("settings")
        local = is_downloaded(settings, src.name, d["title"], c["name"])
        if local:
            cdir = chapter_dir(settings, src.name, d["title"], c["name"])
            path = cdir + ".cbz" if os.path.exists(cdir + ".cbz") else cdir
            rel = os.path.relpath(path, settings["download_dir"]).replace(os.sep, "/")
            pages = [{"local": rel, "name": n} for n in _local_names(path)]
        else:
            pk = (sid, cid)
            if pk not in _pages_cache or time.time() - _pages_cache[pk][0] > 1200:
                _pages_cache[pk] = (time.time(), src.pages(cid))
                if len(_pages_cache) > 60:
                    _pages_cache.pop(next(iter(_pages_cache)))
            pages = [{"url": u} for u in _pages_cache[pk][1]]
    except Exception as e:
        return err(e, 502)
    pc = store.load("progress").get(f"{sid}|{mid}", {}).get("chapters", {}).get(cid, {})
    nb = lambda j: {"id": asc[j]["id"], "name": asc[j]["name"]} if 0 <= j < len(asc) else None
    return jsonify({"title": d["title"], "cover": d.get("cover"), "source_name": src.name, "chapter": c, "index": i,
                    "count": len(asc), "prev": nb(i - 1), "next": nb(i + 1), "pages": pages, "local": local,
                    "page": 0 if pc.get("read") else pc.get("page", 0),
                    "chapters": [{"id": x["id"], "name": x["name"]} for x in asc]})


@app.get("/api/cbz")
def cbz_export():
    """Бүлгийг CBZ болгож хөтөч рүү (утас руу) шууд өгнө. Компьютерт татагдсан бол дискнээс, үгүй бол сайтаас."""
    from xml.sax.saxutils import escape as xesc
    sid, mid, cid = request.args["source"], request.args["manga"], request.args["chapter"]
    src = need_source(sid)
    key = (sid, mid)
    try:
        if key not in _details_cache or time.time() - _details_cache[key][0] > 1800:
            _details_cache[key] = (time.time(), src.details(mid))
        d = _details_cache[key][1]
        c = next((x for x in d["chapters"] if x["id"] == cid), None)
        if not c:
            return err("Бүлэг олдсонгүй", 404)
        settings = store.load("settings")
        files = []  # (name, bytes)
        if is_downloaded(settings, src.name, d["title"], c["name"]):
            cdir = chapter_dir(settings, src.name, d["title"], c["name"])
            path = cdir + ".cbz" if os.path.exists(cdir + ".cbz") else cdir
            if path.endswith(".cbz"):
                return send_file(path, as_attachment=True, download_name=f"{safe(d['title'])} - {safe(c['name'])}.cbz",
                                 mimetype="application/vnd.comicbook+zip")
            for n in _local_names(path):
                with open(os.path.join(path, n), "rb") as f:
                    files.append((n, f.read()))
        else:
            urls = src.pages(cid)
            hdr = src.img_headers()

            def fetch(iu):
                i, u = iu
                r = http.get(u, headers=hdr, timeout=60, retries=3)
                ext = {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif"}.get(
                    (r.headers.get("content-type") or "").split(";")[0].strip().lower(), ".jpg")
                return f"{i:03d}{ext}", r.content
            with ThreadPoolExecutor(4) as ex:
                files = list(ex.map(fetch, enumerate(urls, 1)))
    except Exception as e:
        return err(e, 502)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for n, b in files:
            z.writestr(n, b)
        num = f"<Number>{c['number']:g}</Number>" if (c.get("number") or -1) >= 0 else ""
        z.writestr("ComicInfo.xml", f'<?xml version="1.0"?>\n<ComicInfo><Series>{xesc(d["title"])}</Series><Title>{xesc(c["name"])}</Title>{num}<PageCount>{len(files)}</PageCount></ComicInfo>')
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"{safe(d['title'])} - {safe(c['name'])}.cbz",
                     mimetype="application/vnd.comicbook+zip")


_prog_lock = threading.Lock()


@app.post("/api/progress")
def progress_set():
    j = request.json
    sid, m, c = j["source_id"], j["manga"], j["chapter"]
    key = f"{sid}|{m['id']}"
    page, total = int(j.get("page", 0)), int(j.get("total", 0))
    with _prog_lock:
        prog = store.load("progress")
        p = prog.setdefault(key, {"chapters": {}})
        e = p["chapters"].setdefault(c["id"], {})
        e.update(page=page, total=total, t=time.time())
        if j.get("read") or (total and page >= total - 1):
            e["read"] = True
        p["last"] = {"id": c["id"], "name": c.get("name", ""), "t": time.time()}
        store.save("progress", prog)
        hist = [h for h in store.load("history") if not (h["key"] == key and h["chapter_id"] == c["id"])]
        hist.insert(0, {"t": time.time(), "key": key, "source_id": sid, "manga_id": m["id"], "title": m.get("title", ""),
                        "cover": m.get("cover"), "chapter_id": c["id"], "chapter_name": c.get("name", ""),
                        "page": page, "total": total, "read": bool(e.get("read"))})
        store.save("history", hist[:400])
    return jsonify({"ok": True, "read": bool(e.get("read"))})


@app.post("/api/progress/mark")
def progress_mark():
    j = request.json
    key = f"{j['source_id']}|{j['manga_id']}"
    with _prog_lock:
        prog = store.load("progress")
        p = prog.setdefault(key, {"chapters": {}})
        for cid in j["ids"]:
            e = p["chapters"].setdefault(cid, {})
            e["read"] = bool(j.get("read", True))
            if not e["read"]:
                e["page"] = 0
        store.save("progress", prog)
    return jsonify({"ok": True})


@app.get("/api/history")
def history_get():
    return jsonify(store.load("history"))


@app.delete("/api/history")
def history_del():
    cid, key = request.args.get("chapter"), request.args.get("key")
    with _prog_lock:
        store.save("history", [h for h in store.load("history") if key and not (h["key"] == key and h["chapter_id"] == cid)])
    return jsonify({"ok": True})


@app.post("/api/chapters/delete")
def chapters_delete():
    """Татсан бүлгүүдийг дискнээс устгана."""
    j = request.json
    src = need_source(j["source_id"])
    settings = store.load("settings")
    n = 0
    for name in j["names"]:
        d = chapter_dir(settings, src.name, j["manga_title"], name)
        _inside(os.path.relpath(d, settings["download_dir"]))
        if os.path.exists(d + ".cbz"):
            os.remove(d + ".cbz"); n += 1
        elif os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True); n += 1
    return jsonify({"deleted": n})


# ---------------- Backup / cache ----------------
BACKUP_DIR = os.path.join(store.DATA, "backups")
BACKUP_KEYS = ("settings", "sites", "library", "updates", "ui", "progress", "history")


@app.get("/api/backup")
def backup_list():
    try:
        files = sorted((f for f in os.listdir(BACKUP_DIR) if f.endswith(".json")), reverse=True)
    except FileNotFoundError:
        files = []
    return jsonify({"dir": BACKUP_DIR, "files": [os.path.join(BACKUP_DIR, f) for f in files[:20]]})


@app.post("/api/backup")
def backup_make():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, time.strftime("tengri-backup-%Y%m%d-%H%M%S.json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"izuru_backup": 1, "time": time.time(), **{k: store.load(k) for k in BACKUP_KEYS}}, f, ensure_ascii=False)
    return jsonify({"path": path})


@app.post("/api/restore")
def backup_restore():
    path = request.json["path"].strip().strip('"')
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("izuru_backup"):
            return err("Энэ нь Tengri Downloader-ийн нөөц файл биш байна")
        for k in BACKUP_KEYS:
            if k in data and k != "settings":
                store.save(k, data[k])
        if "settings" in data:  # хавтас, хөдөлгүүрийн тохиргоог одоогийнхоор үлдээнэ
            cur = store.load("settings")
            keep = {k: cur[k] for k in ("download_dir", "engine_mode", "engine_port", "engine_path", "engine_memory") if k in cur}
            store.save("settings", {**data["settings"], **keep})
    except (OSError, ValueError) as e:
        return err(e)
    return jsonify({"ok": True, "library": len(data.get("library", {}))})


def _cache_size():
    n = 0
    for f in os.scandir(_img_dir):
        n += f.stat().st_size
    return n


@app.get("/api/cache")
def cache_info():
    return jsonify({"bytes": _cache_size()})


@app.delete("/api/cache")
def cache_clear():
    for f in os.scandir(_img_dir):
        try:
            os.remove(f.path)
        except OSError:
            pass
    return jsonify({"ok": True})


def prune_cache(max_bytes=1500 * 1024 * 1024, max_age=21 * 86400):
    """Зургийн кэшийг хязгаарлана: 3 долоо хоногоос хуучин, эсвэл 1.5 GB-аас хэтэрсэн хэсгийг устгана."""
    try:
        files = sorted(((f.stat().st_mtime, f.stat().st_size, f.path) for f in os.scandir(_img_dir)), reverse=True)
        total, now = 0, time.time()
        for mt, size, path in files:
            total += size
            if total > max_bytes or now - mt > max_age:
                os.remove(path)
    except OSError:
        pass


_img_dir = os.path.join(store.DATA, "imgcache")
os.makedirs(_img_dir, exist_ok=True)


@app.get("/api/img")
def img_proxy():
    """Хавтасны зургийг Referer-тэй нь татаж, кэшлэнэ (сайтууд hotlink хаадаг)."""
    url, sid = request.args.get("url", ""), request.args.get("source", "")
    if not url.startswith("http"):
        abort(404)
    h = hashlib.sha1(url.encode()).hexdigest()
    path = os.path.join(_img_dir, h)
    if not os.path.exists(path):
        src = get_source(sid)
        try:
            r = http.get(url, headers=src.img_headers() if src else {}, retries=3, timeout=40)
        except Exception:
            abort(404)
        if (r.headers.get("content-type") or "").lower().startswith("text/"):
            abort(404)
        with open(path + ".part", "wb") as f:
            f.write(r.content)
        os.replace(path + ".part", path)
    resp = send_file(path, mimetype=_sniff(path))
    resp.headers["Cache-Control"] = "max-age=604800"
    return resp


def _sniff(path):
    """Зургийн төрлийг агуулгаар нь тодорхойлно (Safari/WebKit буруу MIME-д хатуу)."""
    try:
        with open(path, "rb") as f:
            h = f.read(16)
    except OSError:
        return "application/octet-stream"
    if h[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if h[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "image/webp"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if h[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    if h.lstrip()[:4] in (b"<svg", b"<?xm"):
        return "image/svg+xml"
    return "image/jpeg"


# ---------------- Downloads ----------------
@app.post("/api/download")
def download():
    j = request.json
    chs = [c for c in j["chapters"] if not c.get("locked") and not str(c.get("id", "")).startswith("locked:")]
    return jsonify({"added": dl.add(j["source_id"], j["manga"], chs), "locked": len(j["chapters"]) - len(chs)})


@app.get("/api/queue")
def queue():
    return jsonify({"paused": dl.paused, "jobs": dl.list()})


@app.post("/api/queue/<action>")
def queue_action(action):
    if action == "pause":
        dl.set_paused(True)
    elif action == "resume":
        dl.set_paused(False)
    elif action == "retry":
        dl.retry(request.json.get("id") if request.is_json else None)
    elif action == "clear":
        dl.clear(request.args.get("which", "finished"))
    return jsonify({"ok": True})


@app.delete("/api/queue/<int:jid>")
def queue_del(jid):
    dl.remove(jid)
    return jsonify({"ok": True})


# ---------------- Library / updates ----------------
@app.get("/api/library")
def library():
    prog = store.load("progress")
    out = []
    for key, m in store.load("library").items():
        p = prog.get(key, {})
        pch = p.get("chapters", {})
        known = m.get("known", [])
        e = {k: v for k, v in m.items() if k != "known"}
        e["total"] = len(known)
        e["unread"] = sum(1 for c in known if not pch.get(c, {}).get("read"))
        e["last_read"] = (p.get("last") or {}).get("t", 0)
        e["category"] = m.get("category", "")
        out.append(e)
    return jsonify(out)


@app.put("/api/library")
def library_edit():
    lib = store.load("library")
    j = request.json
    if j["key"] in lib:
        lib[j["key"]]["category"] = (j.get("category") or "").strip()[:40]
        store.save("library", lib)
    return jsonify({"ok": True})


@app.post("/api/library")
def library_add():
    j = request.json
    lib = store.load("library")
    key = f"{j['source_id']}|{j['manga']['id']}"
    lib[key] = {"key": key, "source_id": j["source_id"], "manga_id": j["manga"]["id"], "title": j["manga"]["title"],
                "cover": j["manga"].get("cover"), "known": [c["id"] for c in j.get("chapters", [])],
                "added": time.time(), "new": 0, "category": (j.get("category") or "").strip()[:40]}
    store.save("library", lib)
    return jsonify({"ok": True})


@app.delete("/api/library")
def library_del():
    lib = store.load("library")
    lib.pop(request.args["key"], None)
    store.save("library", lib)
    return jsonify({"ok": True})


refresh_state = {"running": False, "done": 0, "total": 0, "last": None, "errors": []}


def refresh_library():
    if refresh_state["running"]:
        return
    lib = store.load("library")
    refresh_state.update(running=True, done=0, total=len(lib), errors=[])
    settings = store.load("settings")
    new_updates = []
    try:
        def check(item):
            key, m = item
            src = get_source(m["source_id"])
            try:
                if not src:
                    raise RuntimeError("эх сурвалж байхгүй")
                d = src.details(m["manga_id"])
                _details_cache[(m["source_id"], m["manga_id"])] = (time.time(), d)
                known = set(m.get("known", []))
                fresh = [c for c in d["chapters"] if c["id"] not in known]
                if fresh and known:
                    for c in fresh:
                        new_updates.append({"time": time.time(), "key": key, "source_id": m["source_id"],
                                            "manga_id": m["manga_id"], "title": d["title"], "cover": d.get("cover"),
                                            "chapter": c})
                    m["new"] = m.get("new", 0) + len(fresh)
                    if settings.get("auto_download_new"):
                        dl.add(m["source_id"], {"id": m["manga_id"], "title": d["title"], "cover": d.get("cover")}, fresh[::-1])
                m["known"] = [c["id"] for c in d["chapters"]]
                m["cover"] = d.get("cover") or m.get("cover")
            except Exception as e:
                refresh_state["errors"].append(f"{m['title']}: {e}")
            refresh_state["done"] += 1

        with ThreadPoolExecutor(4) as ex:
            list(ex.map(check, list(lib.items())))
        cur = store.load("library")
        for k, v in lib.items():
            if k in cur:
                cur[k].update(known=v["known"], new=v.get("new", 0), cover=v.get("cover"))
        store.save("library", cur)
        ups = new_updates + store.load("updates")
        store.save("updates", ups[:1000])
    finally:
        refresh_state.update(running=False, last=time.time())


@app.post("/api/library/refresh")
def library_refresh():
    threading.Thread(target=refresh_library, daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/library/refresh")
def library_refresh_state():
    return jsonify(refresh_state)


@app.post("/api/library/seen")
def library_seen():
    lib = store.load("library")
    if request.json["key"] in lib:
        lib[request.json["key"]]["new"] = 0
        store.save("library", lib)
    return jsonify({"ok": True})


@app.get("/api/updates")
def updates():
    return jsonify(store.load("updates"))


@app.delete("/api/updates")
def updates_clear():
    store.save("updates", [])
    return jsonify({"ok": True})


# ---------------- Local (downloaded) reader ----------------
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")


def _dl_root():
    return os.path.realpath(store.load("settings")["download_dir"])


def _inside(path):
    root = _dl_root()
    p = os.path.realpath(os.path.join(root, path))
    if not (p == root or p.startswith(root + os.sep)):
        abort(403)
    return p


@app.get("/api/local")
def local_tree():
    root = _dl_root()
    out = []
    if not os.path.isdir(root):
        return jsonify(out)
    for src in sorted(os.listdir(root)):
        sp = os.path.join(root, src)
        if not os.path.isdir(sp):
            continue
        for manga in sorted(os.listdir(sp)):
            mp = os.path.join(sp, manga)
            if not os.path.isdir(mp):
                continue
            chs = []
            for ch in os.listdir(mp):
                cp = os.path.join(mp, ch)
                if ch.endswith(".cbz") or (os.path.isdir(cp) and os.path.exists(os.path.join(cp, ".done"))):
                    chs.append(f"{src}/{manga}/{ch}")
            if chs:
                from core.sources.base import chapter_number
                chs.sort(key=lambda c: chapter_number(c.rsplit("/", 1)[-1]))
                out.append({"source": src, "title": manga, "chapters": chs})
    return jsonify(out)


def _local_names(p):
    if p.endswith(".cbz"):
        with zipfile.ZipFile(p) as z:
            return sorted(n for n in z.namelist() if n.lower().endswith(IMG_EXT))
    return sorted(n for n in os.listdir(p) if n.lower().endswith(IMG_EXT))


@app.get("/api/local/pages")
def local_pages():
    return jsonify(_local_names(_inside(request.args["path"])))


@app.post("/api/local/delete")
def local_delete():
    p = _inside(request.json["path"])
    if p == _dl_root():
        abort(403)
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)
    elif os.path.isfile(p):
        os.remove(p)
    parent = os.path.dirname(p)
    try:
        if parent != _dl_root() and not os.listdir(parent):
            os.rmdir(parent)
    except OSError:
        pass
    return jsonify({"ok": True})


@app.get("/api/local/page")
def local_page():
    p, name = _inside(request.args["path"]), request.args["name"]
    if p.endswith(".cbz"):
        with zipfile.ZipFile(p) as z:
            data = z.read(name)
        ext = name.rsplit(".", 1)[-1].lower()
        return Response(data, mimetype={"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp",
                                        "gif": "image/gif", "avif": "image/avif"}.get(ext, "image/jpeg"))
    f = _inside(os.path.join(request.args["path"], os.path.basename(name)))
    return send_file(f, mimetype=_sniff(f))


@app.post("/api/local/open-folder")
def open_folder():
    path = _inside(request.json.get("path", ""))
    if not os.path.isdir(path):
        path = os.path.dirname(path)
    os.makedirs(path, exist_ok=True)
    return jsonify({"ok": osutil.open_path(path)})


# ---------------- Settings ----------------
@app.get("/api/settings")
def settings_get():
    s = store.load("settings")
    for k in ("lan_pin", "lan_token", "suwayomi_pass"):
        s.pop(k, None)
    return jsonify({**s, "curl_cffi": http.USING_CURL, "remote": _remote()})


@app.post("/api/settings")
def settings_set():
    s = store.load("settings")
    for k in store.DEFAULTS["settings"]:
        if k in ("lan_pin", "lan_token", "lan_enabled", "lan_port") or (_remote() and k in ("download_dir", "engine_path", "engine_mode", "suwayomi_url")):
            continue
        if k in request.json:
            if k == "suwayomi_pass" and request.json[k] == "" and not request.json.get("clear_pass"):
                continue  # нууц үгийг хуудсанд буцааж өгдөггүй тул хоосон ирвэл хуучнаа хадгална
            s[k] = request.json[k]
    os.makedirs(s["download_dir"], exist_ok=True)
    store.save("settings", s)
    return settings_get()


@app.errorhandler(HTTPException)
def http_exc(e):
    return err(e.description, e.code)


def auto_updater():
    while True:
        time.sleep(60)
        hrs = float(store.load("settings").get("auto_update_hours") or 0)
        last = refresh_state["last"] or 0
        if hrs > 0 and time.time() - last > hrs * 3600 and store.load("library"):
            refresh_library()


def serve():
    app.run(host="127.0.0.1", port=PORT, threaded=True, debug=False, use_reloader=False)


def _ours(port):
    try:
        r = http.get(f"http://127.0.0.1:{port}/api/whoami", retries=1, timeout=2)
        return r.json().get("app") == APP_NAME
    except Exception:
        return False


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as so:
        try:
            so.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


@app.get("/api/whoami")
def whoami():
    return jsonify({"app": APP_NAME, "platform": osutil.platform_name(), "version": VERSION})


@app.get("/api/update")
def update_check():
    if _remote():
        abort(403)
    if request.args.get("check"):
        updater.check(VERSION, force=True)
    st = updater.state
    cfg = store.load("settings")
    return jsonify({"current": VERSION, "frozen": not updater.can_update(),
                    "feed": cfg.get("update_feed") or updater.DEFAULT_FEED,
                    "auto": bool(cfg.get("auto_update_check", True)),
                    "auto_install": bool(cfg.get("auto_update_install", True)),
                    "staged": updater.staged_version(),
                    **{k: st[k] for k in ("checking", "latest", "error", "busy", "phase", "done", "total", "ready", "mode")}})


@app.post("/api/update")
def update_apply():
    if _remote():
        abort(403)
    j = request.get_json(silent=True) or {}
    try:
        if "feed" in j or "auto" in j or "auto_install" in j:
            s = store.load("settings")
            if "feed" in j:
                s["update_feed"] = (j["feed"] or "").strip()
            if "auto" in j:
                s["auto_update_check"] = bool(j["auto"])
            if "auto_install" in j:
                s["auto_update_install"] = bool(j["auto_install"])
            store.save("settings", s)
            updater.state["checked"] = 0
            return jsonify({"ok": True})
        if j.get("apply"):
            def finish():
                lan.stop()
                engine.stop()
                updater.restart(sys.argv[1:])
                os._exit(0)
            updater.apply(VERSION, on_done=finish)
        return jsonify({"ok": True})
    except Exception as e:
        return err(e)


APP_ID = "tengritoon.TengriDownloader"


def _win_app_id():
    """Windows: taskbar дээр Python-ийн дүрсний оронд өөрийн дүрсээр, тусдаа програм болж харагдахын тулд."""
    if not osutil.WIN:
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _set_window_icon(win):
    """Цонх нээгдсэний дараа гарчгийн мөр, taskbar (Windows) болон Dock (macOS)-ийн дүрсийг Tengri лого болгоно."""
    web = os.path.join(store.ASSETS, "web")
    if osutil.WIN:
        ico = os.path.join(web, "icon.ico")
        if not os.path.isfile(ico):
            return
        try:  # pywebview (WinForms) — Form.Icon
            import clr  # noqa: F401  (pythonnet)
            from System.Drawing import Icon  # type: ignore
            win.native.Icon = Icon(ico)
            return
        except Exception:
            pass
        try:  # WinAPI: цонхыг гарчгаар нь олж WM_SETICON илгээнэ
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            u.FindWindowW.restype = wintypes.HWND
            u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            u.LoadImageW.restype = wintypes.HANDLE
            u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            u.SendMessageW.restype = ctypes.c_ssize_t
            u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            hwnd = u.FindWindowW(None, APP_NAME)
            if not hwnd:
                return
            for which, size in ((1, 256), (0, 32)):  # ICON_BIG, ICON_SMALL
                h = u.LoadImageW(None, ico, 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
                if h:
                    u.SendMessageW(hwnd, 0x0080, which, h)  # WM_SETICON
        except Exception:
            pass
    elif osutil.MAC:
        try:
            from AppKit import NSApplication, NSImage  # pyobjc (pywebview-тэй хамт суудаг)
            img = NSImage.alloc().initWithContentsOfFile_(os.path.join(web, "icon.png"))
            if img:
                NSApplication.sharedApplication().setApplicationIconImage_(img)
        except Exception:
            pass


def _open_ui(url):
    if osutil.LINUX and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("  Дэлгэцгүй орчин — хөтөчөөр дээрх хаягийг нээнэ үү.")
        return
    webbrowser.open(url)


VERSION = "3.2"


def _auto_update(force=False):
    """Шинэ хувилбар байвал шалгаж, тохиргоо зөвшөөрвөл цаана нь татаж бэлтгэнэ (дараагийн асалтад суулгана)."""
    updater.check(VERSION, force=force)
    if store.load("settings").get("auto_update_install", True):
        updater.prefetch(VERSION)


def _update_poller():
    while True:
        time.sleep(6 * 3600)
        if store.load("settings").get("auto_update_check", True) and not updater.state["busy"]:
            _auto_update(force=True)


def _wait_for_port(port, timeout=30):
    """Шинэчлэлтийн дараа дахин асахад хуучин процесс портоо суллахыг хүлээнэ."""
    end = time.time() + timeout
    while time.time() < end:
        if _port_free(port):
            return True
        time.sleep(0.4)
    return False


def main():
    global PORT
    import atexit
    if "--version" in sys.argv:
        print(f"{APP_NAME} {VERSION}")
        return
    if "--wait-port" in sys.argv:
        _wait_for_port(PORT)
    # Өмнө нь цаана нь татагдсан шинэчлэлт байвал асахаас өмнө суулгаад, шинэ кодоор дахин асаана
    sv = updater.staged_version()
    updater.cleanup_old_exe()
    if sv and updater.newer(sv, VERSION) and updater.can_update() and not _ours(PORT):
        try:
            updater.install_staged()
            print(f"  Шинэ хувилбар {sv} суулгалаа — дахин асааж байна…")
            updater.restart(sys.argv[1:])
            return
        except Exception as e:
            print("  Шинэчлэлт суулгаж чадсангүй:", e)
    elif sv and not updater.newer(sv, VERSION):
        shutil.rmtree(updater.STAGE(), ignore_errors=True)  # хуучирсан бэлтгэл
    # Аль хэдийн ажиллаж байвал шинээр асаалгүй, байгаа цонхыг нээнэ
    if _ours(PORT) and "--wait-port" not in sys.argv:
        print(f"  {APP_NAME} аль хэдийн ажиллаж байна: http://127.0.0.1:{PORT}")
        if "--server" not in sys.argv:
            _open_ui(f"http://127.0.0.1:{PORT}")
        return
    if not _port_free(PORT):
        for p in range(PORT + 1, PORT + 40):
            if _port_free(p):
                print(f"  {PORT} порт эзэлсэн тул {p} портыг ашиглана")
                PORT = p
                break
    os.makedirs(store.load("settings")["download_dir"], exist_ok=True)
    store.ensure_presets()
    threading.Thread(target=auto_updater, daemon=True).start()
    threading.Thread(target=prune_cache, daemon=True).start()
    threading.Thread(target=engine.start, daemon=True).start()
    if store.load("settings").get("auto_update_check", True):
        threading.Thread(target=_auto_update, daemon=True).start()
    if store.load("settings").get("lan_enabled"):
        lan.start(app)
    threading.Thread(target=_update_poller, daemon=True).start()
    atexit.register(engine.stop)

    def _quit(*_):
        engine.stop()
        os._exit(0)
    for sig in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, sig):
            try:
                signal.signal(getattr(signal, sig), _quit)
            except (ValueError, OSError):
                pass
    url = f"http://127.0.0.1:{PORT}"
    print(f"\n  {APP_NAME}: {url}\n  Хаахын тулд энэ цонхыг хаа (эсвэл Ctrl+C).\n")
    if "--browser" not in sys.argv and "--server" not in sys.argv:
        _win_app_id()
        try:
            import webview  # Windows: Edge WebView2 · macOS: WebKit · Linux: GTK/Qt
        except ImportError:
            webview = None
        if webview:
            threading.Thread(target=serve, daemon=True).start()
            icon = os.path.join(store.ASSETS, "web", "icon.png")
            win = webview.create_window(APP_NAME, url, width=1400, height=880, min_size=(900, 600),
                                        background_color="#06141a", text_select=True)

            def pick_path(kind="folder"):
                FD = getattr(webview, "FileDialog", None)
                if FD:
                    t = FD.FOLDER if kind == "folder" else FD.OPEN
                else:
                    t = webview.FOLDER_DIALOG if kind == "folder" else webview.OPEN_DIALOG
                types = ("Archives (*.zip;*.tar.gz;*.tgz;*.jar)", "All files (*.*)") if kind == "zip" else ()
                r = win.create_file_dialog(t, file_types=types)
                return (r[0] if isinstance(r, (list, tuple)) else r) if r else ""
            app.config["pick_path"] = pick_path
            try:
                win.events.shown += lambda: _set_window_icon(win)
            except Exception:
                pass
            for _ in range(50):  # Flask асахыг хүлээх
                try:
                    http.get(url + "/api/whoami", retries=1, timeout=1)
                    break
                except Exception:
                    time.sleep(0.1)
            try:
                kw = {"private_mode": False, "storage_path": os.path.join(store.DATA, "webview")}
                if osutil.LINUX and os.path.isfile(icon):
                    kw["icon"] = icon
                try:
                    webview.start(**kw)
                except TypeError:  # хуучин pywebview: icon параметргүй
                    kw.pop("icon", None)
                    webview.start(**kw)
            except Exception as e:  # WebView2 / GTK / Qt байхгүй — хөтөч дээр үргэлжлүүлнэ
                print("Цонх нээгдсэнгүй, хөтөч дээр нээж байна:", e)
                app.config["pick_path"] = None
                _open_ui(url)
                try:
                    while True:
                        time.sleep(3600)
                except KeyboardInterrupt:
                    pass
            engine.stop()
            os._exit(0)
    if "--server" not in sys.argv:
        threading.Timer(1.2, lambda: _open_ui(url)).start()
    try:
        serve()
    except KeyboardInterrupt:
        pass
    engine.stop()


if __name__ == "__main__":
    main()
