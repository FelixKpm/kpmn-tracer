#!/bin/sh
# Adds KPMN Tracer to the application menu of the current user (no root needed).
# Run from the unpacked folder:  ./install.sh      Remove again:  ./install.sh --uninstall
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
BIN="$HOME/.local/bin"

if [ "$1" = "--uninstall" ]; then
    rm -f "$APPS/kpmn-tracer.desktop" "$ICONS/kpmn-tracer.png" "$BIN/kpmn-tracer"
    echo "KPMN Tracer removed from the menu (this folder was left untouched)."
    exit 0
fi

mkdir -p "$APPS" "$ICONS" "$BIN"
cp "$DIR/kpmn-tracer.png" "$ICONS/kpmn-tracer.png"
sed "s|@DIR@|$DIR|g" "$DIR/kpmn-tracer.desktop" > "$APPS/kpmn-tracer.desktop"
chmod +x "$APPS/kpmn-tracer.desktop"
ln -sf "$DIR/kpmn-tracer" "$BIN/kpmn-tracer"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" || true
echo "KPMN Tracer is now in your application menu; command line: kpmn-tracer (in ~/.local/bin)."
echo "Tip: if the window does not open, install the Qt runtime libraries, e.g. on Ubuntu/Debian:"
echo "     sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgles2"
