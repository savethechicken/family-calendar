#!/usr/bin/env bash
# Launch Chromium in kiosk mode against the local calendar server.
# Called from ~/.config/labwc/autostart (Wayland) or an XDG autostart entry (X11).
set -euo pipefail

URL="${FAMILY_CALENDAR_URL:-http://localhost:8080}"
PROFILE_DIR="${FAMILY_CALENDAR_CHROMIUM_PROFILE:-/tmp/family-calendar-chromium}"

BROWSER="${FAMILY_CALENDAR_BROWSER:-}"
if [ -z "${BROWSER}" ]; then
  # Trixie ships `chromium`; Bookworm ships `chromium-browser`.
  BROWSER="$(command -v chromium || command -v chromium-browser || true)"
fi
if [ -z "${BROWSER}" ]; then
  echo "Chromium not found. Install it with: sudo apt install chromium-browser" >&2
  exit 1
fi

# Wait for the backend (max 60s) so we never show an error page on boot.
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 "${URL}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# X11 sessions only: stop the display from blanking and hide the cursor.
if [ -n "${DISPLAY:-}" ] && command -v xset >/dev/null 2>&1; then
  xset s off || true
  xset -dpms || true
  xset s noblank || true
fi
if [ -n "${DISPLAY:-}" ] && command -v unclutter >/dev/null 2>&1; then
  unclutter -idle 0.5 -root >/dev/null 2>&1 &
fi

FLAGS=(
  --kiosk "${URL}"
  --user-data-dir="${PROFILE_DIR}"
  --disk-cache-dir="${PROFILE_DIR}/cache"
  --noerrdialogs
  --disable-infobars
  --disable-session-crashed-bubble
  --disable-component-update
  --disable-background-networking
  --disable-sync
  --disable-features=Translate,MediaRouter
  --check-for-update-interval=31536000
  --password-store=basic
  --overscroll-history-navigation=0
  --no-first-run
)

if [ -n "${WAYLAND_DISPLAY:-}" ]; then
  FLAGS+=(--ozone-platform=wayland)
fi

# Restart the browser if it ever crashes, unless explicitly running once.
while true; do
  "${BROWSER}" "${FLAGS[@]}" || true
  if [ "${FAMILY_CALENDAR_ONESHOT:-0}" = "1" ]; then
    break
  fi
  sleep 3
done
