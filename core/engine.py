"""Дотоод хөдөлгүүр: Suwayomi-Server.jar-ыг нуугдмал (цонхгүй, tray-гүй, WebUI-гүй) асааж, Tengri Downloader-т өргөтгөлүүдийг
ажиллуулах арын сервер болгон ашиглана. Suwayomi Launcher-ийг тусад нь асаах шаардлагагүй."""
import glob
import json
import os
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import threading
import time
import zipfile

from . import http, osutil, store

ROOT = store.ROOT
ENGINE_DIR = os.path.join(store.HOME, "engine")   # бичих боломжтой газар суулгана
BUNDLED_ENGINE = os.path.join(ROOT, "engine")      # .exe / .app-тай хамт ирсэн бол          # engine/jre/..., engine/bin/Suwayomi-Server.jar
ENGINE_DATA = os.path.join(store.DATA, "engine")    # Suwayomi-ийн өгөгдөл (өргөтгөл, DB)
WIN = sys.platform == "win32"
MAC = sys.platform == "darwin"
JAVA_MIN = 21
GH_REPO = "Suwayomi/Suwayomi-Server"
PROP = "suwayomi.tachidesk.config.server"

state = {"status": "stopped", "message": "", "pid": None, "java": None, "jar": None, "import": None}
_proc = None
_lock = threading.Lock()


def effective_url(settings):
    if settings.get("engine_mode", "builtin") == "builtin":
        return f"http://127.0.0.1:{int(settings.get('engine_port', 4580))}"
    return (settings.get("suwayomi_url") or "http://127.0.0.1:4567").rstrip("/")


# ---------- хайх ----------
def _java_in(folder):
    rels = [("jre", "bin", "javaw.exe"), ("jre", "bin", "java.exe"), ("jre", "bin", "java"),
            ("jre", "Contents", "Home", "bin", "java")]  # macOS-ийн JRE багц
    rels += [("jre",) + tuple(os.path.relpath(x, os.path.join(folder, "jre")).split(os.sep))
             for x in glob.glob(os.path.join(folder, "jre", "*.jre", "Contents", "Home", "bin", "java"))]
    for rel in rels:
        p = os.path.join(folder, *rel)
        if os.path.isfile(p):
            _ensure_exec(p)
            return p
    return None


def _ensure_exec(p):
    """zip-ээс задлахад алга болдог гүйцэтгэх эрхийг (Mac/Linux) сэргээнэ."""
    if WIN:
        return
    try:
        mode = os.stat(p).st_mode
        if not mode & stat.S_IXUSR:
            os.chmod(p, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        helper = os.path.join(os.path.dirname(os.path.dirname(p)), "lib", "jspawnhelper")
        if os.path.isfile(helper) and not os.stat(helper).st_mode & stat.S_IXUSR:
            os.chmod(helper, os.stat(helper).st_mode | stat.S_IXUSR)
    except OSError:
        pass


def _system_javas():
    """Системд суусан Java-уудыг олно (PATH, JAVA_HOME, түгээмэл байршлууд)."""
    out = []
    for name in (("javaw", "java") if WIN else ("java",)):
        w = shutil.which(name)
        if w:
            out.append(w)
    jh = os.environ.get("JAVA_HOME")
    if jh:
        out.append(os.path.join(jh, "bin", "java.exe" if WIN else "java"))
    if MAC:
        try:
            home = subprocess.run(["/usr/libexec/java_home", "-v", f"{JAVA_MIN}+"], capture_output=True, text=True,
                                  timeout=10).stdout.strip()
            if home:
                out.append(os.path.join(home, "bin", "java"))
        except (OSError, subprocess.TimeoutExpired):
            pass
        out += glob.glob("/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java")
        out += glob.glob("/opt/homebrew/opt/openjdk*/bin/java") + glob.glob("/usr/local/opt/openjdk*/bin/java")
    elif not WIN:
        out += glob.glob("/usr/lib/jvm/*/bin/java")
    else:
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(env):
                out += glob.glob(os.path.join(os.environ[env], "*", "*jdk*", "bin", "javaw.exe"))
                out += glob.glob(os.path.join(os.environ[env], "*", "*jre*", "bin", "javaw.exe"))
    seen, res = set(), []
    for j in out:
        r = os.path.realpath(j)
        if os.path.isfile(r) and r not in seen:
            seen.add(r)
            res.append(j)
    return res


_ver_cache = {}


def java_major(java):
    """'java -version'-аас үндсэн хувилбарыг (21, 25…) гаргана. Мэдэгдэхгүй бол 0."""
    if java in _ver_cache:
        return _ver_cache[java]
    exe = java
    if WIN and exe.lower().endswith("javaw.exe") and os.path.isfile(exe[:-5] + ".exe"):
        exe = exe[:-5] + ".exe"
    v = 0
    try:
        r = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=20, creationflags=osutil.NOWIN)
        m = re.search(r'version "(\d+)(?:\.(\d+))?', r.stderr + r.stdout)
        if m:
            v = int(m.group(1))
            if v == 1 and m.group(2):  # 1.8 → 8
                v = int(m.group(2))
    except (OSError, subprocess.TimeoutExpired):
        pass
    _ver_cache[java] = v
    return v


def best_system_java():
    best = None
    for j in _system_javas():
        v = java_major(j)
        if v >= JAVA_MIN and (not best or v > best[1]):
            best = (j, v)
    return best


def _jar_in(folder):
    for rel in (("bin", "Suwayomi-Server.jar"), ("Suwayomi-Server.jar",)):
        p = os.path.join(folder, *rel)
        if os.path.isfile(p):
            return p
    hits = glob.glob(os.path.join(folder, "**", "Suwayomi-Server*.jar"), recursive=False)
    return hits[0] if hits else None


def candidate_dirs(settings):
    dirs = [ENGINE_DIR] + ([BUNDLED_ENGINE] if BUNDLED_ENGINE != ENGINE_DIR else [])
    if settings.get("engine_path"):
        dirs.append(settings["engine_path"])
    parent = os.path.dirname(ROOT)
    home = os.path.expanduser("~")
    pats = [os.path.join(parent, "Suwayomi*"), os.path.join(home, "Downloads", "Suwayomi*"),
            os.path.join(home, "Desktop", "Suwayomi*")]
    if WIN:
        for env in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(env):
                pats.append(os.path.join(os.environ[env], "Programs", "Suwayomi*"))
                pats.append(os.path.join(os.environ[env], "Suwayomi*"))
    elif MAC:
        pats += ["/Applications/Suwayomi*", os.path.join(home, "Applications", "Suwayomi*")]
    else:
        pats += ["/opt/suwayomi*", "/opt/Suwayomi*", "/usr/share/java/suwayomi*", "/usr/share/suwayomi*",
                 os.path.join(home, ".local", "share", "Suwayomi*"), os.path.join(home, "Suwayomi*")]
    for pat in pats:
        for d in sorted(glob.glob(pat), reverse=True):
            if os.path.isdir(d):
                dirs.append(d)
                dirs.extend(x for x in glob.glob(os.path.join(d, "Suwayomi*")) if os.path.isdir(x))
    return dirs


def find(settings):
    """-> (java, jar, folder). Java олдохгүй бол java=None (jar байгаа ч)."""
    first_jar = None
    for d in candidate_dirs(settings):
        jar = _jar_in(d)
        if not jar:
            continue
        java = _java_in(d)
        if java:
            return java, jar, d
        first_jar = first_jar or (jar, d)
    if first_jar:
        sj = best_system_java()
        return (sj[0] if sj else None), first_jar[0], first_jar[1]
    return None, None, None


# ---------- асаах / унтраах ----------
def alive(url, timeout=3):
    try:
        r = http.post(url + "/api/graphql", json={"query": "{ aboutServer { name version } }"},
                      headers={"Content-Type": "application/json"}, retries=1, timeout=timeout)
        return r.json().get("data", {}).get("aboutServer", {}).get("version") or "?"
    except http.HttpError as e:
        return "auth" if "401" in str(e) else None
    except Exception:
        return None


def start(settings=None):
    global _proc
    settings = settings or store.load("settings")
    if settings.get("engine_mode", "builtin") != "builtin":
        state.update(status="external", message=effective_url(settings))
        return
    with _lock:
        if _proc and _proc.poll() is None:
            return
        url = effective_url(settings)
        v = alive(url)
        if v:
            state.update(status="running", message=f"Аль хэдийн ажиллаж байна ({v})", pid=None)
            return
        java, jar, folder = find(settings)
        if not jar:
            state.update(status="missing", message="Хөдөлгүүр олдсонгүй. Тохиргоо → Хөдөлгүүр → «Автоматаар татах» дарна уу.")
            return
        if not java:
            state.update(status="missing", message=f"Java {JAVA_MIN}+ олдсонгүй. «Автоматаар татах» нь Java-тай хамт татна.")
            return
        if not _java_in(folder):  # системийн Java — хувилбарыг шалгана
            v = java_major(java)
            if v and v < JAVA_MIN:
                state.update(status="missing", message=f"Java {v} хэт хуучин, {JAVA_MIN}+ хэрэгтэй. «Автоматаар татах»-ыг ашиглана уу.")
                return
        os.makedirs(ENGINE_DATA, exist_ok=True)
        port = int(settings.get("engine_port", 4580))
        args = [java, f"-Xmx{settings.get('engine_memory', '1024m')}",
                f"-D{PROP}.rootDir={ENGINE_DATA}", f"-D{PROP}.ip=127.0.0.1", f"-D{PROP}.port={port}",
                f"-D{PROP}.webUIEnabled=false", f"-D{PROP}.initialOpenInBrowserEnabled=false",
                f"-D{PROP}.systemTrayEnabled=false", f"-D{PROP}.authMode=NONE",
                f"-D{PROP}.downloadsPath={os.path.join(ENGINE_DATA, 'downloads')}",
                "-jar", jar]
        log = open(os.path.join(store.DATA, "engine.log"), "w", encoding="utf-8", errors="replace")
        kw, env = {}, dict(os.environ)
        env.pop("_JAVA_OPTIONS", None)
        if WIN:
            kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        else:
            kw["start_new_session"] = True     # терминал хаагдахад Ctrl+C хамт ирэхгүй, бид өөрсдөө унтраана
            ca = os.path.join(os.path.dirname(jar), "catch_abort.so")  # Suwayomi-ийн Linux багцад байдаг
            if not MAC and os.path.isfile(ca):
                env["LD_PRELOAD"] = ca
        if MAC:
            args.insert(1, "-Dapple.awt.UIElement=true")  # Dock-д дүрс гаргахгүй
        _proc = subprocess.Popen(args, cwd=os.path.dirname(jar), stdout=log, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, env=env, **kw)
        state.update(status="starting", message="Хөдөлгүүр асаж байна…", pid=_proc.pid, java=java, jar=jar)
    threading.Thread(target=_wait_ready, args=(url,), daemon=True).start()


def _wait_ready(url):
    t0 = time.time()
    while time.time() - t0 < 180:
        if _proc is None or _proc.poll() is not None:
            state.update(status="error", message="Хөдөлгүүр зогслоо. data/engine.log-ийг шалгана уу. " + _log_tail())
            return
        v = alive(url, timeout=2)
        if v:
            state.update(status="running", message=f"Suwayomi {v}")
            return
        time.sleep(1.5)
    state.update(status="error", message="Хөдөлгүүр 3 минутын дотор асаагүй. " + _log_tail())


def _log_tail(n=3):
    try:
        with open(os.path.join(store.DATA, "engine.log"), encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in f if "ERROR" in l or "Exception" in l]
        return " | ".join(lines[-n:])[:400]
    except Exception:
        return ""


def stop():
    global _proc
    with _lock:
        p, _proc = _proc, None
    if p and p.poll() is None:
        try:
            if WIN:
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=0x08000000)
            else:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except (OSError, AttributeError):
                    p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(p.pid, signal.SIGKILL)
                    except (OSError, AttributeError):
                        p.kill()
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    if state["status"] in ("running", "starting"):
        state.update(status="stopped", message="", pid=None)


def restart():
    stop()
    time.sleep(1)
    start()


# ---------- Хөдөлгүүрийг суулгах: Suwayomi-ийн хавтас / zip / tar.gz / jar-аас, эсвэл интернэтээс ----------
def _busy():
    return bool(state.get("import") and state["import"].get("running"))


def _new_job(kind):
    if _busy():
        raise RuntimeError("Өөр суулгалт явагдаж байна")
    st = state["import"] = {"running": True, "kind": kind, "phase": "", "done": 0, "total": 0, "error": "", "ok": False}
    return st


def _member_rel(name):
    """Архив доторх замыг engine/ доторх зам руу хөрвүүлнэ: …/jre/x → jre/x, …Suwayomi-Server*.jar → bin/…, catch_abort.so → bin/."""
    n = name.replace("\\", "/")
    if "/jre/" in "/" + n:
        return "jre/" + ("/" + n).split("/jre/", 1)[1]
    base = n.rsplit("/", 1)[-1]
    if re.fullmatch(r"Suwayomi-Server[^/]*\.jar", base):
        return "bin/Suwayomi-Server.jar"
    if base == "catch_abort.so":
        return "bin/catch_abort.so"
    return None


def _safe_join(root, rel):
    d = os.path.normpath(os.path.join(root, rel))
    if not d.startswith(os.path.normpath(root) + os.sep):
        raise RuntimeError("Архивт аюултай зам байна: " + rel)
    return d


def _extract_zip(path, tmp, st, only_jre=False):
    with zipfile.ZipFile(path) as z:
        items = []
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = _member_rel(info.filename) if not only_jre else _jre_rel(info.filename)
            if rel:
                items.append((info, rel))
        st.update(phase="Задалж байна", done=0, total=len(items))
        for info, rel in items:
            dest = _safe_join(tmp, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            mode = (info.external_attr >> 16) & 0o177777
            if stat.S_ISLNK(mode) and not WIN:  # Unix symlink (macOS JRE)
                target = z.read(info).decode()
                if os.path.lexists(dest):
                    os.remove(dest)
                os.symlink(target, dest)
            else:
                with z.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                if mode & 0o111 and not WIN:
                    os.chmod(dest, 0o755)
            st["done"] += 1
    return len(items)


def _extract_tar(path, tmp, st, only_jre=False):
    with tarfile.open(path, "r:*") as t:
        items = []
        for m in t.getmembers():
            if m.isdir():
                continue
            rel = _member_rel(m.name) if not only_jre else _jre_rel(m.name)
            if rel and (m.isfile() or m.issym()):
                items.append((m, rel))
        st.update(phase="Задалж байна", done=0, total=len(items))
        for m, rel in items:
            dest = _safe_join(tmp, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if m.issym():
                if WIN:
                    continue
                if os.path.isabs(m.linkname):
                    continue
                if os.path.lexists(dest):
                    os.remove(dest)
                os.symlink(m.linkname, dest)
            else:
                with t.extractfile(m) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                if m.mode & 0o111 and not WIN:
                    os.chmod(dest, 0o755)
            st["done"] += 1
    return len(items)


def _jre_rel(name):
    """Azul JRE архив: эхний хавтсыг (zulu…-jre…) jre/ болгож солино."""
    parts = name.replace("\\", "/").split("/", 1)
    return "jre/" + parts[1] if len(parts) == 2 and parts[1] else None


def _extract(path, tmp, st, only_jre=False):
    low = path.lower()
    if low.endswith(".zip"):
        return _extract_zip(path, tmp, st, only_jre)
    if low.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar")):
        return _extract_tar(path, tmp, st, only_jre)
    raise RuntimeError("Танигдахгүй архив: " + os.path.basename(path))


def _copy_folder(path, tmp, st):
    jar = _jar_in(path)
    if not jar:
        raise RuntimeError("Энэ хавтсанд bin/Suwayomi-Server.jar алга")
    files = [(jar, os.path.join(tmp, "bin", "Suwayomi-Server.jar"))]
    ca = os.path.join(os.path.dirname(jar), "catch_abort.so")
    if os.path.isfile(ca):
        files.append((ca, os.path.join(tmp, "bin", "catch_abort.so")))
    jre = os.path.join(path, "jre")
    if os.path.isdir(jre):
        for r, ds, fs in os.walk(jre):
            for f in fs + [d for d in ds if os.path.islink(os.path.join(r, d))]:
                src = os.path.join(r, f)
                files.append((src, os.path.join(tmp, "jre", os.path.relpath(src, jre))))
    st.update(phase="Хуулж байна", done=0, total=len(files))
    for src, d in files:
        os.makedirs(os.path.dirname(d), exist_ok=True)
        if os.path.islink(src) and not WIN:
            os.symlink(os.readlink(src), d)
        elif os.path.isfile(src):
            shutil.copy2(src, d)
        st["done"] += 1


def _finish(tmp, st):
    if not _jar_in(tmp):
        raise RuntimeError("Suwayomi-Server.jar олдсонгүй")
    j = _java_in(tmp)
    if j is None and not best_system_java():
        raise RuntimeError(f"Java {JAVA_MIN}+ олдсонгүй. Java-тай багцыг (jre хавтастай) сонгоно уу, эсвэл «Автоматаар татах»-ыг ашиглана уу.")
    st["phase"] = "Хөдөлгүүрийг асааж байна"
    stop()
    old = ENGINE_DIR + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(ENGINE_DIR):
        os.replace(ENGINE_DIR, old)
    os.replace(tmp, ENGINE_DIR)
    shutil.rmtree(old, ignore_errors=True)
    st.update(running=False, ok=True, phase="Бэлэн")
    start()


def import_from(path):
    """Suwayomi-ийн хавтас, zip (Windows), tar.gz (Mac/Linux) эсвэл .jar файлаас хөдөлгүүр суулгана."""
    path = os.path.expanduser(path.strip().strip('"').strip("'"))
    if not os.path.exists(path):
        raise RuntimeError("Зам олдсонгүй: " + path)
    st = _new_job("import")

    def work():
        tmp = ENGINE_DIR + ".new"
        try:
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp)
            if os.path.isdir(path):
                _copy_folder(path, tmp, st)
            elif path.lower().endswith(".jar"):
                os.makedirs(os.path.join(tmp, "bin"))
                shutil.copy2(path, os.path.join(tmp, "bin", "Suwayomi-Server.jar"))
            else:
                _extract(path, tmp, st)
            _finish(tmp, st)
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            st.update(running=False, error=str(e))

    threading.Thread(target=work, daemon=True).start()


# ---- интернэтээс автоматаар татах ----
def _arch():
    m = platform.machine().lower()
    return "aarch64" if m in ("arm64", "aarch64", "armv8l") else "x64" if m in ("x86_64", "amd64", "x64", "") else m


def latest_release():
    """-> {"tag": "v2.4.2366", "assets": {name: url}}"""
    try:
        d = http.get(f"https://api.github.com/repos/{GH_REPO}/releases/latest",
                     headers={"Accept": "application/vnd.github+json"}, retries=2).json()
        return {"tag": d["tag_name"], "assets": {a["name"]: a["browser_download_url"] for a in d.get("assets", [])}}
    except Exception:
        # API хязгаарлалтад орсон бол: /releases/latest нь шинэ хувилбар руу шилжүүлдэг
        r = http.get(f"https://github.com/{GH_REPO}/releases/latest", retries=2)
        m = re.search(r"/releases/tag/([^/?#]+)", r.url or "")
        if not m:
            raise RuntimeError("Suwayomi-ийн сүүлийн хувилбарыг олж чадсангүй")
        tag = m.group(1)
        base = f"https://github.com/{GH_REPO}/releases/download/{tag}/Suwayomi-Server-{tag}"
        names = {f"Suwayomi-Server-{tag}.jar": base + ".jar"}
        for suf in ("-windows-x64.zip", "-linux-x64.tar.gz", "-macOS-arm64.tar.gz", "-macOS-x64.tar.gz"):
            names[f"Suwayomi-Server-{tag}{suf}"] = base + suf
        return {"tag": tag, "assets": names, "guessed": True}


def plan_download(rel, os_name=None, arch=None, has_java=None):
    """Аль файлуудыг татахыг шийднэ. -> [("jar"|"bundle", name, url)]"""
    os_name = os_name or osutil.platform_name()
    arch = arch or _arch()
    assets = rel["assets"]
    jar = next(((n, u) for n, u in assets.items() if re.fullmatch(r"Suwayomi-Server-[^-]+(?:-[^-]+)?\.jar", n)
                and "Launcher" not in n), None)
    bundle_suffix = {("windows", "x64"): "-windows-x64.zip", ("linux", "x64"): "-linux-x64.tar.gz",
                     ("macos", "aarch64"): "-macOS-arm64.tar.gz", ("macos", "x64"): "-macOS-x64.tar.gz"}.get((os_name, arch))
    bundle = next(((n, u) for n, u in assets.items() if bundle_suffix and n.endswith(bundle_suffix)), None)
    if has_java and jar:
        return [("jar",) + jar]
    if jar:  # Java байхгүй: jar + Azul JRE (bundle-аас хамаагүй жижиг), бүтэхгүй бол bundle
        return [("jar",) + jar, ("jre", "azul", "")] + ([("bundle",) + bundle] if bundle else [])
    if bundle:
        return [("bundle",) + bundle]
    raise RuntimeError(f"{os_name}/{arch}-д тохирох файл олдсонгүй")


def azul_jre_url(os_name=None, arch=None):
    os_name = os_name or osutil.platform_name()
    arch = arch or _arch()
    q = {"java_version": "21", "os": {"windows": "windows", "macos": "macos", "linux": "linux"}[os_name],
         "arch": "aarch64" if arch == "aarch64" else "x64", "archive_type": "zip" if os_name == "windows" else "tar.gz",
         "java_package_type": "jre", "javafx_bundled": "false", "latest": "true", "release_status": "ga",
         "availability_types": "CA", "page_size": "1"}
    if os_name == "linux":
        q["distro_version"] = ""
        q["lib_c_type"] = "glibc"
    d = http.get("https://api.azul.com/metadata/v1/zulu/packages/", params={k: v for k, v in q.items() if v != ""}, retries=2).json()
    if not d:
        raise RuntimeError("Azul JRE олдсонгүй")
    return d[0]["download_url"]


def _download(url, dest, st, label):
    st.update(phase=f"{label} татаж байна", done=0, total=0)
    sess = http.session()
    r = sess.get(url, stream=True, timeout=60, headers={"Accept": "application/octet-stream"})
    if r.status_code >= 400:
        raise RuntimeError(f"Татаж чадсангүй (HTTP {r.status_code}): {url}")
    st["total"] = int(r.headers.get("content-length") or 0)
    with open(dest + ".part", "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 18):
            if chunk:
                f.write(chunk)
                st["done"] += len(chunk)
            if st.get("cancel"):
                raise RuntimeError("Цуцаллаа")
    os.replace(dest + ".part", dest)


def auto_download():
    """GitHub-аас Suwayomi-ийн сүүлийн хувилбарыг (шаардлагатай бол Java-тай) татаж суулгана."""
    st = _new_job("download")

    def work():
        tmp = ENGINE_DIR + ".new"
        dl = os.path.join(store.DATA, "engine-download")
        try:
            os.makedirs(dl, exist_ok=True)
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(os.path.join(tmp, "bin"))
            st["phase"] = "Сүүлийн хувилбарыг шалгаж байна"
            rel = latest_release()
            st["tag"] = rel["tag"]
            sj = best_system_java()
            steps = plan_download(rel, has_java=bool(sj))
            kinds = [k for k, _, _ in steps]
            if "jar" in kinds:
                _, name, url = steps[kinds.index("jar")]
                f = os.path.join(dl, name)
                if not (os.path.isfile(f) and zipfile.is_zipfile(f)):
                    _download(url, f, st, f"Suwayomi {rel['tag']}")
                shutil.copy2(f, os.path.join(tmp, "bin", "Suwayomi-Server.jar"))
                if not sj:
                    try:
                        jurl = azul_jre_url()
                        jf = os.path.join(dl, jurl.rsplit("/", 1)[-1])
                        if not os.path.isfile(jf):
                            _download(jurl, jf, st, "Java 21")
                        _extract(jf, tmp, st, only_jre=True)
                    except Exception:
                        if "bundle" not in kinds:
                            raise
                        _, bname, burl = steps[kinds.index("bundle")]
                        bf = os.path.join(dl, bname)
                        if not os.path.isfile(bf):
                            _download(burl, bf, st, "Suwayomi + Java багц")
                        shutil.rmtree(tmp, ignore_errors=True)
                        os.makedirs(tmp)
                        _extract(bf, tmp, st)
            else:
                _, bname, burl = steps[0]
                bf = os.path.join(dl, bname)
                _download(burl, bf, st, "Suwayomi + Java багц")
                _extract(bf, tmp, st)
            _finish(tmp, st)
            shutil.rmtree(dl, ignore_errors=True)
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            st.update(running=False, error=str(e)[:400])

    threading.Thread(target=work, daemon=True).start()
