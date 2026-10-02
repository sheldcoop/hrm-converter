"""File logging: full technical details go to a log file, not to the console."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

PACKAGE_LOGGER = "hrm_converter"


def setup_logging(directory: Path, level: str = "INFO") -> Path:
    """Attach a fresh file handler to the package logger and return the log path."""
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / f"hrm_converter_{datetime.now():%Y%m%d_%H%M%S}.log"

    logger = logging.getLogger(PACKAGE_LOGGER)
    close_logging()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logger.addHandler(handler)
    return log_path


def close_logging() -> None:
    logger = logging.getLogger(PACKAGE_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
