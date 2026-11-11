"""Configuration loading.

The whole app is driven by one YAML file. Environment variables can be
interpolated with ``${NAME}`` so calendar URLs and OAuth secrets can live in
``.env`` (or the systemd unit) instead of the config file.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from dotenv import load_dotenv

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(RuntimeError):
    """Raised when the configuration file is missing or invalid."""


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda match: os.environ.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    admin_token: str = ""


@dataclass(frozen=True)
class DisplayConfig:
    title: str = "Family Calendar"
    timezone: str = "America/New_York"
    week_starts_on: str = "monday"
    day_start_hour: int = 6
    day_end_hour: int = 22
    refresh_seconds: int = 60
    show_clock: bool = True
    time_format: str = "12h"
    accent_color: str = "#5b8cff"
    theme: str = "auto"

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:  # pragma: no cover - platform data
            raise ConfigError(
                f"Unknown timezone {self.timezone!r}. Use an IANA name like "
                "'America/New_York' or 'Europe/London'."
            ) from exc


@dataclass(frozen=True)
class WeatherConfig:
    enabled: bool = False
    latitude: float | None = None
    longitude: float | None = None
    location_name: str = "Home"
    units: str = "imperial"  # imperial -> F/mph, metric -> C/kmh


@dataclass(frozen=True)
class SourceConfig:
    type: str = "ics"
    url: str = ""
    cache_ttl_seconds: int = 300
    # Google-only fields, used when type == "google".
    calendar_id: str = "primary"
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""


@dataclass(frozen=True)
class CalendarConfig:
    id: str
    name: str
    color: str
    source: SourceConfig


@dataclass(frozen=True)
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    calendars: tuple[CalendarConfig, ...] = ()
    config_dir: Path = Path(".")
    cache_dir: Path = Path("cache")

    def public_dict(self) -> dict[str, Any]:
        """Everything the browser is allowed to know. No URLs or secrets."""
        return {
            "display": {
                "title": self.display.title,
                "timezone": self.display.timezone,
                "weekStartsOn": self.display.week_starts_on,
                "dayStartHour": self.display.day_start_hour,
                "dayEndHour": self.display.day_end_hour,
                "refreshSeconds": self.display.refresh_seconds,
                "showClock": self.display.show_clock,
                "timeFormat": self.display.time_format,
                "accentColor": self.display.accent_color,
                "theme": self.display.theme,
            },
            "weather": {
                "enabled": self.weather.enabled and self.weather.latitude is not None,
                "locationName": self.weather.location_name,
                "units": self.weather.units,
            },
            "calendars": [
                {"id": calendar.id, "name": calendar.name, "color": calendar.color}
                for calendar in self.calendars
            ],
        }


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _require_mapping(value: Any, what: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{what} must be a mapping/object.")
    return value


def _clamp_hour(value: Any, default: int, name: str) -> int:
    try:
        hour = int(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"display.{name} must be an integer hour (0-24).") from exc
    if not 0 <= hour <= 24:
        raise ConfigError(f"display.{name} must be between 0 and 24.")
    return hour


def ensure_config_file(path: str | Path) -> Path:
    """Create a demo config on first run so the app always boots.

    The generated ``config.yaml`` is machine-managed by the settings UI and is
    gitignored; ``config.demo.yaml`` and ``config.example.yaml`` are the
    versioned templates.
    """
    target = Path(path).expanduser().resolve()
    if target.exists():
        return target

    candidates = [
        target.parent / "config.demo.yaml",
        Path(__file__).resolve().parent.parent / "config.demo.yaml",
    ]
    demo = next((candidate for candidate in candidates if candidate.exists()), None)
    if demo is None:
        raise ConfigError(
            f"No config at {target} and no config.demo.yaml to copy. "
            "Copy config.example.yaml to config.yaml and edit it."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(demo.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def load_config(path: str | Path) -> Config:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(
            f"Config file not found: {config_path}\n"
            "Copy config.example.yaml to config.yaml and edit it."
        )

    # Load .env next to the config so `python run.py` behaves like the systemd
    # unit, without overwriting variables that are already set.
    load_dotenv(config_path.parent / ".env", override=False)

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse {config_path.name}: {exc}") from exc

    raw = _expand_env(raw)
    if not isinstance(raw, dict):
        raise ConfigError("The config file must contain a YAML mapping at the top level.")

    server_raw = _require_mapping(raw.get("server"), "server")
    server = ServerConfig(
        host=str(server_raw.get("host", "0.0.0.0")),
        port=int(server_raw.get("port", 8080)),
        admin_token=str(
            server_raw.get("admin_token")
            or os.environ.get("SKYLIGHT_ADMIN_TOKEN")
            or ""
        ).strip(),
    )

    display_raw = _require_mapping(raw.get("display"), "display")
    timezone = str(display_raw.get("timezone", "America/New_York"))
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(
            f"Unknown timezone {timezone!r}. Use an IANA name like 'America/New_York'."
        ) from exc

    week_starts_on = str(display_raw.get("week_starts_on", "monday")).lower()
    if week_starts_on not in {"monday", "sunday"}:
        raise ConfigError("display.week_starts_on must be 'monday' or 'sunday'.")

    day_start = _clamp_hour(display_raw.get("day_start_hour"), 6, "day_start_hour")
    day_end = _clamp_hour(display_raw.get("day_end_hour"), 22, "day_end_hour")
    if day_end <= day_start:
        raise ConfigError("display.day_end_hour must be greater than day_start_hour.")

    time_format = str(display_raw.get("time_format", "12h")).lower()
    if time_format not in {"12h", "24h"}:
        raise ConfigError("display.time_format must be '12h' or '24h'.")

    theme = str(display_raw.get("theme", "auto")).lower()
    if theme not in {"auto", "light", "dark"}:
        raise ConfigError("display.theme must be 'auto', 'light' or 'dark'.")

    display = DisplayConfig(
        title=str(display_raw.get("title", "Family Calendar")),
        timezone=timezone,
        week_starts_on=week_starts_on,
        day_start_hour=day_start,
        day_end_hour=day_end,
        refresh_seconds=max(15, int(display_raw.get("refresh_seconds", 60))),
        show_clock=_as_bool(display_raw.get("show_clock"), True),
        time_format=time_format,
        accent_color=str(display_raw.get("accent_color", "#5b8cff")),
        theme=theme,
    )

    weather_raw = _require_mapping(raw.get("weather"), "weather")
    units = str(weather_raw.get("units", "imperial")).lower()
    if units not in {"imperial", "metric"}:
        raise ConfigError("weather.units must be 'imperial' or 'metric'.")
    latitude = weather_raw.get("latitude")
    longitude = weather_raw.get("longitude")
    weather = WeatherConfig(
        enabled=_as_bool(weather_raw.get("enabled"), False),
        latitude=float(latitude) if latitude is not None else None,
        longitude=float(longitude) if longitude is not None else None,
        location_name=str(weather_raw.get("location_name", "Home")),
        units=units,
    )
    if weather.enabled and (weather.latitude is None or weather.longitude is None):
        raise ConfigError(
            "weather.enabled is true but weather.latitude/longitude are missing."
        )

    calendars_raw = raw.get("calendars") or []
    if not isinstance(calendars_raw, list) or not calendars_raw:
        raise ConfigError("Add at least one entry under 'calendars'.")

    calendars: list[CalendarConfig] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(calendars_raw, start=1):
        item = _require_mapping(item, f"calendars[{index}]")
        calendar_id = str(item.get("id") or f"calendar-{index}").strip()
        if calendar_id in seen_ids:
            raise ConfigError(f"Duplicate calendar id {calendar_id!r}.")
        seen_ids.add(calendar_id)

        source_raw = _require_mapping(item.get("source"), f"calendars[{index}].source")
        source_type = str(source_raw.get("type", "ics")).lower()
        if source_type not in {"ics", "google", "demo"}:
            raise ConfigError(
                f"calendars[{index}].source.type must be 'ics', 'google' or 'demo'."
            )

        source = SourceConfig(
            type=source_type,
            url=str(source_raw.get("url", "")),
            cache_ttl_seconds=max(30, int(source_raw.get("cache_ttl_seconds", 300))),
            calendar_id=str(source_raw.get("calendar_id", "primary")),
            client_id=str(source_raw.get("client_id", "")),
            client_secret=str(source_raw.get("client_secret", "")),
            refresh_token=str(source_raw.get("refresh_token", "")),
        )
        if source_type == "ics" and not source.url:
            raise ConfigError(f"calendars[{index}] is type 'ics' but has no source.url.")

        color = str(item.get("color", "#5b8cff")).strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ConfigError(
                f"calendars[{index}].color must be a hex color like '#4f8cff'."
            )

        calendars.append(
            CalendarConfig(
                id=calendar_id,
                name=str(item.get("name", calendar_id.title())),
                color=color,
                source=source,
            )
        )

    config_dir = config_path.parent
    cache_dir = Path(str(raw.get("cache_dir", "cache")))
    if not cache_dir.is_absolute():
        cache_dir = config_dir / cache_dir

    return Config(
        server=server,
        display=display,
        weather=weather,
        calendars=tuple(calendars),
        config_dir=config_dir,
        cache_dir=cache_dir,
    )
