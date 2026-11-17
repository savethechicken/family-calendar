#!/usr/bin/env bash
# Kiosk launcher for Raspberry Pi 5 (and Pi 4) running Raspberry Pi OS Lite.
#
# Uses cage (a tiny Wayland compositor) so there is no desktop environment
# overhead. GPU acceleration is enabled (Pi 5 has a capable V3D GPU).
set -euo pipefail

URL="${FAMILY_CALENDAR_URL:-http://localhost:8080}"
PROFILE_DIR="${FAMILY_CALENDAR_CHROMIUM_PROFILE:-/tmp/family-calendar-chromium}"
ONESHOT="${FAMILY_CALENDAR_ONESHOT:-0}"

mkdir -p "$PROFILE_DIR"

BROWSER=""
for candidate in chromium chromium-browser; do
  if command -v "$candidate" >/dev/null 2>&1; then
    BROWSER="$candidate"
    break
  fi
done
if [ -z "$BROWSER" ]; then
  echo "No chromium binary found. Install with: sudo apt install chromium" >&2
  exit 1
fi

if ! command -v cage >/dev/null 2>&1; then
  echo "==> Installing cage"
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends cage
fi

CHROMIUM_FLAGS=(
  --kiosk
  --app="$URL"
  --user-data-dir="$PROFILE_DIR"
  --no-first-run
  --no-default-browser-check
  --disable-extensions
  --disable-translate
  --disable-features=TranslateUI
  --disable-background-networking
  --disable-sync
  --disable-default-apps
  --disable-component-update
  --disable-breakpad
  --disable-crash-reporter
  --metrics-recording-only
  --ozone-platform=wayland
  --enable-gpu-rasterization
  --enable-features=VaapiVideoDecoder
  --ignore-gpu-blocklist
)

launch() {
  cage -- "$BROWSER" "${CHROMIUM_FLAGS[@]}"
}

if [ "$ONESHOT" = "1" ]; then
  launch
  exit 0
fi

while true; do
  launch || true
  sleep 5
done
