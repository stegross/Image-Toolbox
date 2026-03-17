"""Centralized logging system for VI-Toolbox (REQ-HS-017)."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_APP_LOGGER = "vi_toolbox"


def initialize_logging(log_dir: Path | None = None, level: int = logging.DEBUG) -> None:
    """Configure the application-wide logging system.

    Sets up a console handler and, if *log_dir* is provided, a
    size-rotating file handler.  Safe to call multiple times — subsequent
    calls are no-ops if the logger already has handlers attached.

    Parameters
    ----------
    log_dir : Path | None
        Directory for rotating log files.  Pass ``None`` to skip file
        logging (e.g. during testing).
    level : int
        Root log level for the ``vi_toolbox`` logger.
        Default: :data:`logging.DEBUG`.
    """
    logger = logging.getLogger(_APP_LOGGER)
    logger.setLevel(level)

    if logger.handlers:
        return  # already initialised

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(level)
    logger.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "vi_toolbox.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``vi_toolbox`` namespace.

    Parameters
    ----------
    name : str
        Sub-logger name (e.g. ``"shell.main_window"``).

    Returns
    -------
    logging.Logger
        Logger named ``vi_toolbox.<name>``.
    """
    return logging.getLogger(f"{_APP_LOGGER}.{name}")
