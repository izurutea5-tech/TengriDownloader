@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (echo Ehleed "Tengri Downloader.bat"-g neg udaa ajilluulna uu. & pause & exit /b)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d='%~dp0'.TrimEnd('\'); $s=New-Object -ComObject WScript.Shell;" ^
  "foreach($p in @([Environment]::GetFolderPath('Desktop'), (Join-Path ([Environment]::GetFolderPath('Programs')) ''))){" ^
  " $l=$s.CreateShortcut((Join-Path $p 'Tengri Downloader.lnk'));" ^
  " $l.TargetPath=(Join-Path $d '.venv\Scripts\pythonw.exe'); $l.Arguments='\"'+(Join-Path $d 'app.py')+'\"';" ^
  " $l.WorkingDirectory=$d; $l.IconLocation=(Join-Path $d 'icon.ico')+',0'; $l.Description='Tengri Downloader - by tengritoon.site'; $l.Save() }"
if errorlevel 1 (echo Tovchlol uusgej chadsangui. & pause & exit /b)
echo Bolson: Desktop bolon Start tsesend "Tengri Downloader" tovchlol nemegdlee.
pause
