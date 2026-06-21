"""Structured, single-line logging (FR11, G6).

Each warmup attempt and each save/restore emits exactly one line so a silent
failure is impossible to miss. Output goes to stderr and, optionally, a file.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOGGER_NAME = "cwarm"
_FORMAT = "%(asctime)s %(levelname)s %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"


def setup_logging(log_file: str | Path | None = None, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.handlers.clear()
    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def _fields(**fields: object) -> str:
    return " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)


def log_attempt(account_id: str, outcome: str, reset: str | None = None, error: str | None = None) -> None:
    """One structured line per warmup attempt (FR11)."""
    logger = get_logger()
    msg = "warmup " + _fields(account=account_id, outcome=outcome, reset=reset, error=error)
    if outcome == "failed":
        logger.error(msg)
    else:
        logger.info(msg)


def log_event(event: str, **fields: object) -> None:
    """One structured line for batch lifecycle events (save/restore, etc.)."""
    get_logger().info(f"{event} " + _fields(**fields))
