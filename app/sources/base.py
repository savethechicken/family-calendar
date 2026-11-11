"""Shared calendar-source types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Event:
    """A normalized event, always with timezone-aware datetimes."""

    uid: str
    calendar_id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str | None = None
    description: str | None = None

    def as_dict(self, *, calendar_name: str, color: str) -> dict[str, object]:
        return {
            "id": self.uid,
            "calendarId": self.calendar_id,
            "calendarName": calendar_name,
            "color": color,
            "title": self.title,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "allDay": self.all_day,
            "location": self.location,
            "description": self.description,
        }


@runtime_checkable
class CalendarSource(Protocol):
    """A pluggable source of events for one calendar."""

    async def fetch(self, start: datetime, end: datetime) -> list[Event]:
        """Return every event that overlaps ``[start, end)``."""
        ...

    async def aclose(self) -> None:
        """Release any network resources."""
        ...
