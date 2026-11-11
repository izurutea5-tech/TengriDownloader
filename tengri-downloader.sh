#!/usr/bin/env bash
# Tengri Downloader — Linux эхлүүлэгч
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.8+ олдсонгүй."
  case "$(uname -s)" in
    Darwin) echo "  https://www.python.org/downloads/macos/ эсвэл: brew install python" ;;
    *)      echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
            echo "  Fedora: sudo dnf install python3   ·   Arch: sudo pacman -S python" ;;
  esac
  read -r -p "Enter дарж хаана уу..." _ ; exit 1
fi
VENV_OPTS=""
[ "$(uname -s)" = "Linux" ] && VENV_OPTS="--system-site-packages"   # GTK (python3-gi)-г цонхонд ашиглахын тулд
if [ ! -x .venv/bin/python ]; then
  echo "Virtual орчин үүсгэж байна..."
  "$PY" -m venv $VENV_OPTS .venv || { echo "venv үүсгэж чадсангүй. Ubuntu/Debian: sudo apt install python3-venv"; read -r _; exit 1; }
fi
V=.venv/bin/python
if ! $V -c "import flask, bs4, requests" 2>/dev/null; then
  echo "Үндсэн сангуудыг суулгаж байна..."
  $V -m pip install --upgrade pip >/dev/null 2>&1
  $V -m pip install flask beautifulsoup4 requests || { echo "[!] Сангуудыг суулгаж чадсангүй"; read -r _; exit 1; }
fi
$V -c "import curl_cffi" 2>/dev/null || $V -m pip install curl_cffi || echo "[i] curl_cffi суусангүй — энгийн requests-ээр ажиллана"
$V -c "import webview" 2>/dev/null || $V -m pip install pywebview || echo "[i] pywebview суусангүй — хөтөч дээр нээгдэнэ"
exec "$V" app.py "$@"
