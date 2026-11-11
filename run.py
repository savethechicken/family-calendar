#!/usr/bin/env python3
"""Run the calendar server: ``python run.py``."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn

from app.config import load_config
from app.main import create_app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    config_path = Path(os.environ.get("SKYLIGHT_CONFIG", "config.yaml"))
    config = load_config(config_path)
    uvicorn.run(
        create_app(config_path),
        host=config.server.host,
        port=config.server.port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
