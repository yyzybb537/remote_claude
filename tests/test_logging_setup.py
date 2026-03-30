import logging
from pathlib import Path

from logging.handlers import RotatingFileHandler

from utils.logging_setup import LOG_DIR, get_role_log_path, setup_role_logging


def test_get_role_log_path_uses_tmp_directory():
    assert get_role_log_path("client") == Path("/tmp/remote-claude/client.log")
    assert get_role_log_path("server") == Path("/tmp/remote-claude/server.log")
    assert get_role_log_path("lark") == Path("/tmp/remote-claude/lark.log")


def test_setup_role_logging_uses_rotating_file_handler():
    logger = setup_role_logging("client", level=20)
    handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    handler = handlers[0]
    assert Path(handler.baseFilename) == LOG_DIR / "client.log"
    assert handler.maxBytes == 10 * 1024 * 1024
    assert handler.backupCount == 5


def test_setup_role_logging_is_idempotent():
    logger = logging.getLogger("remote_claude.client")
    logger.handlers.clear()

    setup_role_logging("client", level=logging.INFO)
    setup_role_logging("client", level=logging.INFO)

    handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1


def test_server_role_log_path_is_tmp_server_log():
    assert get_role_log_path("server") == Path("/tmp/remote-claude/server.log")


def test_lark_role_log_path_is_tmp_lark_log():
    assert str(get_role_log_path("lark")) == "/tmp/remote-claude/lark.log"
