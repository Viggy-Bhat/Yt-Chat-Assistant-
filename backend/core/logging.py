"""Logging configuration via loguru."""

from __future__ import annotations

import sys

from loguru import logger

from backend.core.config import get_settings


def setup_logging() -> None:
    """Configure loguru with a single stderr sink.

    Safe to call multiple times; loguru de-dupes sinks.
    """
    settings = get_settings()
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
        backtrace=False,
        diagnose=False,
    )


def get_logger():
    """Return the configured loguru logger."""
    return logger
