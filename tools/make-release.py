#!/usr/bin/env python3
"""Шинэ хувилбар бэлтгэнэ: програмын zip болон latest.json үүсгэнэ.

Ажиллуулах:  python tools/make-release.py 3.2
Үр дүн (dist_release/ дотор):
  • TengriDownloader-3.2.zip   — програмын файлууд (data/engine/downloads/.venv ОРООГҮЙ)
  • latest.json                — {"version","url","sha256","notes"}

Дараа нь сайтдаа байршуулна, ЭСВЭЛ GitHub Release болгон гаргана (доорх gh командыг хэвлэнэ):
  https://tengritoon.site/downloader/latest.json
  https://tengritoon.site/downloader/TengriDownloader-3.2.zip
RELEASE_NOTES.txt файл байвал түүний агуулгыг notes болгоно.
app.py доторх VERSION-ийг шинэ хувилбартай тааруулахаа бүү мартаарай."""
import hashlib
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"data", "engine", "downloads", ".venv", "venv", ".git", "dist", "dist_release", "build",
             "__pycache__", "node_modules", ".webview", ".github", "bins", "pkg"}
SKIP_EXT = {".pyc", ".pyo", ".log"}
TOP = "TengriDownloader"
BASE_URL = os.environ.get("TENGRI_BASE_URL", "https://tengritoon.site/downloader")


def main():
    if len(sys.argv) < 2:
        sys.exit("Хэрэглээ: python tools/make-release.py <хувилбар>   жишээ: 3.2")
    version = sys.argv[1].lstrip("vV")
    appver = ""
    with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as f:
        m = re.search(r'VERSION\s*=\s*"([^"]+)"', f.read())
        appver = m.group(1) if m else "?"
    if appver != version:
        print(f"  [!] Анхаар: app.py доторх VERSION = {appver}, харин та {version} гэж байна. Тааруулна уу.")
    out = os.path.join(ROOT, "dist_release")
    os.makedirs(out, exist_ok=True)
    zname = f"TengriDownloader-{version}.zip"
    zpath = os.path.join(out, zname)
    n = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith("[stitched]")]
            if os.path.abspath(root) == out:
                continue
            for fn in files:
                if os.path.splitext(fn)[1] in SKIP_EXT or fn.endswith((".zip", ".ico.part")):
                    continue
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, ROOT)
                z.write(full, f"{TOP}/{rel}".replace(os.sep, "/"))
                n += 1
    sha = hashlib.sha256(open(zpath, "rb").read()).hexdigest()
    notes = ""
    nf = os.path.join(ROOT, "RELEASE_NOTES.txt")
    if os.path.isfile(nf):
        notes = open(nf, encoding="utf-8").read().strip()
    latest = {"version": version, "url": f"{BASE_URL}/{zname}", "sha256": sha, "notes": notes}
    with open(os.path.join(out, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)
    # GitHub Release-ийн тайлбар: програм sha256-ыг эндээс уншиж шалгадаг
    gh_notes = os.path.join(out, "github-notes.md")
    with open(gh_notes, "w", encoding="utf-8") as f:
        f.write((notes + "\n\n" if notes else "") + f"sha256: {sha}\n")
    print(f"  ✓ {zname} ({n} файл, {os.path.getsize(zpath)//1024} KB)")
    print(f"  ✓ latest.json  (sha256 {sha[:16]}…)")
    print(f"  ✓ github-notes.md")
    print("\n  ── Сонголт 1: өөрийн сайт ──")
    print(f"  dist_release/ доторх latest.json ба {zname}-ийг {BASE_URL}/ руу байршуулна.")
    print("\n  ── Сонголт 2: GitHub Release ──")
    print(f'  gh release create v{version} "dist_release/{zname}" --title "Tengri Downloader {version}" --notes-file dist_release/github-notes.md')
    print("  (эсвэл github.com → repo → Releases → Draft a new release: tag v" + version +
          f", {zname}-ийг хавсаргаж, github-notes.md-ийн агуулгыг тайлбарт хуулна)")


if __name__ == "__main__":
    main()
