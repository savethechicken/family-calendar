#!/usr/bin/env bash
# Install Skylight on Raspberry Pi OS (Pi 4 / Pi 5, 64-bit recommended).
# Run as your normal desktop user — the script calls sudo when needed.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-${USER}}"

if [ "${EUID}" -eq 0 ]; then
  echo "Run this as your normal user (e.g. 'pi'), not with sudo or as root." >&2
  echo "The script asks for sudo itself when it needs it." >&2
  exit 1
fi
SUDO="sudo"

echo "==> Installing Skylight for user '${SERVICE_USER}' from ${APP_DIR}"

$SUDO apt-get update
$SUDO apt-get install -y --no-install-recommends python3-venv python3-pip curl fonts-dejavu-core
# unclutter is X11-only and optional.
$SUDO apt-get install -y --no-install-recommends unclutter || true

# Trixie ships `chromium`; Bookworm ships `chromium-browser`.
if ! $SUDO apt-get install -y --no-install-recommends chromium; then
  echo "==> 'chromium' package unavailable, trying 'chromium-browser'"
  $SUDO apt-get install -y --no-install-recommends chromium-browser
fi

if [ ! -d "${APP_DIR}/.venv" ]; then
  echo "==> Creating virtualenv"
  python3 -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/pip" install --upgrade pip wheel
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

mkdir -p "${APP_DIR}/cache"
chmod +x "${APP_DIR}/deploy/kiosk.sh"

if [ ! -f "${APP_DIR}/config.yaml" ]; then
  cp "${APP_DIR}/config.example.yaml" "${APP_DIR}/config.yaml"
  echo "==> Created config.yaml from the template — edit it with your calendar URLs."
fi
touch "${APP_DIR}/.env"

echo "==> Installing systemd service"
$SUDO tee /etc/systemd/system/skylight.service >/dev/null <<EOF
[Unit]
Description=Skylight family calendar
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
Environment=SKYLIGHT_CONFIG=${APP_DIR}/config.yaml
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

$SUDO systemctl daemon-reload
$SUDO systemctl enable --now skylight.service

echo "==> Installing kiosk autostart"
USER_HOME="$(getent passwd "${SERVICE_USER}" | cut -d: -f6)"

# X11 / LXDE sessions.
mkdir -p "${USER_HOME}/.config/autostart"
sed "s|__APP_DIR__|${APP_DIR}|g" "${APP_DIR}/deploy/skylight-kiosk.desktop" \
  > "${USER_HOME}/.config/autostart/skylight-kiosk.desktop"

# Wayland / labwc sessions (the default on Bookworm and Trixie).
LABWC_DIR="${USER_HOME}/.config/labwc"
mkdir -p "${LABWC_DIR}"
touch "${LABWC_DIR}/autostart"
if ! grep -q "skylight-kiosk" "${LABWC_DIR}/autostart"; then
  {
    echo ""
    echo "# skylight-kiosk"
    echo "${APP_DIR}/deploy/kiosk.sh &"
  } >> "${LABWC_DIR}/autostart"
fi

chown -R "${SERVICE_USER}:" "${USER_HOME}/.config/autostart" "${LABWC_DIR}" || true

if [ -f "${USER_HOME}/.config/wayfire.ini" ]; then
  echo "==> Wayfire config detected. If the kiosk does not start, add this under"
  echo "    the [autostart] section of ${USER_HOME}/.config/wayfire.ini:"
  echo "    skylight = ${APP_DIR}/deploy/kiosk.sh"
  echo "    ...or switch to labwc in raspi-config (Advanced Options -> Wayland)."
fi

# Disable console screen blanking so the TV never goes dark.
if command -v raspi-config >/dev/null 2>&1; then
  $SUDO raspi-config nonint do_blanking 1 || true
fi

IP="$(hostname -I | awk '{print $1}')"
echo
echo "Done."
echo "  Local:  http://localhost:8080"
echo "  LAN:    http://${IP}:8080"
echo "  Logs:   journalctl -u skylight -f"
echo "  Config: ${APP_DIR}/config.yaml"
echo
echo "Reboot (or log out and back in) to start the kiosk on the TV."
