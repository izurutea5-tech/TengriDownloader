"""JSON файлд тохиргоо, сайтууд, номын сан, шинэчлэлтүүдийг хадгална."""
import json
import os
import threading

import sys

# .exe (PyInstaller) үед өгөгдөл exe-ийн хажууд, эх кодоор ажиллуулахад төслийн хавтсанд хадгалагдана
ROOT = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = getattr(sys, "_MEIPASS", ROOT)
# Хэрэглэгчийн өгөгдөл: програмын хавтсанд (зөөврийн). Харин macOS-ийн .app багц дотор бичих боломжгүй тул
# ~/Library/Application Support/Tengri Downloader-д хадгална.
if getattr(sys, "frozen", False) and sys.platform == "darwin":
    HOME = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Tengri Downloader")
elif getattr(sys, "frozen", False) and os.name == "nt" and not os.path.exists(os.path.join(ROOT, "data")):
    # Дан .exe: өгөгдлийг %LOCALAPPDATA%-д хадгална (exe-г хаана ч тавьсан, зөөсөн ч номын сан алга болохгүй).
    # exe-ийн хажууд data\ хавтас байвал (зөөврийн горим) түүнийгээ ашиглана.
    HOME = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Tengri Downloader")
elif getattr(sys, "frozen", False) and sys.platform.startswith("linux") and not os.path.exists(os.path.join(ROOT, "data")):
    HOME = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"),
                        "Tengri Downloader")
else:
    HOME = ROOT
DATA = os.path.join(HOME, "data")
os.makedirs(DATA, exist_ok=True)
_lock = threading.RLock()

DEFAULTS = {
    "settings": {
        "download_dir": os.path.join(os.path.expanduser("~"), "Documents", "Tengri Downloader")
        if HOME != ROOT else os.path.join(HOME, "downloads"),
        "cbz": False,
        "chapter_workers": 2,
        "page_workers": 4,
        "auto_download_new": False,
        "auto_update_hours": 0,
        "engine_mode": "builtin",
        "engine_port": 4580,
        "engine_memory": "1024m",
        "engine_path": "",
        "lan_enabled": False,
        "lan_port": 4569,
        "lan_pin": "",
        "lan_token": "",
        "update_feed": "",
        "auto_update_check": True,
        "auto_update_install": True,
        "suwayomi_url": "http://127.0.0.1:4567",
        "suwayomi_user": "",
        "suwayomi_pass": "",
    },
    "sites": [
        {"id": "mangadex-en", "name": "MangaDex (EN)", "type": "mangadex", "base_url": "https://mangadex.org", "lang": "en"},
        {"id": "sushiscan", "name": "SushiScan", "type": "mangathemesia", "base_url": "https://sushiscan.net",
         "lang": "fr", "manga_path": "catalogue"},
    ],
    "library": {},
    "ui": {"pinned": [], "last_used": []},
    "progress": {},
    "history": [],
    "updates": [],
}


def _path(name):
    return os.path.join(DATA, name + ".json")


def load(name):
    with _lock:
        try:
            with open(_path(name), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(DEFAULTS[name], dict) and name == "settings":
                return {**DEFAULTS[name], **data}
            return data
        except (FileNotFoundError, json.JSONDecodeError):
            return json.loads(json.dumps(DEFAULTS[name]))


def save(name, data):
    with _lock:
        tmp = _path(name) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _path(name))


PRESET_IDS = ("sushiscan",)


def ensure_presets():
    """Шинэ хувилбарт нэмэгдсэн бэлэн сайтуудыг хуучин хэрэглэгчийн жагсаалтад нэг удаа нэмнэ (устгасан бол дахин нэмэхгүй)."""
    ui = load("ui")
    # Nebula-г хассан: өмнө автоматаар нэмэгдсэн байсан бол устгана
    if "nebula" in ui.get("presets", []):
        sites = [s for s in load("sites") if "nebula.mn" not in s.get("base_url", "")]
        save("sites", sites)
        ui["presets"] = [x for x in ui["presets"] if x != "nebula"]
        save("ui", ui)
    done = ui.get("presets", [])
    todo = [d for d in DEFAULTS["sites"] if d["id"] in PRESET_IDS and d["id"] not in done]
    if not todo:
        return
    sites = load("sites")
    for d in todo:
        host = d["base_url"].split("//")[1]
        if not any(s["id"] == d["id"] or host in s.get("base_url", "") for s in sites):
            sites.append(dict(d))
    save("sites", sites)
    ui["presets"] = done + [d["id"] for d in todo]
    save("ui", ui)
