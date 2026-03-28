#!/usr/bin/env bash
# ============================================================
# Build CopySoft.exe from macOS/Linux using Docker + Wine
# No Windows machine needed.
# Requirements: Docker Desktop running
# ============================================================
set -e

cd "$(dirname "$0")/.."
DIST_DIR="$(pwd)/dist"
mkdir -p "$DIST_DIR"

echo "==> Building Windows exe via Docker + Wine..."
echo "    (First run builds image ~2 min; subsequent runs ~1 min)"
echo

# Build (or reuse cached) Docker image
docker build \
  --platform linux/amd64 \
  -f build/Dockerfile.windows \
  -t copysoft-win-builder \
  --quiet \
  .

# Extract exe to dist/
docker run --rm \
  --platform linux/amd64 \
  -v "${DIST_DIR}:/out" \
  copysoft-win-builder

echo
if [ -f "${DIST_DIR}/CopySoft.exe" ]; then
  SIZE=$(du -sh "${DIST_DIR}/CopySoft.exe" | cut -f1)
  echo "==> SUCCESS: dist/CopySoft.exe  (${SIZE})"
  echo "    Portable Windows executable — copy to any Windows PC and run."
else
  echo "==> ERROR: Build failed."
  exit 1
fi
