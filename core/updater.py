"""Програмын автомат шинэчлэлт.

Шинэчлэлтийн эх сурвалж (Тохиргоо → Шинэчлэлт):
  • https://…/latest.json  — {"version": "3.1", "url": "https://…/TengriDownloader-3.1.zip", "sha256": "…", "notes": "…"}
  • github:owner/repo      — GitHub-ийн хамгийн сүүлийн release (.zip хавсралт, тайлбар нь notes)
Шинэчлэх үед: zip-ийг татаж (sha256 шалгана), програмын файлуудыг солино. data/, engine/, downloads/, .venv/ хөндөгдөхгүй.
Дараа нь програмыг дахин асаана."""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile

from . import http, store

DEFAULT_FEED = "github:izurutea5-tech/TengriDownloader"
KEEP = {"data", "engine", "downloads", ".venv", "venv", ".git", "dist", "build"}
state = {"checking": False, "checked": 0, "latest": None, "error": "", "busy": False, "phase": "", "done": 0,
         "total": 0, "ready": False, "staged": "", "mode": ""}
_lock = threading.Lock()


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def newer(a, b):
    return vtuple(a) > vtuple(b)


def feed_url():
    return (store.load("settings").get("update_feed") or DEFAULT_FEED).strip()


def fetch_latest(feed=None):
    feed = feed or feed_url()
    if feed.startswith("github:"):
        repo = feed.split(":", 1)[1].strip().strip("/")
        d = http.get(f"https://api.github.com/repos/{repo}/releases/latest",
                     headers={"Accept": "application/vnd.github+json"}, retries=2, timeout=20).json()
        assets = d.get("assets", [])
        body = d.get("body") or ""
        kind = bin_kind()
        if kind:
            suffix = BIN_ASSET[kind]
            asset = next((a for a in assets if a["name"].lower().endswith(suffix)), None)
            if not asset:
                raise RuntimeError(f"GitHub release-д {suffix} файл алга")
            m = re.search(rf"sha256-{kind}[:\s]*([0-9a-f]{{64}})", body, re.I)
        else:
            asset = next((a for a in assets if a["name"].lower().endswith(".zip")
                          and not a["name"].lower().endswith(BIN_ASSET["macos"])), None)
            if not asset:
                raise RuntimeError("GitHub release-д .zip файл алга")
            m = re.search(r"sha256(?!-)[:\s]*([0-9a-f]{64})", body, re.I)
        sha = m.group(1) if m else ""
        return {"version": d.get("tag_name", "").lstrip("vV"), "url": asset["browser_download_url"], "sha256": sha,
                "notes": d.get("body") or "", "page": d.get("html_url", "")}
    low = feed.lower()
    is_local = low.startswith("http://127.0.0.1") or low.startswith("http://localhost") or low.startswith("http://[::1]")
    if not low.startswith("https://") and not is_local:
        raise RuntimeError("Шинэчлэлтийн хаяг https:// эсвэл github:owner/repo байх ёстой")
    d = http.get(feed, retries=2, timeout=20, headers={"Cache-Control": "no-cache"}).json()
    if not d.get("version") or not d.get("url"):
        raise RuntimeError("latest.json-д version, url талбар алга")
    return {"version": str(d["version"]), "url": d["url"], "sha256": d.get("sha256", ""), "notes": d.get("notes", ""),
            "page": d.get("page", ""), "min_version": d.get("min_version", "")}


def check(current, force=False):
    with _lock:
        if state["checking"]:
            return state
        if not force and time.time() - state["checked"] < 1800 and (state["latest"] or state["error"]):
            return state
        state.update(checking=True, error="")
    try:
        latest = fetch_latest()
        latest["available"] = newer(latest["version"], current)
        state["latest"] = latest
    except Exception as e:
        state["error"] = str(e)[:300]
    finally:
        state.update(checking=False, checked=time.time())
    return state


def frozen():
    return getattr(sys, "frozen", False)


BIN_ASSET = {"exe": ".exe", "linux": "-linux.tar.gz", "macos": "-macos.zip"}


def bin_kind():
    """GitHub Release-ийн бэлэн програм (Python-гүй) бол түүний төрөл: exe / linux / macos, эх кодоор бол ""."""
    if not frozen():
        return ""
    if os.name == "nt":
        return "exe" if sys.executable.lower().endswith(".exe") else ""
    if sys.platform == "darwin":
        return "macos" if mac_bundle() else ""
    if sys.platform.startswith("linux"):
        return "linux"
    return ""


def mac_bundle():
    """…/Tengri Downloader.app (sys.executable = …app/Contents/MacOS/<нэр>)."""
    p = os.path.abspath(sys.executable)
    for _ in range(3):
        p = os.path.dirname(p)
    return p if p.endswith(".app") else ""


def self_exe():
    return bool(bin_kind())


def can_update():
    return not frozen() or self_exe()


def _old_path():
    k = bin_kind()
    return (mac_bundle() if k == "macos" else sys.executable) + ".old" if k else ""


def cleanup_old_exe():
    old = _old_path()
    if old and os.path.exists(old):
        try:
            shutil.rmtree(old) if os.path.isdir(old) else os.remove(old)
        except OSError:
            pass


def _app_root(names):
    """zip доторх програмын үндсэн хавтас (app.py байгаа)."""
    tops = [n for n in names if n.endswith("app.py") and n.count("/") <= 1]
    if not tops:
        raise RuntimeError("Шинэчлэлтийн zip дотор app.py алга")
    t = min(tops, key=len)
    return t[: -len("app.py")]


STAGE = lambda: os.path.join(store.DATA, "update", "staged")


def staged_version():
    """Татагдаад суулгахад бэлэн байгаа хувилбар (байхгүй бол "")."""
    try:
        with open(os.path.join(STAGE(), ".version"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _download_stage(latest):
    """zip-ийг татаж, шалгаж, data/update/staged/ руу задална (програмын файлд хүрэхгүй)."""
    tmpdir = os.path.join(store.DATA, "update")
    os.makedirs(tmpdir, exist_ok=True)
    zpath = os.path.join(tmpdir, "update.zip")
    state.update(phase="Татаж байна", done=0, total=0)
    r = http.session().get(latest["url"], stream=True, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Татаж чадсангүй (HTTP {r.status_code})")
    state["total"] = int(r.headers.get("content-length") or 0)
    h = hashlib.sha256()
    with open(zpath + ".part", "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 16):
            if chunk:
                f.write(chunk)
                h.update(chunk)
                state["done"] += len(chunk)
    if latest.get("sha256") and h.hexdigest().lower() != latest["sha256"].lower():
        os.remove(zpath + ".part")
        raise RuntimeError("Файлын шалгах нийлбэр (sha256) таарсангүй — татсан файл гэмтсэн эсвэл өөр файл байна")
    os.replace(zpath + ".part", zpath)
    state["phase"] = "Бэлтгэж байна"
    stage = STAGE()
    if self_exe():
        _stage_binary(zpath, stage, latest)
        return
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    files = []
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        root = _app_root(names)
        for n in names:
            if not n.startswith(root):
                continue
            rel = n[len(root):]
            top = rel.split("/", 1)[0]
            if not rel or top in KEEP or "__pycache__" in rel or rel.startswith("../") or os.path.isabs(rel):
                continue
            dest = os.path.normpath(os.path.join(stage, rel))
            if not dest.startswith(os.path.normpath(stage) + os.sep):
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(n) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            if (z.getinfo(n).external_attr >> 16) & 0o111 and os.name != "nt":
                os.chmod(dest, 0o755)
            files.append(rel)
    if "app.py" not in files:
        shutil.rmtree(stage, ignore_errors=True)
        raise RuntimeError("Шинэчлэлт бүрэн бус байна")
    with open(os.path.join(stage, ".files"), "w", encoding="utf-8") as f:
        f.write("\n".join(files))
    with open(os.path.join(stage, ".version"), "w", encoding="utf-8") as f:
        f.write(str(latest["version"]))
    os.remove(zpath)


def _stage_binary(path, stage, latest):
    kind = bin_kind()
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    try:
        if kind == "exe":
            with open(path, "rb") as f:
                if f.read(2) != b"MZ":
                    raise RuntimeError("Татсан файл .exe биш байна")
            shutil.move(path, os.path.join(stage, "new"))
        elif kind == "linux":
            import tarfile
            with tarfile.open(path) as t:
                m = next((x for x in t.getmembers() if x.isfile() and os.path.basename(x.name) == "TengriDownloader"), None)
                if not m:
                    raise RuntimeError("Шинэчлэлтийн архивт TengriDownloader алга")
                with t.extractfile(m) as src, open(os.path.join(stage, "new"), "wb") as out:
                    shutil.copyfileobj(src, out)
            os.chmod(os.path.join(stage, "new"), 0o755)
        else:  # macos: ditto нь symlink, эрхийг хадгална
            ex = os.path.join(stage, "x")
            subprocess.run(["ditto", "-x", "-k", path, ex], check=True, capture_output=True)
            app = next((n for n in os.listdir(ex) if n.endswith(".app")), None)
            if not app:
                raise RuntimeError("Шинэчлэлтийн zip-д .app алга")
            os.rename(os.path.join(ex, app), os.path.join(stage, "new"))
            shutil.rmtree(ex, ignore_errors=True)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    finally:
        if os.path.exists(path):
            os.remove(path)
    with open(os.path.join(stage, ".version"), "w", encoding="utf-8") as f:
        f.write(str(latest["version"]))


def _install_binary(stage):
    """Ажиллаж буй програмыг шинээр солино. Windows/macOS ажиллаж байгаа файлын нэрийг солихыг зөвшөөрдөг,
    Linux дээр os.replace нь ажиллаж буй процессыг гэмтээхгүй."""
    kind = bin_kind()
    new = os.path.join(stage, "new")
    if not os.path.exists(new):
        return False
    target = mac_bundle() if kind == "macos" else sys.executable
    old = target + ".old"
    cleanup_old_exe()
    if kind == "linux":
        tmp = target + ".new"
        shutil.copy2(new, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, target)
        return True
    os.rename(target, old)
    try:
        if kind == "macos":
            subprocess.run(["ditto", new, target], check=True, capture_output=True)
        else:
            shutil.copy2(new, target)
    except Exception:
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        elif os.path.exists(target):
            os.remove(target)
        os.rename(old, target)
        raise
    return True


def install_staged():
    """Бэлэн болсон шинэчлэлтийг програмын хавтас руу хуулна (алдаа гарвал хуучнаа буцаана). -> суулгасан хувилбар"""
    stage = STAGE()
    ver = staged_version()
    if not ver:
        return ""
    if self_exe():
        try:
            ok = _install_binary(stage)
        except PermissionError:
            raise RuntimeError("Програмын хавтсанд бичих эрх алга — шинэ хувилбарыг Release хуудаснаас гараар татна уу.")
        shutil.rmtree(stage, ignore_errors=True)
        return ver if ok else ""
    with open(os.path.join(stage, ".files"), encoding="utf-8") as f:
        files = [x for x in f.read().splitlines() if x]
    backup = os.path.join(store.DATA, "update", "old")
    shutil.rmtree(backup, ignore_errors=True)
    done = []
    try:
        for rel in files:
            dst = os.path.join(store.ROOT, rel)
            if os.path.exists(dst):
                b = os.path.join(backup, rel)
                os.makedirs(os.path.dirname(b), exist_ok=True)
                shutil.copy2(dst, b)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(stage, rel), dst)
            done.append(rel)
    except Exception:
        for rel in done:
            b = os.path.join(backup, rel)
            if os.path.exists(b):
                shutil.copy2(b, os.path.join(store.ROOT, rel))
        raise
    shutil.rmtree(stage, ignore_errors=True)
    return ver


def prefetch(current):
    """Шинэ хувилбарыг цаана нь чимээгүй татаж бэлтгэнэ (суулгахгүй)."""
    latest = state.get("latest") or {}
    if not can_update() or state["busy"] or not latest.get("available"):
        return
    if staged_version() == str(latest["version"]):
        state.update(staged=staged_version())
        return
    state.update(busy=True, error="", ready=False, mode="prefetch")

    def work():
        try:
            _download_stage(latest)
            state.update(staged=staged_version(), phase="Бэлэн")
        except Exception as e:
            state.update(error=str(e)[:300], phase="")
        finally:
            state["busy"] = False

    threading.Thread(target=work, daemon=True).start()


def apply(current, on_done=None):
    """«Одоо шинэчлэх»: (татаагүй бол татаад) суулгаж, програмыг дахин асаана."""
    if state["busy"] and state.get("mode") == "install":
        raise RuntimeError("Шинэчлэлт аль хэдийн явагдаж байна")
    for _ in range(600):  # цаана татаж байгаа бол дуусахыг хүлээнэ
        if not state["busy"]:
            break
        time.sleep(0.5)
    latest = (state.get("latest") or {})
    if not latest.get("available") and not staged_version():
        raise RuntimeError("Шинэ хувилбар алга")
    if not can_update():
        raise RuntimeError("Энэ .exe/.app хувилбарыг автоматаар шинэчлэх боломжгүй — шинэ хувилбарыг татаж суулгана уу.")
    state.update(busy=True, error="", ready=False, mode="install")

    def work():
        try:
            if latest.get("version") and staged_version() != str(latest["version"]):
                _download_stage(latest)
            state["phase"] = "Суулгаж байна"
            install_staged()
            state.update(phase="Дахин асааж байна", ready=True, staged="")
            if on_done:
                on_done()
        except Exception as e:
            state.update(busy=False, error=str(e)[:300], phase="")

    threading.Thread(target=work, daemon=True).start()


def restart(argv):
    """Шинэ процессоор програмыг дахин асаана (хуучин нь порт суллахыг шинэ нь хүлээнэ)."""
    rest = [a for a in argv if a != "--wait-port"] + ["--wait-port"]
    args = ([sys.executable] if frozen() else [sys.executable, os.path.join(store.ROOT, "app.py")]) + rest
    kw = {"cwd": store.ROOT, "stdin": subprocess.DEVNULL}
    if frozen():
        kw["env"] = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(args, **kw)
