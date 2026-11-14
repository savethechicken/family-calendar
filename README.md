# Family Calendar

A wall calendar for a TV: a big, glanceable week view with a **Today** panel,
clock, optional weather, and any number of color-coded calendars merged
together. Built to run on a **Raspberry Pi 4** driving a TV over HDMI, and to
keep working when the Wi-Fi doesn't.

![Week view on a TV](docs/screenshot.png)

```
 Google / Outlook / iCloud / school ICS feeds
                    │
                    ▼
        ┌───────────────────────┐        ┌──────────────────────┐
        │  FastAPI backend      │  HTTP  │  Chromium (kiosk)    │
        │  fetch + cache +      │◄──────►│  week grid + today   │
        │  expand recurrences   │        │  clock + weather     │
        └───────────────────────┘        └──────────────────────┘
                    Raspberry Pi 4 ──────────────► TV via HDMI
```

- **Read-only.** It never changes your calendars.
- **Resilient.** Every feed is cached on disk; a network outage keeps the last
  good copy on screen.
- **No build step.** The frontend is plain HTML/CSS/JS, so the Pi only needs
  Python and Chromium.
- **Pluggable sources.** Start with ICS (5-minute setup), add the Google
  Calendar API later without touching the UI.

---

## Quick start (on your laptop first)

Requires Python 3.11+.

```bash
cd family-calendar
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

Open <http://localhost:8080>. On first run the app creates `config.yaml`
from `config.demo.yaml`, so you'll see a demo family week immediately — no
calendar setup needed.

Then open <http://localhost:8080/settings> to add your real calendars, change
the timezone and title, and turn on weather. Settings save straight to
`config.yaml` and apply instantly; no restart.

Useful variants while developing:

- `http://localhost:8080/?theme=dark` or `?theme=light` to preview both themes
- `http://localhost:8080/api/events?start=2026-11-01T00:00:00Z&end=2026-12-01T00:00:00Z`
- `http://localhost:8080/api/docs` for the interactive API

---

## Add your calendars (settings page)

Open <http://localhost:8080/settings> — or click the gear in the top-right corner
of the calendar. Everything on that page is saved to `config.yaml` for you:

1. **+ Add calendar**, give it a name and pick a color.
2. Paste the calendar's private iCal (`.ics`) address.
3. Click **Test feed** to confirm it loads and shows upcoming events.
4. **Save changes.** The TV updates immediately; no restart.

### Where to find the iCal address (Google Calendar)

1. Open [Google Calendar](https://calendar.google.com) on the web.
2. **Settings** → select the calendar under *Settings for my calendars*.
3. Scroll to **Integrate calendar**.
4. Copy **Secret address in iCal format** (ends in `/basic.ics`).

Paste that into the settings page. Add one entry per calendar. The secret URL
grants read access to anyone who has it, so treat it like a password; it stays
in `config.yaml`, which is gitignored.

### Colors

Each calendar gets a hex color. These match Google's palette:

| Color | Hex | Color | Hex |
| --- | --- | --- | --- |
| Blue | `#039be5` | Yellow | `#f6bf26` |
| Green | `#33b679` | Orange | `#f4511e` |
| Purple | `#8e63ce` | Indigo | `#7986cb` |
| Red | `#e67c73` | Graphite | `#616161` |

Everything is merged into one week view and color-coded; the Today panel lists
all calendars together.

### Outlook, iCloud, school portals

Anything that publishes an `.ics` works. In the settings page choose
**ICS / iCal feed** and paste the link:

- **Outlook.com**: Settings → Calendar → Shared calendars → **Publish a
  calendar** → copy the ICS link.
- **iCloud**: Calendar app → Share → **Public Calendar** → copy the `webcal://`
  link (`webcal://` is accepted and converted to `https://`).
- **School / sports team**: look for "Subscribe", "Export" or "Add to calendar"
  and use the `.ics` URL, not the website URL.

If it opens a file download instead of showing a page, that's usually the right
link.

### Protecting the settings page

By default anyone on your home network can open `/settings`. To require a
password, add this to `config.yaml` (or set the `SKYLIGHT_ADMIN_TOKEN`
environment variable):

```yaml
server:
  admin_token: "pick-a-long-password"
```

The settings page asks for it once per browser session. The public calendar
stays read-only either way — the token only guards changes.

### Editing `config.yaml` by hand

The settings page is the easy path, but `config.yaml` is still a normal YAML
file (see `config.example.yaml` for every option). You can edit it directly:
the server watches the file and reloads within about five seconds. It is
gitignored on purpose, because it holds your private calendar URLs.


---

## Run with Docker (home server / NAS)

A pre-built image is published to GitHub Container Registry on every push to
`main` and every `v*` tag:

```bash
mkdir family-calendar && cd family-calendar
curl -O https://raw.githubusercontent.com/savethechicken/family-calendar/main/docker-compose.yml
docker compose up -d
```

Open <http://localhost:8080>. On first start the container creates
`./data/config.yaml` from the bundled demo config; open
<http://localhost:8080/settings> to add your calendars. All state (config +
cache) lives in `./data`, so updating the image never touches your calendars:

```bash
docker compose pull && docker compose up -d
```

> If the repo or package is private, `curl` returns a 404 and `docker compose
> pull` requires a login. Make the package public under the repo's **Packages**
> settings, or create the compose file manually and run
> `echo $GITHUB_TOKEN | docker login ghcr.io -u savethechicken --password-stdin`.

To build the image yourself instead:

```bash
git clone https://github.com/savethechicken/family-calendar.git
cd family-calendar
docker build -t family-calendar .
docker run -d --name family-calendar -p 8080:8080 -v "$PWD/data:/app/data" family-calendar
```

Lock down the settings page by uncommenting `FAMILY_CALENDAR_ADMIN_TOKEN` in
`docker-compose.yml`.

---

## Put it on the TV (Raspberry Pi 4)

### What you need

- **Raspberry Pi 4** (2 GB minimum, 4 GB comfortable; 1 GB works but Chromium is
  tight), official power supply, 16 GB+ microSD (A2) or USB SSD.
- **Raspberry Pi OS with desktop, 64-bit** (Bookworm or newer). The 64-bit build
  matters: 32-bit Chromium is slower and more memory-hungry.
- A TV over HDMI. Set the Pi's resolution to the TV's native mode in
  `raspi-config` if it doesn't pick it automatically.
- A heatsink or fan is cheap insurance; a slim case can throttle on long uptimes.

### 1. Prepare the OS

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git
sudo raspi-config
```

In `raspi-config`:

- **System Options → Boot / Auto Login → Desktop Autologin** (the kiosk needs a
  desktop session).
- **Localisation → Timezone** (also correct for HTTPS certificate checks).
- **Display Options → Screen Blanking → Disabled** (the installer also does this).

> Current Raspberry Pi OS images use **Wayland with labwc**; older Bookworm
> images may use Wayfire. The installer writes to both labwc and XDG autostart
> locations. If you are on Wayfire, see *Manual kiosk test* below.

### 2. Copy the project

```bash
cd ~
git clone <your-repo-url> family-calendar     # or scp the folder from your computer
cd family-calendar
```

No config editing yet — the first start creates `config.yaml` with demo data and
you set everything up in the browser afterwards.

If you copied the folder from Windows, fix line endings once:

```bash
sudo apt install -y dos2unix
dos2unix deploy/*.sh scripts/*.py
```

### 3. Install

```bash
chmod +x deploy/install.sh
./deploy/install.sh
```

The script installs Chromium and Python, creates `.venv`, sets up a
`family-calendar` systemd service that starts on boot, and adds the kiosk to desktop
autostart. Then:

```bash
sudo reboot
```

The calendar should appear on the TV a few seconds after the desktop loads.

### 4. Add your calendars

From your phone or laptop on the same network:

1. Open `http://<pi-ip>:8080/settings`.
2. Add each calendar's private iCal address, test the feed, and save.
3. Optionally set the timezone, title, theme and weather.

Changes apply to the TV immediately. If you want the settings page password
protected, set `server.admin_token` in `~/family-calendar/config.yaml` once (see
*Protecting the settings page* above).

### 5. Verify and operate

```bash
# from any device on the LAN
curl http://<pi-ip>:8080/api/health

journalctl -u family-calendar -f        # live server logs
sudo systemctl restart family-calendar  # rarely needed; config edits reload automatically
```

Open `http://<pi-ip>:8080` in a browser on your phone or laptop to check the
layout before looking at the TV. The gear icon in the top-right goes to the
settings page.

### 6. Updating

```bash
cd ~/family-calendar
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart family-calendar
```

`config.yaml` is gitignored, so `git pull` never touches your calendars or
password. The kiosk reloads itself once a day and whenever it wakes, so no
manual browser restart is usually needed.

### Manual kiosk test

If the TV shows the desktop instead of the calendar, run the kiosk script by
hand from a terminal **in the desktop session**:

```bash
FAMILY_CALENDAR_ONESHOT=1 ~/family-calendar/deploy/kiosk.sh
```

`SKYLIGHT_ONESHOT=1` stops it from relaunching forever so you can quit with
`Ctrl+C` and debug.

If that works, the autostart entry is the problem:

- **Wayland / labwc** (default on current Raspberry Pi OS): check that
  `~/.config/labwc/autostart` contains a line ending in
  `${HOME}/family-calendar/deploy/kiosk.sh &`. The trailing `&` matters.
- **X11 / LXDE**: check `~/.config/autostart/family-calendar-kiosk.desktop` and make
  sure its `Exec=` path is correct.
- **Wayfire** (older Bookworm images): add
  `family-calendar = /home/pi/family-calendar/deploy/kiosk.sh` under `[autostart]` in
  `~/.config/wayfire.ini`, or switch to labwc via `raspi-config` → Advanced
  Options → Wayland → labwc.

---

## Configuration reference

`config.yaml` is created on first run from `config.demo.yaml` and is normally
managed by the settings page. It is gitignored because it holds your private
calendar URLs. Manual edits are fine: the server watches the file and reloads
within about five seconds. Set `SKYLIGHT_CONFIG=/path/to/config.yaml` to use a
different file. `${VAR}` placeholders are still expanded from the environment,
so advanced setups can keep secrets in `.env`.

### `server`

| Key | Default | Notes |
| --- | --- | --- |
| `host` | `0.0.0.0` | `0.0.0.0` makes the UI reachable from your LAN |
| `port` | `8080` | |
| `admin_token` | *(empty)* | Password for `/settings`; also settable via `SKYLIGHT_ADMIN_TOKEN`. Empty means anyone on the LAN can change settings |

### `display`

| Key | Default | Notes |
| --- | --- | --- |
| `title` | `Family Calendar` | Shown top-left and in the browser tab |
| `timezone` | `America/New_York` | IANA name. Layout math uses this even if the Pi is on UTC |
| `week_starts_on` | `monday` | `monday` or `sunday` |
| `day_start_hour` | `6` | First hour in the week grid |
| `day_end_hour` | `22` | Last hour; events outside are clamped, not dropped |
| `refresh_seconds` | `60` | How often the TV polls the server (min 15) |
| `show_clock` | `true` | |
| `time_format` | `12h` | `12h` or `24h` |
| `theme` | `auto` | `auto`, `light` or `dark` |
| `accent_color` | `#5b8cff` | Today highlight, buttons, focus rings |

### `weather` (optional, Open-Meteo — no API key)

| Key | Default | Notes |
| --- | --- | --- |
| `enabled` | `false` | |
| `latitude` / `longitude` | — | Required when enabled |
| `location_name` | `Home` | Shown next to the current conditions |
| `units` | `imperial` | `imperial` (F/ mph) or `metric` (C/ km/h) |

### `calendars[]`

| Key | Notes |
| --- | --- |
| `id` | Unique, stable id (used in the API) |
| `name` | Display name |
| `color` | `#rrggbb` |
| `source.type` | `ics`, `google` or `demo` |
| `source.url` | ICS URL for `ics` (https, webcal, file paths all work) |
| `source.cache_ttl_seconds` | How long a downloaded feed is fresh (default 300) |
| `source.calendar_id` | Google only: `primary` or the calendar's long id |
| `source.client_id` / `client_secret` / `refresh_token` | Google only |

`type: demo` generates a sample family week relative to today — handy for
testing the layout, useless for real life.

---

## Optional: Google Calendar API instead of ICS

ICS is simpler and fine for most families. Use the API when you want faster
updates, many calendars without many URLs, or per-event colors later.

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project and enable **Google Calendar API**.
2. Configure the OAuth consent screen (External, add yourself as a test user).
3. **Credentials → Create credentials → OAuth client ID → Desktop app**, then
   download the JSON.
4. On your computer (not necessarily the Pi):

   ```bash
   python scripts/google_auth.py ~/Downloads/client_secret_xxx.json
   ```

   A browser opens; approve read-only calendar access. The script prints a
   refresh token.
5. Put the three values in `.env`:

   ```bash
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REFRESH_TOKEN=...
   ```

6. Use a `google` source in `config.yaml` (see `config.example.yaml`). Google
   API calendars are read-only in the settings page — they are preserved when
   you save, and their tokens are never sent to the browser.

The scope requested is `calendar.readonly`. Tokens are stored only on your Pi.

---

## HTTP API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Liveness, version, configured calendar ids |
| `GET /api/config` | Public display settings (never secrets) |
| `GET /api/events?start=…&end=…` | Merged events; `days=7` computes from this week |
| `GET /api/weather` | Current conditions + 3-day outlook |
| `GET /api/settings` | Full settings (includes editable ICS URLs; requires the admin token if set) |
| `PUT /api/settings` | Validate + save settings and hot-reload; partial payloads allowed |
| `POST /api/settings/test-feed` | Fetch a feed and report upcoming events without saving it |
| `GET /api/docs` | Interactive OpenAPI docs |

Event shape:

```json
{
  "id": "family:abc123:2026-11-11T13:00:00+00:00",
  "calendarId": "family",
  "calendarName": "Family",
  "color": "#039be5",
  "title": "Soccer practice",
  "start": "2026-11-11T16:00:00-05:00",
  "end": "2026-11-11T17:30:00-05:00",
  "allDay": false,
  "location": "Field 3",
  "description": null
}
```

`errors` in the response maps a calendar id to a message when its feed failed;
the UI keeps showing the cached copy in that case.

---

## Troubleshooting

**The TV shows a white/blank page.**
Check `curl http://localhost:8080/api/health`. If that fails, the service isn't
running: `journalctl -u family-calendar -n 50`. If it succeeds, the kiosk URL or
autostart is wrong.

**"Family couldn't refresh — showing the last saved copy."**
The feed URL is wrong, expired, or the network is down. Test it:

```bash
curl -sI "https://…/basic.ics" | head
```

You want `200` and a `text/calendar` content type. A Google Calendar **public
HTML** link won't work — use the *secret iCal* address.

**Times are wrong / off by hours.**
Set `display.timezone` in `config.yaml` *and* the Pi's system timezone
(`sudo timedatectl set-timezone America/New_York`). The UI uses the config
timezone, but the OS clock must be right for HTTPS.

**Nothing from a recurring event.**
Some feeds publish recurrence rules the expander can't handle. Check the server
log for `Could not expand recurring events`; exporting the calendar as ICS from
the provider and importing it into Google Calendar usually fixes the feed.

**Chromium is sluggish or crashes on the Pi 4.**
Confirm 64-bit Raspberry Pi OS (`uname -m` → `aarch64`), close other desktop
apps, and give the Pi airflow. On a 1 GB Pi, expect to wait longer after boot.
The kiosk profile lives in `/tmp` to spare the SD card; it is rebuilt at boot.

**Screen goes dark after a few minutes.**
`sudo raspi-config nonint do_blanking 1`, then reboot. On Wayland sessions
`xset` cannot help; the raspi-config setting is the reliable fix.

**I edited config.yaml but nothing changed.**
Check the server log (`journalctl -u family-calendar -f`). The server watches
`config.yaml` and reloads within ~5 seconds; if the new file is invalid it keeps
the previous settings and logs why. Fix the error and it will reload. You can
also restart explicitly with `sudo systemctl restart family-calendar`.

**Chromium shows an error page for a few seconds at boot.**
The kiosk script waits up to 60 seconds for `http://localhost:8080/api/health`
before opening the browser. If it still appears, the backend failed to start —
`journalctl -u family-calendar -n 50`.

---

## Exposing it beyond your LAN

The calendar and event API have no login because they are meant for a trusted
home network and are read-only. The settings page **is** writable: set
`server.admin_token` before letting untrusted devices onto your network. Do
**not** port-forward any of it to the internet. If you want to check the
calendar remotely, use a VPN such as [Tailscale](https://tailscale.com) or put
it behind an authenticating reverse proxy. Treat the `/api/events` output as
private family data.

---

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Covers ICS recurrence expansion, all-day handling, config validation, the API
contract, and the settings UI (GET/PUT round-trip, partial payloads, validation
failures, admin-token auth, Google-calendar preservation, feed preview). Run
`python -m pytest` (27 tests, no network required).

---

## Project layout

```
family-calendar/
├── app/
│   ├── config.py          # YAML loading, validation, env expansion
│   ├── main.py            # FastAPI routes
│   ├── service.py         # merge calendars, isolate failures
│   ├── settings.py        # settings UI backend (validate/save/preview)
│   ├── weather.py         # Open-Meteo client + WMO code mapping
│   ├── sources/
│   │   ├── base.py        # Event + CalendarSource protocol
│   │   ├── ics.py         # ICS fetch, disk cache, RRULE expansion
│   │   ├── demo.py        # sample week
│   │   └── google.py      # optional Calendar API source
│   └── static/            # index.html, style.css, app.js, settings.*
├── deploy/
│   ├── install.sh         # Pi 4 installer
│   ├── kiosk.sh           # Chromium kiosk launcher
│   ├── family-calendar.service   # example systemd unit
│   └── family-calendar-kiosk.desktop
├── scripts/google_auth.py # one-time OAuth refresh-token helper
├── tests/
├── .github/workflows/      # Docker image build & push (GHCR)
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── config.demo.yaml       # bootstrap config copied to config.yaml on first run
├── config.example.yaml    # documented template (manual reference)
└── config.yaml            # your machine's config (gitignored)
```

### Adding a new source type

Implement `fetch(start, end) -> list[Event]` and `aclose()` from
`app/sources/base.py`, then register it in `app/sources/__init__.py`. Sources
return timezone-aware datetimes; the service handles merging and colors.

---

## Roadmap

The architecture is deliberately boring so these are incremental:

1. **Month view** — add a `?view=month` renderer; the events endpoint already
   accepts up to 62-day ranges.
2. **Chores / meals / rewards** — a second sidebar panel backed by a tiny SQLite
   table, Family Calendar-style.
3. **Photo screensaver** — idle timer that fades to a slideshow, then returns to
   the calendar on motion or touch.
4. **Touch support** — swipe between weeks on a touchscreen; the layout already
   scales down to tablet widths.
