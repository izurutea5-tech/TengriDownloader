#!/usr/bin/env bash
# macOS: «Tengri Downloader.app» үүсгэнэ (Python шаардлагагүй, бусад Mac руу хуулж болно).
cd "$(dirname "$0")/.." || exit 1
bash "Tengri Downloader.command" --version >/dev/null 2>&1 || true   # .venv бэлтгэнэ
V=.venv/bin/python
$V -m pip install pyinstaller || exit 1
$V -m PyInstaller --noconfirm --windowed --name "Tengri Downloader" --icon icon.icns --add-data "web:web" \
  --collect-all curl_cffi --collect-all webview --osx-bundle-identifier site.tengritoon.downloader app.py || exit 1
[ -f engine/bin/Suwayomi-Server.jar ] && cp -R engine "dist/Tengri Downloader.app/Contents/MacOS/engine"
echo "Болсон: dist/Tengri Downloader.app"
