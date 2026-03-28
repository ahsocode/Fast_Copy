#!/usr/bin/env bash
# Build Fast_Copy.app for macOS (portable — no Python required)
# Usage (from project root):  ./build/build_macos.sh
# Output:
#   dist/Fast_Copy.app   — double-clickable app bundle
#   dist/Fast_Copy.dmg   — drag-to-Applications installer

set -e
cd "$(dirname "$0")/.."

echo "==> Setting up Python virtual environment…"
python3 -m venv /tmp/fc_venv
/tmp/fc_venv/bin/pip install -r requirements.txt -q

echo "==> Generating icon…"
/tmp/fc_venv/bin/python build/generate_icon.py

echo "==> Building Fast_Copy.app with PyInstaller…"
/tmp/fc_venv/bin/pyinstaller copysoft.spec \
    --clean \
    --noconfirm \
    --distpath dist \
    --workpath /tmp/fastcopy_build

echo "==> Removing extended attributes and re-signing…"
xattr -cr dist/Fast_Copy.app
codesign --force --deep --sign - dist/Fast_Copy.app

echo "==> Creating DMG installer…"
DMG="dist/Fast_Copy.dmg"
rm -f "$DMG"
STAGING="$(mktemp -d)"
cp -R "dist/Fast_Copy.app" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create \
    -volname "Fast Copy" \
    -srcfolder "$STAGING" \
    -ov -format UDZO \
    "$DMG"
rm -rf "$STAGING"

echo ""
echo "✅  Build complete!"
echo "    App bundle : dist/Fast_Copy.app"
echo "    DMG        : dist/Fast_Copy.dmg  ($(du -sh "$DMG" | cut -f1))"
echo ""
echo "    To run now:   open dist/Fast_Copy.app"
echo "    To install:   open dist/Fast_Copy.dmg → drag to Applications"
