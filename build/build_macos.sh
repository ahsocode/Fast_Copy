#!/usr/bin/env bash
# Build CopySoft.app for macOS (portable, no Python required)
set -e

cd "$(dirname "$0")/.."

echo "==> Installing dependencies..."
pip install -r requirements.txt

echo "==> Building macOS .app bundle..."
pyinstaller \
    --onefile \
    --windowed \
    --name "CopySoft" \
    --add-data "core:core" \
    --add-data "gui:gui" \
    --hidden-import PyQt5.sip \
    --hidden-import PyQt5.QtWidgets \
    --hidden-import PyQt5.QtCore \
    --hidden-import PyQt5.QtGui \
    main.py

echo ""
echo "==> Done! Output: dist/CopySoft"
echo "    (Single binary — copy anywhere and run)"
