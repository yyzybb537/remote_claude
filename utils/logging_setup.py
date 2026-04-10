from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("/tmp/remote-claude")
_LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_ROLE_FILES = {
    "client": "client.log",
    "server": "server.log",
    "lark": "lark.log",
}


def get_role_log_path(role: str) -> Path:
    return LOG_DIR / _ROLE_FILES[role]


def setup_role_logging(role: str, level: int = logging.INFO) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"remote_claude.{role}")
    logger.setLevel(level)

    for handler in logger.handlers:
        if getattr(handler, "_remote_claude_role", None) == role:
            return logger

    handler = RotatingFileHandler(
        get_role_log_path(role),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler._remote_claude_role = role
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
