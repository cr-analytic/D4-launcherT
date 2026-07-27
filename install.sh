#!/usr/bin/env bash
# One-click installer for d4-launcher on CachyOS / Arch.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PREFIX="${PREFIX:-$HOME/.local}"
LIB_DIR="$PREFIX/share/d4-launcher"
BIN_DIR="$PREFIX/bin"
BIN="$BIN_DIR/d4l"
APPS_DIR="$PREFIX/share/applications"
ICON_DIR="$PREFIX/share/icons/hicolor/scalable/apps"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '\033[32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m  !\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m  ✗\033[0m %s\n' "$*" >&2; exit 1; }

# --- sanity ---------------------------------------------------------------
[[ $EUID -eq 0 ]] && die "Don't run this as root. It installs into your home directory."
command -v python3 >/dev/null || die "python3 is required."

python3 - <<'PY' || die "Python 3.9 or newer is required."
import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)
PY

# --- dependencies ---------------------------------------------------------
REQUIRED=(umu-launcher)
OPTIONAL=(python-gobject libadwaita gtk4 vulkan-tools)

if command -v pacman >/dev/null; then
    missing=()
    for pkg in "${REQUIRED[@]}" "${OPTIONAL[@]}"; do
        pacman -Qq "$pkg" &>/dev/null || missing+=("$pkg")
    done
    if ((${#missing[@]})); then
        bold "The following packages are missing:"
        printf '    %s\n' "${missing[@]}"
        echo
        read -rp "Install them with pacman now? [Y/n] " reply
        if [[ ${reply:-Y} =~ ^[Yy]?$ ]]; then
            sudo pacman -S --needed "${missing[@]}"
        else
            for pkg in "${REQUIRED[@]}"; do
                pacman -Qq "$pkg" &>/dev/null || \
                    die "$pkg is required. Install it and re-run this script."
            done
            warn "Continuing without the optional packages (the GUI may not start)."
        fi
    fi
else
    warn "pacman not found — this isn't an Arch-based system."
    warn "Install umu-launcher yourself before continuing."
fi

# --- install --------------------------------------------------------------
info "Installing d4-launcher into $LIB_DIR"
rm -rf "$LIB_DIR"
mkdir -p "$LIB_DIR" "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"
cp -r "$SRC_DIR/src/d4l" "$LIB_DIR/"
find "$LIB_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

cat > "$BIN" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$LIB_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m d4l "\$@"
EOF
chmod +x "$BIN"

install -m644 "$SRC_DIR/share/icons/hicolor/scalable/apps/d4-launcher.svg" "$ICON_DIR/"

for entry in d4-launcher diablo-iv; do
    sed "s|@BIN@|$BIN|g" "$SRC_DIR/share/applications/$entry.desktop" \
        > "$APPS_DIR/$entry.desktop"
done

command -v update-desktop-database >/dev/null && \
    update-desktop-database -q "$APPS_DIR" || true
command -v gtk-update-icon-cache >/dev/null && \
    gtk-update-icon-cache -qtf "$PREFIX/share/icons/hicolor" 2>/dev/null || true

info "Installed."

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not on your PATH — run d4l as $BIN, or add it:"
       warn "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc" ;;
esac

# --- first run ------------------------------------------------------------
echo
bold "Next step: set up the game."
echo "  This creates a Wine prefix, installs Battle.net, and opens it so you"
echo "  can log in once. After that, launching is a single click."
echo
read -rp "Run setup now? [Y/n] " reply
if [[ ${reply:-Y} =~ ^[Yy]?$ ]]; then
    "$BIN" setup
else
    echo
    echo "  Run it later with:  d4l setup"
fi

echo
bold "Done."
echo "  d4l play      launch Diablo IV"
echo "  d4l gui       graphical launcher"
echo "  d4l doctor    check your system"
echo
echo "  'Diablo IV' and 'D4 Launcher' are now in your application menu."
