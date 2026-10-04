"""Rotating file logging for `run` and the tray app."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .platform.paths import agent_data_dir

_LOG_NAME = "djutil_agent"


def logs_dir() -> Path:
    d = agent_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_file_logging(verbose: bool = False) -> Path:
    """Attach a rotating file handler (5 x 1 MB) to the agent logger.

    Console output still flows through the handlers installed by
    `logging.basicConfig` in the CLI callback — this only adds the file.
    """
    log_path = logs_dir() / "agent.log"
    logger = logging.getLogger(_LOG_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    # Avoid stacking handlers when called twice (e.g. tests).
    for h in logger.handlers:
        if isinstance(h, RotatingFileHandler) and getattr(
            h, "baseFilename", None
        ) == str(log_path):
            return log_path
    handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.debug("file logging initialised")
    return log_path
