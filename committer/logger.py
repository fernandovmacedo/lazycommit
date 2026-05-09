"""Persistent file logger for post-mortem debugging of hangs and errors.

Writes to ~/.local/state/committer/committer.log (XDG_STATE_HOME aware).
Rotates at 2 MB, keeps 3 backups. Never raises; setup failures fall back to a
NullHandler so commit flows still proceed.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _log_path() -> Path:
    state_home = (
        os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    )
    log_dir = Path(state_home) / "committer"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "committer.log"


def _make_logger() -> logging.Logger:
    logger = logging.getLogger("committer")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    try:
        handler = RotatingFileHandler(
            _log_path(), maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s pid=%(process)d %(levelname)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        logger.addHandler(handler)
    except Exception:
        logger.addHandler(logging.NullHandler())
    return logger


_logger = _make_logger()


def log_debug(msg: str) -> None:
    _logger.debug(msg)


def log_info(msg: str) -> None:
    _logger.info(msg)


def log_warning(msg: str) -> None:
    _logger.warning(msg)


def log_error(msg: str, *, exc_info: bool = False) -> None:
    _logger.error(msg, exc_info=exc_info)
