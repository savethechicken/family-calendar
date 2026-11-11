from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import CalendarConfig, SourceConfig
from app.sources.ics import parse_ics

TZ = ZoneInfo("America/New_York")

CALENDAR = CalendarConfig(
    id="test",
    name="Test",
    color="#5b8cff",
    source=SourceConfig(type="ics", url="https://example.com/feed.ics"),
)

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Skylight Tests//EN
CALSCALE:GREGORIAN
BEGIN:VEVENT
UID:dentist
DTSTAMP:20260101T000000Z
DTSTART;TZID=America/New_York:20251110T090000
DTEND;TZID=America/New_York:20251110T100000
SUMMARY:Dentist appointment
LOCATION:123 Main St
DESCRIPTION:Bring insurance card
END:VEVENT
BEGIN:VEVENT
UID:piano
DTSTAMP:20260101T000000Z
DTSTART;TZID=America/New_York:20251103T153000
DTEND;TZID=America/New_York:20251103T163000
RRULE:FREQ=WEEKLY;BYDAY=MO
SUMMARY:Piano lesson
END:VEVENT
BEGIN:VEVENT
UID:trash
DTSTAMP:20260101T000000Z
DTSTART;VALUE=DATE:20251112
DTEND;VALUE=DATE:20251113
SUMMARY:Trash day
END:VEVENT
BEGIN:VEVENT
UID:cancelled
DTSTAMP:20260101T000000Z
DTSTART;TZID=America/New_York:20251111T120000
DTEND;TZID=America/New_York:20251111T130000
STATUS:CANCELLED
SUMMARY:Cancelled thing
END:VEVENT
END:VCALENDAR
"""

WINDOW_START = datetime(2025, 11, 10, 0, 0, tzinfo=TZ)
WINDOW_END = datetime(2025, 11, 17, 0, 0, tzinfo=TZ)


def test_expands_recurrence_and_skips_cancelled() -> None:
    events = parse_ics(ICS, CALENDAR, WINDOW_START, WINDOW_END, TZ)

    titles = {event.title for event in events}
    assert titles == {"Dentist appointment", "Piano lesson", "Trash day"}

    piano = next(event for event in events if event.title == "Piano lesson")
    local_start = piano.start.astimezone(TZ)
    assert (local_start.month, local_start.day, local_start.hour, local_start.minute) == (11, 10, 15, 30)


def test_all_day_event_is_flagged_and_uses_exclusive_end() -> None:
    events = parse_ics(ICS, CALENDAR, WINDOW_START, WINDOW_END, TZ)
    trash = next(event for event in events if event.title == "Trash day")

    assert trash.all_day is True
    assert (trash.end - trash.start).days == 1
    assert trash.start.astimezone(TZ).hour == 0


def test_event_fields_are_normalized() -> None:
    events = parse_ics(ICS, CALENDAR, WINDOW_START, WINDOW_END, TZ)
    dentist = next(event for event in events if event.title == "Dentist appointment")

    assert dentist.location == "123 Main St"
    assert dentist.description == "Bring insurance card"
    assert dentist.calendar_id == "test"
    assert dentist.uid.startswith("test:dentist:")


def test_window_filters_by_date() -> None:
    later = datetime(2025, 12, 1, 0, 0, tzinfo=TZ)
    events = parse_ics(ICS, CALENDAR, later, datetime(2025, 12, 8, tzinfo=TZ), TZ)
    assert [event.title for event in events] == ["Piano lesson"]


def test_invalid_ics_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_ics("not a calendar", CALENDAR, WINDOW_START, WINDOW_END, TZ)
