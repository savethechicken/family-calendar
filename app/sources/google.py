"""Google Calendar API source (optional upgrade from ICS).

Read-only, no Google SDK required: a stored OAuth refresh token is exchanged
for short-lived access tokens, then the REST API is queried directly.

Run ``python scripts/google_auth.py`` once to obtain the refresh token.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from urllib.parse import quote

import httpx

from ..config import CalendarConfig, ConfigError
from .base import Event

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"
USER_AGENT = "skylight-calendar/0.1"


class GoogleSource:
    def __init__(self, calendar: CalendarConfig, *, tz) -> None:
        self._calendar = calendar
        self._tz = tz
        source = calendar.source
        if not (source.client_id and source.client_secret and source.refresh_token):
            raise ConfigError(
                f"Calendar {calendar.id!r} uses type 'google' but is missing "
                "client_id, client_secret or refresh_token. "
                "Run `python scripts/google_auth.py` and copy the values into config.yaml."
            )
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=10.0),
            headers={"User-Agent": USER_AGENT},
        )
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def _token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token

        source = self._calendar.source
        response = await self._client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": source.client_id,
                "client_secret": source.client_secret,
                "refresh_token": source.refresh_token,
            },
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = payload["access_token"]
        self._expires_at = time.time() + int(payload.get("expires_in", 3600))
        return self._access_token

    async def _list_events(self, start: datetime, end: datetime) -> list[dict]:
        token = await self._token()
        calendar_id = quote(self._calendar.source.calendar_id, safe="")
        params: dict[str, str] = {
            "timeMin": start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "timeMax": end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "2500",
            "showDeleted": "false",
        }
        items: list[dict] = []
        page_token: str | None = None
        while True:
            if page_token:
                params["pageToken"] = page_token
            response = await self._client.get(
                f"{API_BASE}/calendars/{calendar_id}/events",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            payload = response.json()
            items.extend(payload.get("items", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                return items

    def _parse_start_end(self, item: dict) -> tuple[datetime, datetime, bool] | None:
        start_raw = item.get("start") or {}
        end_raw = item.get("end") or {}

        if "date" in start_raw:
            all_day = True
            start_day = date.fromisoformat(start_raw["date"])
            end_day = date.fromisoformat(end_raw.get("date", start_raw["date"]))
            if end_day <= start_day:
                end_day = start_day + timedelta(days=1)
            start = datetime.combine(start_day, dtime.min, tzinfo=self._tz)
            end = datetime.combine(end_day, dtime.min, tzinfo=self._tz)
            return start, end, all_day

        if "dateTime" not in start_raw:
            return None
        start = datetime.fromisoformat(start_raw["dateTime"])
        end = datetime.fromisoformat(end_raw.get("dateTime", start_raw["dateTime"]))
        if start.tzinfo is None:
            start = start.replace(tzinfo=self._tz)
        if end.tzinfo is None:
            end = end.replace(tzinfo=self._tz)
        if end <= start:
            end = start + timedelta(minutes=30)
        return start, end, False

    async def fetch(self, start: datetime, end: datetime) -> list[Event]:
        try:
            items = await self._list_events(start, end)
            self._last_error = None
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            log.warning("Google Calendar %s fetch failed: %s", self._calendar.id, exc)
            raise

        events: list[Event] = []
        for item in items:
            if item.get("status") == "cancelled":
                continue
            window = self._parse_start_end(item)
            if window is None:
                continue
            begins, finishes, all_day = window
            if finishes <= start or begins >= end:
                continue
            events.append(
                Event(
                    uid=f"{self._calendar.id}:{item.get('id', begins.isoformat())}:{begins.isoformat()}",
                    calendar_id=self._calendar.id,
                    title=(item.get("summary") or "Untitled event").strip(),
                    start=begins,
                    end=finishes,
                    all_day=all_day,
                    location=(item.get("location") or "").strip() or None,
                    description=(item.get("description") or "").strip() or None,
                )
            )
        return events

    async def aclose(self) -> None:
        await self._client.aclose()
