"""Optional weather from Open-Meteo (free, no API key)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .config import WeatherConfig

log = logging.getLogger(__name__)

CACHE_SECONDS = 600

# WMO weather interpretation codes.
_WMO: dict[int, tuple[str, str]] = {
    0: ("Clear", "sun"),
    1: ("Mostly clear", "sun"),
    2: ("Partly cloudy", "cloud-sun"),
    3: ("Overcast", "cloud"),
    45: ("Fog", "fog"),
    48: ("Rime fog", "fog"),
    51: ("Light drizzle", "rain"),
    53: ("Drizzle", "rain"),
    55: ("Heavy drizzle", "rain"),
    56: ("Freezing drizzle", "rain"),
    57: ("Freezing drizzle", "rain"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"),
    67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Rain showers", "rain"),
    81: ("Rain showers", "rain"),
    82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"),
    86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm", "storm"),
    99: ("Thunderstorm", "storm"),
}


def describe(code: int | None) -> dict[str, str]:
    label, icon = _WMO.get(int(code or 0), ("Unknown", "cloud"))
    return {"label": label, "icon": icon}


class WeatherService:
    def __init__(self, config: WeatherConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        self._cached: dict[str, Any] | None = None
        self._cached_at: float = 0.0

    @property
    def enabled(self) -> bool:
        return self._config.enabled and self._config.latitude is not None

    async def get(self) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}

        if self._cached and time.time() - self._cached_at < CACHE_SECONDS:
            return self._cached

        imperial = self._config.units == "imperial"
        params: dict[str, Any] = {
            "latitude": self._config.latitude,
            "longitude": self._config.longitude,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
            "forecast_days": 3,
        }
        if imperial:
            params["temperature_unit"] = "fahrenheit"
            params["wind_speed_unit"] = "mph"
        else:
            params["wind_speed_unit"] = "kmh"

        try:
            response = await self._client.get(
                "https://api.open-meteo.com/v1/forecast", params=params
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - weather is decorative
            log.warning("Weather fetch failed: %s", exc)
            if self._cached:
                return self._cached
            return {"enabled": True, "error": "Weather unavailable"}

        current = payload.get("current", {})
        daily = payload.get("daily", {})
        days = []
        for index, day in enumerate(daily.get("time", [])[:3]):
            days.append(
                {
                    "date": day,
                    "high": _round(daily.get("temperature_2m_max", [None])[index]),
                    "low": _round(daily.get("temperature_2m_min", [None])[index]),
                    **describe(daily.get("weather_code", [None])[index]),
                }
            )

        result = {
            "enabled": True,
            "location": self._config.location_name,
            "units": "F" if imperial else "C",
            "temperature": _round(current.get("temperature_2m")),
            "feelsLike": _round(current.get("apparent_temperature")),
            "humidity": _round(current.get("relative_humidity_2m")),
            "wind": _round(current.get("wind_speed_10m")),
            "isDay": bool(current.get("is_day", 1)),
            "days": days,
            **describe(current.get("weather_code")),
        }
        self._cached = result
        self._cached_at = time.time()
        return result

    async def aclose(self) -> None:
        await self._client.aclose()


def _round(value: Any) -> int | None:
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None
