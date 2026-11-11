"""Merges every configured calendar into one sorted list of events."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from .config import Config
from .sources import CalendarSource, Event, build_sources

log = logging.getLogger(__name__)


class CalendarService:
    def __init__(
        self,
        config: Config,
        sources: dict[str, CalendarSource] | None = None,
    ) -> None:
        self.config = config
        self.sources = sources if sources is not None else build_sources(config)
        self._calendars = {calendar.id: calendar for calendar in config.calendars}

    async def events(
        self, start: datetime, end: datetime
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Fetch all calendars concurrently and normalize the results.

        Returns the event payloads plus a map of ``calendar_id -> error`` for
        any source that failed. A failure never takes down the whole screen.
        """
        results = await asyncio.gather(
            *(source.fetch(start, end) for source in self.sources.values()),
            return_exceptions=True,
        )

        merged: list[Event] = []
        errors: dict[str, str] = {}

        for (calendar_id, _source), result in zip(self.sources.items(), results):
            if isinstance(result, BaseException):
                errors[calendar_id] = f"{type(result).__name__}: {result}"
                log.warning("Calendar %s failed: %s", calendar_id, result)
                continue
            merged.extend(result)

        merged.sort(key=lambda event: (event.start, event.end, event.title.lower()))

        payload = [
            event.as_dict(
                calendar_name=self._calendars[event.calendar_id].name,
                color=self._calendars[event.calendar_id].color,
            )
            for event in merged
        ]
        return payload, errors

    async def aclose(self) -> None:
        for source in self.sources.values():
            try:
                await source.aclose()
            except Exception:
                log.debug("Error closing source", exc_info=True)
