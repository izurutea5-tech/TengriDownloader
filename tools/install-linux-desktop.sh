#!/usr/bin/env bash
# Програмын цэсэнд (Activities / Applications) «Tengri Downloader»-ийг нэмнэ.
DIR="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/512x512/apps"
cp "$DIR/web/icon.png" "$HOME/.local/share/icons/hicolor/512x512/apps/tengri-downloader.png"
cat > "$HOME/.local/share/applications/tengri-downloader.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Tengri Downloader
Comment=Манга / манхва унших, татах — by tengritoon.site
Exec="$DIR/tengri-downloader.sh"
Path=$DIR
Icon=tengri-downloader
Terminal=false
Categories=Graphics;Viewer;Network;
StartupWMClass=Tengri Downloader
DESK
chmod +x "$DIR/tengri-downloader.sh"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null
echo "Нэмэгдлээ: програмын цэснээс «Tengri Downloader»-ийг хайж нээнэ үү."
