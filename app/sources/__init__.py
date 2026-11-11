"""Source registry: config in, source objects out."""

from __future__ import annotations

from ..config import CalendarConfig, Config
from .base import CalendarSource, Event
from .demo import DemoSource
from .google import GoogleSource
from .ics import IcsSource, parse_ics

__all__ = [
    "CalendarSource",
    "Event",
    "build_sources",
    "parse_ics",
]


def build_source(calendar: CalendarConfig, config: Config) -> CalendarSource:
    tz = config.display.tz
    if calendar.source.type == "ics":
        return IcsSource(calendar, cache_dir=config.cache_dir, tz=tz)
    if calendar.source.type == "google":
        return GoogleSource(calendar, tz=tz)
    if calendar.source.type == "demo":
        return DemoSource(calendar, tz)
    raise ValueError(f"Unsupported source type {calendar.source.type!r}")


def build_sources(config: Config) -> dict[str, CalendarSource]:
    return {calendar.id: build_source(calendar, config) for calendar in config.calendars}
