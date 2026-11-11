"""Settings UI backend: validate, persist and preview calendar settings.

``config.yaml`` is the single source of truth. Saves are written to a temp
file, validated with the normal config loader, then atomically swapped in, so
a bad value can never leave the running server with a broken config.
"""

from __future__ import annotations

import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import available_timezones

import yaml

from .config import (
    CalendarConfig,
    Config,
    ConfigError,
    DisplayConfig,
    SourceConfig,
    WeatherConfig,
    load_config,
)
from .sources.ics import IcsSource

EDITABLE_SOURCE_TYPES = {"ics", "demo"}
COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
ID_PATTERN = re.compile(r"[^a-z0-9_-]+")

HEADER = """# Managed by the Family Calendar settings UI (http://<host>:8080/settings).
# Manual edits are fine too: the server watches this file and reloads it.
# See config.example.yaml for the fully commented reference.
"""


class SettingsError(ValueError):
    """A user-fixable problem with submitted settings."""


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def _display_dict(display: DisplayConfig) -> dict[str, Any]:
    return {
        "title": display.title,
        "timezone": display.timezone,
        "week_starts_on": display.week_starts_on,
        "day_start_hour": display.day_start_hour,
        "day_end_hour": display.day_end_hour,
        "refresh_seconds": display.refresh_seconds,
        "show_clock": display.show_clock,
        "time_format": display.time_format,
        "accent_color": display.accent_color,
        "theme": display.theme,
    }


def _weather_dict(weather: WeatherConfig) -> dict[str, Any]:
    return {
        "enabled": weather.enabled,
        "latitude": weather.latitude,
        "longitude": weather.longitude,
        "location_name": weather.location_name,
        "units": weather.units,
    }


def build_settings_payload(config: Config, config_path: Path) -> dict[str, Any]:
    calendars = []
    for calendar in config.calendars:
        editable = calendar.source.type in EDITABLE_SOURCE_TYPES
        entry: dict[str, Any] = {
            "id": calendar.id,
            "name": calendar.name,
            "color": calendar.color,
            "editable": editable,
            "source": {
                "type": calendar.source.type,
                "cache_ttl_seconds": calendar.source.cache_ttl_seconds,
            },
        }
        # Never send Google client secrets / refresh tokens to the browser.
        if editable:
            entry["source"]["url"] = calendar.source.url
        calendars.append(entry)

    return {
        "display": _display_dict(config.display),
        "weather": _weather_dict(config.weather),
        "calendars": calendars,
        "server": {"admin_token_set": bool(config.server.admin_token)},
        "timezones": sorted(available_timezones()),
        "config_path": str(config_path),
    }


# ---------------------------------------------------------------------------
# Validate helpers
# ---------------------------------------------------------------------------


def _text(value: Any, field: str, *, maximum: int = 500, optional: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise SettingsError(f"{field} must be text.")
    value = value.strip()
    if not value and not optional:
        raise SettingsError(f"{field} cannot be empty.")
    if len(value) > maximum:
        raise SettingsError(f"{field} is too long (max {maximum} characters).")
    return value


def _integer(value: Any, field: str, *, default: int, low: int, high: int) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{field} must be a whole number.") from exc
    if not low <= number <= high:
        raise SettingsError(f"{field} must be between {low} and {high}.")
    return number


def _boolean(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _optional_float(value: Any, field: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{field} must be a number.") from exc


def normalize_feed_url(value: Any) -> str:
    url = _text(value, "Calendar URL", maximum=2000)
    if url.lower().startswith("webcal://"):
        return "webcal://" + url[len("webcal://") :]
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise SettingsError(
            "Calendar URL must start with https:// (or webcal:// for iCloud)."
        )
    return url


def _slugify(value: str, fallback: str) -> str:
    slug = ID_PATTERN.sub("-", value.strip().lower()).strip("-_")
    slug = slug[:40]
    return slug or fallback


def _unique_id(candidate: str, used: set[str]) -> str:
    if candidate not in used:
        return candidate
    index = 2
    while f"{candidate}-{index}" in used:
        index += 1
    return f"{candidate}-{index}"


# ---------------------------------------------------------------------------
# Build editable blocks
# ---------------------------------------------------------------------------


def _display_block(current: DisplayConfig, incoming: Any) -> dict[str, Any]:
    if not isinstance(incoming, dict):
        raise SettingsError("display must be an object.")

    block = _display_dict(current)
    if "title" in incoming:
        block["title"] = _text(incoming["title"], "Display title", maximum=80)
    if "timezone" in incoming:
        block["timezone"] = _text(incoming["timezone"], "Timezone", maximum=80)
    if "week_starts_on" in incoming:
        value = str(incoming["week_starts_on"]).lower()
        if value not in {"monday", "sunday"}:
            raise SettingsError("Week starts on must be Monday or Sunday.")
        block["week_starts_on"] = value
    if "day_start_hour" in incoming:
        block["day_start_hour"] = _integer(
            incoming["day_start_hour"], "Day starts at", default=current.day_start_hour, low=0, high=23
        )
    if "day_end_hour" in incoming:
        block["day_end_hour"] = _integer(
            incoming["day_end_hour"], "Day ends at", default=current.day_end_hour, low=1, high=24
        )
    if "refresh_seconds" in incoming:
        block["refresh_seconds"] = _integer(
            incoming["refresh_seconds"], "Refresh interval", default=current.refresh_seconds, low=15, high=3600
        )
    if "show_clock" in incoming:
        block["show_clock"] = _boolean(incoming["show_clock"], current.show_clock)
    if "time_format" in incoming:
        value = str(incoming["time_format"]).lower()
        if value not in {"12h", "24h"}:
            raise SettingsError("Time format must be 12h or 24h.")
        block["time_format"] = value
    if "accent_color" in incoming:
        value = str(incoming["accent_color"]).strip()
        if not COLOR_PATTERN.fullmatch(value):
            raise SettingsError("Accent color must be a hex value like #5b8cff.")
        block["accent_color"] = value
    if "theme" in incoming:
        value = str(incoming["theme"]).lower()
        if value not in {"auto", "light", "dark"}:
            raise SettingsError("Theme must be auto, light or dark.")
        block["theme"] = value
    return block


def _weather_block(current: WeatherConfig, incoming: Any) -> dict[str, Any]:
    if not isinstance(incoming, dict):
        raise SettingsError("weather must be an object.")

    block = _weather_dict(current)
    if "enabled" in incoming:
        block["enabled"] = _boolean(incoming["enabled"], current.enabled)
    if "latitude" in incoming:
        block["latitude"] = _optional_float(incoming["latitude"], "Latitude")
    if "longitude" in incoming:
        block["longitude"] = _optional_float(incoming["longitude"], "Longitude")
    if "location_name" in incoming:
        block["location_name"] = _text(
            incoming["location_name"], "Location name", maximum=60, optional=True
        )
    if "units" in incoming:
        value = str(incoming["units"]).lower()
        if value not in {"imperial", "metric"}:
            raise SettingsError("Units must be imperial or metric.")
        block["units"] = value

    if block["latitude"] is not None and not -90 <= block["latitude"] <= 90:
        raise SettingsError("Latitude must be between -90 and 90.")
    if block["longitude"] is not None and not -180 <= block["longitude"] <= 180:
        raise SettingsError("Longitude must be between -180 and 180.")
    if block["enabled"] and (block["latitude"] is None or block["longitude"] is None):
        raise SettingsError(
            "Weather is enabled but latitude/longitude are missing. "
            "Copy them from any map pin for your home."
        )
    return block


def _calendar_blocks(incoming: Any, raw_calendars: list[Any]) -> list[dict[str, Any]]:
    if not isinstance(incoming, list):
        raise SettingsError("calendars must be a list.")

    preserved: list[dict[str, Any]] = []
    for raw in raw_calendars:
        if not isinstance(raw, dict):
            continue
        source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        if str(source.get("type", "")).lower() not in EDITABLE_SOURCE_TYPES:
            preserved.append(raw)

    used = {str(raw.get("id", "")) for raw in preserved}
    blocks: list[dict[str, Any]] = []

    for index, item in enumerate(incoming, start=1):
        if not isinstance(item, dict):
            raise SettingsError(f"Calendar #{index} is invalid.")

        name = _text(item.get("name"), f"Calendar #{index} name", maximum=80)
        color = str(item.get("color", "")).strip()
        if not COLOR_PATTERN.fullmatch(color):
            raise SettingsError(f"Calendar #{index} color must be a hex value like #039be5.")

        source_in = item.get("source")
        if not isinstance(source_in, dict):
            raise SettingsError(f"Calendar #{index} is missing a source.")
        source_type = str(source_in.get("type", "ics")).lower()
        if source_type not in EDITABLE_SOURCE_TYPES:
            raise SettingsError(
                f"Calendar #{index}: this screen supports ICS/iCal and demo "
                "calendars. Google API calendars are configured in config.yaml."
            )

        candidate = str(item.get("id") or "").strip().lower()
        if candidate and not re.fullmatch(r"[a-z0-9_-]{1,64}", candidate):
            raise SettingsError(f"Calendar #{index} has an invalid id.")
        calendar_id = _unique_id(candidate or _slugify(name, f"calendar-{index}"), used)
        used.add(calendar_id)

        source: dict[str, Any] = {
            "type": source_type,
            "cache_ttl_seconds": _integer(
                source_in.get("cache_ttl_seconds"),
                f"Calendar #{index} cache TTL",
                default=300,
                low=30,
                high=86_400,
            ),
        }
        if source_type == "ics":
            source["url"] = normalize_feed_url(source_in.get("url"))

        blocks.append(
            {"id": calendar_id, "name": name, "color": color, "source": source}
        )

    return blocks + preserved


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def save_settings(config_path: Path, payload: dict[str, Any]) -> Config:
    """Validate and atomically replace ``config.yaml``, then reload it."""
    path = Path(config_path).expanduser().resolve()
    if not isinstance(payload, dict):
        raise SettingsError("Settings payload must be an object.")

    current = load_config(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SettingsError(f"Could not read the current config: {exc}") from exc
    if not isinstance(raw, dict):
        raise SettingsError("config.yaml must contain a mapping.")

    if "display" in payload:
        raw["display"] = _display_block(current.display, payload["display"])
    if "weather" in payload:
        raw["weather"] = _weather_block(current.weather, payload["weather"])
    if "calendars" in payload:
        raw["calendars"] = _calendar_blocks(payload["calendars"], raw.get("calendars") or [])

    if not raw.get("calendars"):
        raise SettingsError("Keep at least one calendar, or add one first.")

    text = HEADER + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)

    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        load_config(tmp)  # full validation, same rules as startup
    except ConfigError as exc:
        tmp.unlink(missing_ok=True)
        raise SettingsError(str(exc).replace(str(tmp), "config.yaml")) from exc

    try:
        if path.exists():
            path.with_name(f"{path.name}.bak").write_text(
                path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        tmp.replace(path)
        path.chmod(0o600)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise SettingsError(f"Could not save config.yaml: {exc}") from exc

    return load_config(path)


# ---------------------------------------------------------------------------
# Feed preview
# ---------------------------------------------------------------------------


async def preview_feed(url: Any, timezone) -> dict[str, Any]:
    """Fetch and parse a feed without saving it, for the 'Test feed' button."""
    feed_url = normalize_feed_url(url)
    calendar = CalendarConfig(
        id="preview",
        name="Preview",
        color="#5b8cff",
        source=SourceConfig(type="ics", url=feed_url, cache_ttl_seconds=30),
    )

    with tempfile.TemporaryDirectory(prefix="family-calendar-preview-") as folder:
        source = IcsSource(calendar, cache_dir=Path(folder), tz=timezone)
        now = datetime.now(timezone)
        try:
            events = await source.fetch(now, now + timedelta(days=14))
        except Exception as exc:
            message = " ".join(str(exc).split())[:300]
            raise SettingsError(f"Could not load that feed: {message}") from exc
        finally:
            await source.aclose()

    events.sort(key=lambda event: event.start)
    return {
        "count": len(events),
        "samples": [
            {
                "title": event.title,
                "start": event.start.isoformat(),
                "allDay": event.all_day,
            }
            for event in events[:5]
        ],
    }
