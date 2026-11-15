#!/usr/bin/env bash
# Minimal kiosk for Raspberry Pi Zero W (and other low-memory boards).
#
# The Zero W has a single 1 GHz core and 512 MB RAM, so we avoid the full
# desktop session and run Chromium directly under `cage` (a tiny Wayland
# compositor). Expect some lag; for a smoother experience use a Pi 3/4.
set -euo pipefail

URL="${FAMILY_CALENDAR_URL:-http://localhost:8080}"
PROFILE_DIR="${FAMILY_CALENDAR_CHROMIUM_PROFILE:-/tmp/family-calendar-chromium}"
ONESHOT="${FAMILY_CALENDAR_ONESHOT:-0}"

mkdir -p "$PROFILE_DIR"

# Pick a browser binary.
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

# Install cage if missing (tiny Wayland kiosk compositor).
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
  --disable-gpu
  --disable-dev-shm-usage
  --disable-software-rasterizer
  --memory-pressure-off
  --js-flags=--max-old-space-size=128
)

launch() {
  # cage runs a single application full-screen on its own VT.
  cage -- "$BROWSER" "${CHROMIUM_FLAGS[@]}"
}

if [ "$ONESHOT" = "1" ]; then
  launch
  exit 0
fi

# Restart loop with a longer backoff for the Zero W.
while true; do
  launch || true
  sleep 15
done
