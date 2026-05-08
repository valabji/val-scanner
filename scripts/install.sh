#!/usr/bin/env bash
set -euo pipefail

# ValScanner installer — macOS and Linux
# Usage: bash install.sh [--no-venv] [--no-rich] [--prefix PREFIX]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$REPO_DIR")"
VENV_DIR="$REPO_DIR/.venv"
USE_VENV=1
RICH=1
PREFIX=""

# ── parse arguments ────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-venv)  USE_VENV=0 ;;
        --no-rich)  RICH=0 ;;
        --prefix)   PREFIX="$2"; shift ;;
        --help|-h)
            echo "Usage: $0 [--no-venv] [--no-rich] [--prefix DIR]"
            echo ""
            echo "  --no-venv   Install into the system/active Python instead of a venv"
            echo "  --no-rich   Skip optional rich-metadata deps (Pillow, mutagen, PyPDF2)"
            echo "  --prefix    Install launcher scripts to PREFIX/bin (default: ~/.local/bin)"
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

# ── colour helpers ─────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; RESET='\033[0m'
info()    { echo -e "${BOLD}[valscanner]${RESET} $*"; }
success() { echo -e "${GREEN}[valscanner]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[valscanner]${RESET} $*"; }
die()     { echo -e "${RED}[valscanner] ERROR:${RESET} $*" >&2; exit 1; }

# ── find Python ────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c 'import sys; print(sys.version_info[:2] >= (3,8))' 2>/dev/null)
        if [[ "$ver" == "True" ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done
[[ -z "$PYTHON" ]] && die "Python 3.8+ is required but was not found.\nInstall it from https://python.org/downloads or via your package manager."

PY_VER=$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
info "Using $PYTHON ($PY_VER)"

# ── optional: create venv ──────────────────────────────────────────
if [[ $USE_VENV -eq 1 ]]; then
    if [[ ! -d "$VENV_DIR" ]]; then
        info "Creating virtual environment at $VENV_DIR …"
        "$PYTHON" -m venv "$VENV_DIR"
    else
        info "Re-using existing virtual environment at $VENV_DIR"
    fi
    PIP="$VENV_DIR/bin/pip"
    VALSCANNER_BIN="$VENV_DIR/bin/valscanner"
    VALSCANNER_GUI_BIN="$VENV_DIR/bin/valscanner-gui"
else
    PIP="$PYTHON -m pip"
    VALSCANNER_BIN=$(command -v valscanner 2>/dev/null || true)
    warn "--no-venv: installing into the active Python environment"
fi

# ── install package ────────────────────────────────────────────────
EXTRAS=".[rich]"
[[ $RICH -eq 0 ]] && EXTRAS="."

info "Installing valscanner ($EXTRAS) …"
$PIP install --quiet --upgrade pip
$PIP install --quiet -e "$REPO_DIR/$EXTRAS"
success "Package installed."

# ── install launcher symlinks ──────────────────────────────────────
if [[ $USE_VENV -eq 1 ]]; then
    if [[ -z "$PREFIX" ]]; then
        PREFIX="$HOME/.local"
        # macOS Homebrew users often have /usr/local writable
        if [[ "$(uname)" == "Darwin" ]] && [[ -w /usr/local/bin ]]; then
            PREFIX="/usr/local"
        fi
    fi
    BIN_DIR="$PREFIX/bin"
    mkdir -p "$BIN_DIR"

    for cmd in valscanner valscanner-gui; do
        SRC="$VENV_DIR/bin/$cmd"
        DST="$BIN_DIR/$cmd"
        if [[ -f "$SRC" ]]; then
            ln -sf "$SRC" "$DST"
            info "Linked $DST → $SRC"
        fi
    done

    # Check if BIN_DIR is on PATH
    if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
        warn "$BIN_DIR is not in your PATH."
        warn "Add this line to your shell config (~/.bashrc, ~/.zshrc, etc.):"
        warn "  export PATH=\"$BIN_DIR:\$PATH\""
    fi
fi

success "Done! Run 'valscanner --help' or 'valscanner-gui' to get started."
