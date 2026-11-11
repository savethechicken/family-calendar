"""ICS / iCal source.

Works with the "secret address in iCal format" from Google Calendar, plus
Outlook, iCloud, school portals and anything else that publishes an .ics feed.
No OAuth, no API keys, read-only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path

import httpx
import icalendar
import recurring_ical_events

from ..config import CalendarConfig
from .base import Event

log = logging.getLogger(__name__)

MAX_EVENTS = 2000
USER_AGENT = "skylight-calendar/0.1 (+https://github.com/)"


def _as_aware(value: datetime, tz) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value


def _component_window(component: icalendar.cal.Component, tz) -> tuple[datetime, datetime, bool]:
    """Return (start, end, all_day) for one expanded VEVENT component."""
    raw_start = component.get("DTSTART")
    if raw_start is None:
        raise ValueError("VEVENT without DTSTART")

    start_value = raw_start.dt
    all_day = isinstance(start_value, date) and not isinstance(start_value, datetime)

    if all_day:
        start = datetime.combine(start_value, dtime.min, tzinfo=tz)
    else:
        start = _as_aware(start_value, tz)

    raw_end = component.get("DTEND")
    if raw_end is not None:
        end_value = raw_end.dt
        if isinstance(end_value, date) and not isinstance(end_value, datetime):
            end = datetime.combine(end_value, dtime.min, tzinfo=tz)
        else:
            end = _as_aware(end_value, tz)
    else:
        raw_duration = component.get("DURATION")
        if raw_duration is not None:
            end = start + raw_duration.dt
        else:
            end = start + (timedelta(days=1) if all_day else timedelta(hours=1))

    if end <= start:
        end = start + (timedelta(days=1) if all_day else timedelta(minutes=30))
    return start, end, all_day


def _text(component: icalendar.cal.Component, key: str) -> str | None:
    value = component.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_ics(
    text: str,
    calendar: CalendarConfig,
    start: datetime,
    end: datetime,
    tz,
) -> list[Event]:
    """Expand an ICS feed into concrete events inside ``[start, end)``."""
    try:
        parsed = icalendar.Calendar.from_ical(text)
    except ValueError as exc:
        raise ValueError(f"Invalid ICS data: {exc}") from exc

    try:
        components = recurring_ical_events.of(parsed).between(start, end)
    except Exception as exc:
        raise ValueError(f"Could not expand recurring events: {exc}") from exc

    events: list[Event] = []
    for component in components:
        if component.name != "VEVENT":
            continue
        status = str(component.get("STATUS", "")).upper()
        if status == "CANCELLED":
            continue

        try:
            begins, finishes, all_day = _component_window(component, tz)
        except (ValueError, TypeError) as exc:
            log.debug("Skipping malformed event in %s: %s", calendar.id, exc)
            continue

        if finishes <= start or begins >= end:
            continue

        title = _text(component, "SUMMARY") or "Untitled event"
        uid = _text(component, "UID") or f"{calendar.id}-{begins.isoformat()}"
        description = _text(component, "DESCRIPTION")
        if description and len(description) > 2000:
            description = description[:2000].rstrip() + "..."

        events.append(
            Event(
                uid=f"{calendar.id}:{uid}:{begins.isoformat()}",
                calendar_id=calendar.id,
                title=title,
                start=begins,
                end=finishes,
                all_day=all_day,
                location=_text(component, "LOCATION"),
                description=description,
            )
        )

        if len(events) >= MAX_EVENTS:
            log.warning("Calendar %s returned more than %s events; truncating.", calendar.id, MAX_EVENTS)
            break

    return events


class FeedCache:
    """Disk + memory cache for raw feed bytes.

    The TV must keep working when the network is down, so a stale copy is
    always preferred over an error.
    """

    def __init__(self, cache_dir: Path, calendar_id: str) -> None:
        self.path = cache_dir / f"{calendar_id}.ics"
        self.meta_path = cache_dir / f"{calendar_id}.meta.json"
        self._text: str | None = None
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    def _load_disk(self) -> None:
        if self._text is not None or not self.path.exists():
            return
        try:
            self._text = self.path.read_text(encoding="utf-8", errors="replace")
            if self.meta_path.exists():
                meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
                self._fetched_at = float(meta.get("fetched_at", 0))
        except (OSError, ValueError) as exc:
            log.warning("Could not read cached feed %s: %s", self.path, exc)

    def get(self, ttl: int) -> tuple[str, bool] | None:
        """Return (text, stale) if a usable cached copy exists."""
        self._load_disk()
        if self._text is None:
            return None
        stale = (time.time() - self._fetched_at) > ttl
        return self._text, stale

    def store(self, text: str) -> None:
        self._text = text
        self._fetched_at = time.time()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".ics.tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self.path)
            meta_tmp = self.meta_path.with_suffix(".json.tmp")
            meta_tmp.write_text(
                json.dumps({"fetched_at": self._fetched_at}), encoding="utf-8"
            )
            meta_tmp.replace(self.meta_path)
        except OSError as exc:
            log.warning("Could not write feed cache %s: %s", self.path, exc)

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock


class IcsSource:
    def __init__(
        self,
        calendar: CalendarConfig,
        *,
        cache_dir: Path,
        tz,
    ) -> None:
        self._calendar = calendar
        self._tz = tz
        self._cache = FeedCache(cache_dir / "ics", calendar.id)
        self._client: httpx.AsyncClient | None = None
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT, "Accept": "text/calendar, */*"},
            )
        return self._client

    async def _download(self, url: str) -> str:
        if url.startswith("webcal://"):
            url = "https://" + url[len("webcal://") :]

        if url.startswith("file://"):
            return Path(url[len("file://") :]).read_text(encoding="utf-8", errors="replace")
        if not url.lower().startswith(("http://", "https://")):
            return Path(url).expanduser().read_text(encoding="utf-8", errors="replace")

        response = await self._http().get(url)
        response.raise_for_status()
        return response.text

    async def _feed(self) -> tuple[str, bool]:
        ttl = self._calendar.source.cache_ttl_seconds

        cached = self._cache.get(ttl)
        if cached is not None and not cached[1]:
            return cached[0], False

        async with self._cache.lock:
            # Another request may have refreshed it while we waited.
            cached = self._cache.get(ttl)
            if cached is not None and not cached[1]:
                return cached[0], False

            try:
                text = await self._download(self._calendar.source.url)
                if "<html" in text[:2000].lower() and "BEGIN:VCALENDAR" not in text:
                    raise ValueError(
                        "The URL returned an HTML page, not an ICS feed. "
                        "Use the calendar's secret iCal address."
                    )
                self._cache.store(text)
                self._last_error = None
                return text, False
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                log.warning("Calendar %s refresh failed: %s", self._calendar.id, exc)
                if cached is not None:
                    log.info("Serving stale cached feed for %s", self._calendar.id)
                    return cached[0], True
                raise

    async def fetch(self, start: datetime, end: datetime) -> list[Event]:
        text, _stale = await self._feed()
        return parse_ics(text, self._calendar, start, end, self._tz)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
