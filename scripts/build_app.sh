#!/usr/bin/env bash
set -euo pipefail

# ValScanner — native app builder
# macOS : produces dist/ValScanner.app  (optionally signed + packaged as .dmg)
# Linux : produces dist/ValScanner/     (optionally packaged as .tar.gz)
#
# Usage:
#   bash scripts/build_app.sh
#   bash scripts/build_app.sh --dmg
#   bash scripts/build_app.sh --dmg --sign "Developer ID Application: Your Name (TEAMID)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$REPO_DIR")"
PLATFORM="$(uname)"
APP_NAME="ValScanner"
VERSION="0.2.3"
MAKE_DMG=0
SIGN_ID=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dmg)   MAKE_DMG=1 ;;
        --sign)  SIGN_ID="$2"; shift ;;
        --help|-h)
            echo "Usage: $0 [--dmg] [--sign 'Developer ID Application: Name (TEAMID)']"
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

RED='\033[0;31m'; GREEN='\033[0;32m'; BOLD='\033[1m'; RESET='\033[0m'
info()    { echo -e "${BOLD}[build]${RESET} $*"; }
success() { echo -e "${GREEN}[build]${RESET} $*"; }
die()     { echo -e "${RED}[build] ERROR:${RESET} $*" >&2; exit 1; }

# ── pre-flight checks ──────────────────────────────────────────────────────────
if [[ "$PLATFORM" == "Darwin" ]]; then
    ICON="$REPO_DIR/assets/icon.icns"
    [[ -f "$ICON" ]] || die "Missing icon: assets/icon.icns\nSee icon placeholder instructions at the bottom of the README."
elif [[ "$PLATFORM" == "Linux" ]]; then
    ICON="$REPO_DIR/assets/icon.png"
    [[ -f "$ICON" ]] || die "Missing icon: assets/icon.png\nSee icon placeholder instructions at the bottom of the README."
fi

python3 -c "import PyInstaller" 2>/dev/null || {
    info "Installing PyInstaller…"
    pip install --quiet pyinstaller
}

# ── build ──────────────────────────────────────────────────────────────────────
cd "$REPO_DIR"
info "Cleaning previous build…"
rm -rf build/ dist/

info "Running PyInstaller (this takes a minute)…"
python3 -m PyInstaller valscanner.spec --noconfirm

# ── macOS post-processing ──────────────────────────────────────────────────────
if [[ "$PLATFORM" == "Darwin" ]]; then
    APP="dist/${APP_NAME}.app"
    [[ -d "$APP" ]] || die "Build failed — $APP not found"

    # ── code signing ───────────────────────────────────────────────────────────
    if [[ -n "$SIGN_ID" ]]; then
        info "Signing with: $SIGN_ID"
        codesign \
            --deep --force --verify --verbose \
            --sign "$SIGN_ID" \
            --options runtime \
            --entitlements /dev/null \
            "$APP"
        codesign --verify --deep --strict "$APP"
        success "Code signing complete."
    else
        info "Skipping code signing."
        info "  To sign: bash scripts/build_app.sh --sign 'Developer ID Application: Your Name (TEAMID)'"
    fi

    # ── DMG ───────────────────────────────────────────────────────────────────
    if [[ $MAKE_DMG -eq 1 ]]; then
        DMG_OUT="dist/${APP_NAME}-${VERSION}.dmg"
        info "Creating $DMG_OUT…"

        if command -v create-dmg &>/dev/null; then
            create-dmg \
                --volname "$APP_NAME $VERSION" \
                --volicon "$REPO_DIR/assets/icon.icns" \
                --window-pos 200 120 \
                --window-size 600 380 \
                --icon-size 100 \
                --icon "${APP_NAME}.app" 160 185 \
                --hide-extension "${APP_NAME}.app" \
                --app-drop-link 440 185 \
                "$DMG_OUT" \
                "dist/"
        else
            # Fallback: plain hdiutil DMG (no Applications shortcut)
            hdiutil create \
                -volname "$APP_NAME" \
                -srcfolder "dist/${APP_NAME}.app" \
                -ov -format UDZO \
                "$DMG_OUT"
            info "Tip: brew install create-dmg for a nicer DMG with an Applications shortcut."
        fi
        success "DMG ready: $DMG_OUT"
    fi

    success "Done → $APP"

# ── Linux post-processing ──────────────────────────────────────────────────────
elif [[ "$PLATFORM" == "Linux" ]]; then
    OUT_DIR="dist/${APP_NAME}"
    [[ -d "$OUT_DIR" ]] || die "Build failed — $OUT_DIR not found"

    # Install .desktop entry and icon for the current user
    APP_ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
    APP_DESKTOP_DIR="$HOME/.local/share/applications"
    mkdir -p "$APP_ICON_DIR" "$APP_DESKTOP_DIR"

    cp "$REPO_DIR/assets/icon.png" "$APP_ICON_DIR/valscanner.png"

    EXEC_PATH="$REPO_DIR/$OUT_DIR/${APP_NAME}"
    sed "s|Exec=valscanner-gui %f|Exec=\"$EXEC_PATH\" %f|g" \
        "$REPO_DIR/assets/valscanner.desktop" \
        > "$APP_DESKTOP_DIR/valscanner.desktop"

    command -v update-desktop-database &>/dev/null && \
        update-desktop-database "$APP_DESKTOP_DIR" 2>/dev/null || true
    command -v gtk-update-icon-cache &>/dev/null && \
        gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

    success "Desktop entry installed to $APP_DESKTOP_DIR/valscanner.desktop"

    # Archive
    TARBALL="dist/${APP_NAME}-${VERSION}-linux-x86_64.tar.gz"
    tar -czf "$TARBALL" -C dist "${APP_NAME}"
    success "Archive: $TARBALL"
    success "Done → $OUT_DIR/${APP_NAME}"
fi
