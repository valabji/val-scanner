#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/.."

cd "$ROOT/web-ui"
npm ci
npm run build

DEST="$ROOT/valscanner/web/static"
mkdir -p "$DEST"
# Wipe everything except the .gitkeep
find "$DEST" -mindepth 1 ! -name ".gitkeep" -exec rm -rf {} +
cp -R dist/. "$DEST/"

echo "Built and staged into $DEST"
