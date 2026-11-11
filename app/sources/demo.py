"""Demo source: generates a believable family week so the UI works instantly.

Replace it with an ``ics`` or ``google`` calendar in config.yaml when you are
ready to go live.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from ..config import CalendarConfig
from .base import Event

# weekday (Mon=0) -> list of (start hour, start minute, duration minutes, title)
_WEEKLY: dict[int, list[tuple[int, int, int, str]]] = {
    0: [
        (8, 0, 480, "Work"),
        (15, 30, 60, "Piano practice"),
        (18, 30, 60, "Dinner"),
    ],
    1: [
        (8, 0, 480, "Work"),
        (16, 0, 90, "Soccer practice"),
        (18, 30, 60, "Dinner"),
    ],
    2: [
        (8, 0, 480, "Work"),
        (18, 0, 45, "Grocery run"),
        (18, 30, 60, "Dinner"),
    ],
    3: [
        (8, 0, 480, "Work"),
        (16, 0, 90, "Soccer practice"),
        (18, 30, 60, "Dinner"),
    ],
    4: [
        (8, 0, 480, "Work"),
        (17, 30, 120, "Family movie night"),
    ],
    5: [
        (9, 0, 120, "Farmers market"),
        (13, 0, 180, "Playdate at the park"),
    ],
    6: [
        (10, 0, 60, "Brunch"),
        (14, 0, 120, "Visit grandparents"),
    ],
}

_ALL_DAY = {
    2: "Trash day",
    4: "Library books due",
}


class DemoSource:
    def __init__(self, calendar: CalendarConfig, tz) -> None:
        self._calendar = calendar
        self._tz = tz

    async def fetch(self, start: datetime, end: datetime) -> list[Event]:
        events: list[Event] = []
        local_start = start.astimezone(self._tz)
        local_end = end.astimezone(self._tz)

        day = local_start.date()
        while day <= local_end.date():
            for hour, minute, duration, title in _WEEKLY.get(day.weekday(), []):
                begins = datetime.combine(day, time(hour, minute), tzinfo=self._tz)
                finishes = begins + timedelta(minutes=duration)
                if finishes > start and begins < end:
                    events.append(
                        Event(
                            uid=f"demo-{day.isoformat()}-{title.lower().replace(' ', '-')}",
                            calendar_id=self._calendar.id,
                            title=title,
                            start=begins,
                            end=finishes,
                            location="Home" if title == "Dinner" else None,
                        )
                    )

            all_day_title = _ALL_DAY.get(day.weekday())
            if all_day_title:
                begins = datetime.combine(day, time(0, 0), tzinfo=self._tz)
                finishes = begins + timedelta(days=1)
                if finishes > start and begins < end:
                    events.append(
                        Event(
                            uid=f"demo-allday-{day.isoformat()}",
                            calendar_id=self._calendar.id,
                            title=all_day_title,
                            start=begins,
                            end=finishes,
                            all_day=True,
                        )
                    )

            day += timedelta(days=1)

        return events

    async def aclose(self) -> None:
        return None
