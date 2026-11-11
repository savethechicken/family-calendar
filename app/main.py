"""FastAPI application: JSON API + the kiosk web UI."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Config, ConfigError, load_config
from .service import CalendarService
from .weather import WeatherService

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
MAX_RANGE_DAYS = 62


def _parse_datetime(value: str, tz) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid ISO datetime: {value!r}") from exc
    if isinstance(parsed, datetime) and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def _start_of_week(moment: datetime, week_starts_on: str) -> date:
    weekday = moment.weekday()  # Monday = 0
    first = 0 if week_starts_on == "monday" else 6
    return moment.date() - timedelta(days=(weekday - first) % 7)


def create_app(config_path: str | Path | None = None) -> FastAPI:
    path = Path(config_path or os.environ.get("SKYLIGHT_CONFIG", "config.yaml"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            config = load_config(path)
        except ConfigError as exc:
            log.error("Configuration error: %s", exc)
            raise

        service = CalendarService(config)
        weather = WeatherService(config.weather)
        app.state.config = config
        app.state.service = service
        app.state.weather = weather

        log.info(
            "Skylight %s ready: %s calendar(s), timezone %s",
            __version__,
            len(config.calendars),
            config.display.timezone,
        )
        try:
            yield
        finally:
            await service.aclose()
            await weather.aclose()

    app = FastAPI(
        title="Skylight Calendar",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def no_cache_api(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def config(request: Request) -> Config:
        return request.app.state.config

    @app.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        cfg = config(request)
        return {
            "ok": True,
            "version": __version__,
            "timezone": cfg.display.timezone,
            "calendars": [calendar.id for calendar in cfg.calendars],
        }

    @app.get("/api/config")
    async def public_config(request: Request) -> dict[str, Any]:
        return config(request).public_dict()

    @app.get("/api/events")
    async def events(
        request: Request,
        start: str | None = Query(default=None, description="ISO datetime (inclusive)"),
        end: str | None = Query(default=None, description="ISO datetime (exclusive)"),
        days: int = Query(default=7, ge=1, le=MAX_RANGE_DAYS),
    ) -> dict[str, Any]:
        cfg = config(request)
        tz = cfg.display.tz
        now = datetime.now(tz)

        if start:
            range_start = _parse_datetime(start, tz)
        else:
            first_day = _start_of_week(now, cfg.display.week_starts_on)
            range_start = datetime.combine(first_day, dtime.min, tzinfo=tz)

        if end:
            range_end = _parse_datetime(end, tz)
        else:
            range_end = range_start + timedelta(days=days)

        if range_end <= range_start:
            raise HTTPException(status_code=400, detail="`end` must be after `start`.")
        if (range_end - range_start) > timedelta(days=MAX_RANGE_DAYS):
            raise HTTPException(
                status_code=400,
                detail=f"Range too large; maximum is {MAX_RANGE_DAYS} days.",
            )

        payload, errors = await request.app.state.service.events(range_start, range_end)
        return {
            "events": payload,
            "errors": errors,
            "range": {"start": range_start.isoformat(), "end": range_end.isoformat()},
            "serverNow": now.isoformat(),
            "generatedAt": datetime.now(tz).isoformat(),
        }

    @app.get("/api/weather")
    async def weather(request: Request) -> dict[str, Any]:
        return await request.app.state.weather.get()

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-cache"},
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()
