#!/usr/bin/env bash
# Remove d4-launcher. Leaves the game and prefix alone unless asked.
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
LIB_DIR="$PREFIX/share/d4-launcher"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/d4-launcher"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/d4-launcher"

info() { printf '\033[32m==>\033[0m %s\n' "$*"; }

GAME_DIR=""
if [[ -f "$CONFIG_DIR/config.json" ]]; then
    GAME_DIR=$(python3 -c "
import json,os,sys
try:
    print(os.path.expanduser(json.load(open('$CONFIG_DIR/config.json')).get('game_dir','')))
except Exception:
    pass" 2>/dev/null || true)
fi
[[ -z "$GAME_DIR" ]] && GAME_DIR="$HOME/Games/diablo4"

info "Removing the launcher"
rm -rf "$LIB_DIR" "$STATE_DIR"
rm -f "$PREFIX/bin/d4l" \
      "$PREFIX/share/applications/d4-launcher.desktop" \
      "$PREFIX/share/applications/diablo-iv.desktop" \
      "$PREFIX/share/icons/hicolor/scalable/apps/d4-launcher.svg"

command -v update-desktop-database >/dev/null && \
    update-desktop-database -q "$PREFIX/share/applications" || true

echo
read -rp "Also delete settings ($CONFIG_DIR)? [y/N] " reply
[[ ${reply:-N} =~ ^[Yy]$ ]] && rm -rf "$CONFIG_DIR" && info "Settings removed."

echo
echo "The game and its Wine prefix are still on disk:"
echo "  $GAME_DIR"
if [[ -d "$GAME_DIR" ]]; then
    echo "  ($(du -sh "$GAME_DIR" 2>/dev/null | cut -f1) — including Diablo IV itself)"
fi
echo "Delete it yourself if you want the space back:"
echo "  rm -rf \"$GAME_DIR\""
echo
info "Uninstalled."
