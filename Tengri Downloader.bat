@echo off
chcp 65001 >nul
title Tengri Downloader
cd /d "%~dp0"
where python >nul 2>nul || (echo Python suulgaagui baina. https://www.python.org/downloads/ -ees suulgaad "Add to PATH"-g chagtla. & pause & exit /b)
if not exist ".venv\Scripts\python.exe" (
  echo Virtual orchin uusgej baina...
  python -m venv .venv || (echo venv uusgej chadsangui & pause & exit /b)
)
".venv\Scripts\python.exe" -c "import flask, bs4, requests" >nul 2>nul
if errorlevel 1 (
  echo Undsen sanguudyg suulgaj baina: flask, beautifulsoup4, requests ...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install flask beautifulsoup4 requests
  ".venv\Scripts\python.exe" -c "import flask, bs4, requests" >nul 2>nul || (echo. & echo [!] Sanguudyg suulgaj chadsangui. Deerkh aldaag zurag avch ilgeene uu. & pause & exit /b)
)
".venv\Scripts\python.exe" -c "import curl_cffi" >nul 2>nul || (
  echo curl_cffi suulgaj baina ^(Cloudflare-d zoriulsan^)...
  ".venv\Scripts\python.exe" -m pip install curl_cffi || echo [i] curl_cffi suusangui - engiin requests-eer ajillana.
)
".venv\Scripts\python.exe" -c "import webview" >nul 2>nul || (
  echo Tsonkhny san pywebview-g suulgaj baina...
  ".venv\Scripts\python.exe" -m pip install pywebview || echo [i] pywebview suusangui - khotoch deer neegdene.
)
start "" ".venv\Scripts\pythonw.exe" app.py
