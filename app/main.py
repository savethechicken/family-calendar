"""FastAPI application: JSON API, kiosk UI and settings UI."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .config import Config, ConfigError, ensure_config_file, load_config
from .service import CalendarService
from .settings import (
    SettingsError,
    build_settings_payload,
    preview_feed,
    save_settings,
)
from .weather import WeatherService

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
MAX_RANGE_DAYS = 62
CONFIG_WATCH_SECONDS = 5


class FeedTestRequest(BaseModel):
    url: str


def _parse_datetime(value: str, tz) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid ISO datetime: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def _start_of_week(moment: datetime, week_starts_on: str) -> date:
    weekday = moment.weekday()  # Monday = 0
    first = 0 if week_starts_on == "monday" else 6
    return moment.date() - timedelta(days=(weekday - first) % 7)


def _config_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _require_admin(request: Request, config: Config) -> None:
    token = config.server.admin_token
    if not token:
        return
    supplied = request.headers.get("x-admin-token", "")
    if not secrets.compare_digest(supplied, token):
        raise HTTPException(
            status_code=401,
            detail="Settings password required.",
            headers={"WWW-Authenticate": "X-Admin-Token"},
        )


def _require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    if urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(status_code=403, detail="Cross-origin settings change blocked.")


async def reload_app_state(app: FastAPI) -> Config:
    """Re-read config.yaml and hot-swap the calendar/weather services."""
    async with app.state.reload_lock:
        config = load_config(app.state.config_path)
        service = CalendarService(config)
        weather = WeatherService(config.weather)
        old_service = app.state.service
        old_weather = app.state.weather
        app.state.config = config
        app.state.service = service
        app.state.weather = weather
        app.state.config_mtime = _config_mtime(app.state.config_path)

    for old in (old_service, old_weather):
        try:
            await old.aclose()
        except Exception:
            log.debug("Error closing previous service", exc_info=True)

    log.info("Configuration reloaded: %s calendar(s)", len(config.calendars))
    return config


async def _watch_config(app: FastAPI) -> None:
    """Reload automatically when config.yaml is edited outside the UI."""
    while True:
        await asyncio.sleep(CONFIG_WATCH_SECONDS)
        try:
            mtime = _config_mtime(app.state.config_path)
            if mtime and mtime != app.state.config_mtime:
                await reload_app_state(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Config reload failed; keeping the previous settings")
            app.state.config_mtime = _config_mtime(app.state.config_path)


def create_app(config_path: str | Path | None = None) -> FastAPI:
    path = Path(
        config_path
        or os.environ.get("FAMILY_CALENDAR_CONFIG")
        or os.environ.get("SKYLIGHT_CONFIG")
        or "config.yaml"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            ensure_config_file(path)
            config = load_config(path)
        except ConfigError as exc:
            log.error("Configuration error: %s", exc)
            raise

        app.state.config_path = Path(path).expanduser().resolve()
        app.state.config = config
        app.state.service = CalendarService(config)
        app.state.weather = WeatherService(config.weather)
        app.state.reload_lock = asyncio.Lock()
        app.state.config_mtime = _config_mtime(app.state.config_path)

        if not config.server.admin_token:
            log.warning(
                "Settings are not password protected. Set server.admin_token "
                "or SKYLIGHT_ADMIN_TOKEN if guests can reach this server."
            )

        log.info(
            "Family Calendar %s ready: %s calendar(s), timezone %s",
            __version__,
            len(config.calendars),
            config.display.timezone,
        )

        watcher = asyncio.create_task(_watch_config(app))
        try:
            yield
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            await app.state.service.aclose()
            await app.state.weather.aclose()

    app = FastAPI(
        title="Family Calendar",
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

    # --- Settings ---------------------------------------------------------

    @app.get("/api/settings")
    async def get_settings(request: Request) -> dict[str, Any]:
        cfg = config(request)
        _require_admin(request, cfg)
        return build_settings_payload(cfg, request.app.state.config_path)

    @app.put("/api/settings")
    async def update_settings(
        request: Request, payload: dict[str, Any] = Body(...),  # noqa: B008
    ) -> dict[str, Any]:
        cfg = config(request)
        _require_admin(request, cfg)
        _require_same_origin(request)

        try:
            save_settings(request.app.state.config_path, payload)
        except SettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        new_config = await reload_app_state(request.app)
        return build_settings_payload(new_config, request.app.state.config_path)

    @app.post("/api/settings/test-feed")
    async def test_feed(request: Request, payload: FeedTestRequest) -> dict[str, Any]:
        cfg = config(request)
        _require_admin(request, cfg)
        _require_same_origin(request)
        try:
            return await preview_feed(payload.url, cfg.display.tz)
        except SettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- Pages ------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/settings", include_in_schema=False)
    async def settings_page() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "settings.html",
            headers={"Cache-Control": "no-cache"},
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()
