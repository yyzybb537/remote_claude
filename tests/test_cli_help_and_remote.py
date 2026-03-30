#!/usr/bin/env python3

import io
import logging
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import remote_claude


def test_parse_host_session_keeps_positional_session_name():
    args = SimpleNamespace(host="10.0.0.1", port=10000, token="t", name="assistant_public")
    host, port, session, token = remote_claude.parse_host_session(args)
    assert (host, port, session, token) == ("10.0.0.1", 10000, "assistant_public", "t")


def test_validate_remote_args_accepts_current_attach_order():
    args = SimpleNamespace(host="10.0.0.1", port=10000, token="t", name="assistant_public")
    assert remote_claude.validate_remote_args(args, "assistant_public") == (
        "10.0.0.1",
        10000,
        "assistant_public",
        "t",
    )


def test_main_help_exits_cleanly(capsys):
    with patch("sys.argv", ["remote_claude.py", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            remote_claude.main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "Remote Claude" in out


def test_lark_help_exits_cleanly(capsys):
    with patch("sys.argv", ["remote_claude.py", "lark", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            remote_claude.main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "usage: remote_claude.py lark" in out
    assert "查看飞书客户端状态" in out


def test_lark_without_subcommand_prints_help_and_returns_zero():
    output = io.StringIO()
    with patch("sys.argv", ["remote_claude.py", "lark"]):
        with redirect_stdout(output):
            result = remote_claude.main()

    assert result == 0
    text = output.getvalue()
    assert "usage: remote_claude.py lark" in text
    assert "查看飞书客户端状态" in text


def test_cmd_attach_remote_logs_tracing(monkeypatch, caplog):
    args = SimpleNamespace(
        name="assistant_public",
        config_name="",
        save=False,
        remote=True,
        host="10.0.0.1",
        token="secret-token",
        port=10000,
    )

    monkeypatch.setattr("client.run_remote_client", lambda host, session, token, port: 0)

    with caplog.at_level(logging.INFO):
        result = remote_claude.cmd_attach(args)

    assert result == 0
    assert any(
        "stage=remote_args_parsed" in record.message and "has_token=True" in record.message
        for record in caplog.records
    )


def test_cmd_list_remote_logs_tracing(monkeypatch, caplog):
    args = SimpleNamespace(remote=True, host="10.0.0.1", token="secret-token", port=10000, name="list")

    monkeypatch.setattr(remote_claude, "run_remote_control", lambda host, port, session, token, action: 0)

    with caplog.at_level(logging.INFO):
        result = remote_claude.cmd_list(args)

    assert result == 0
    assert any(
        "stage=remote_args_parsed" in record.message and "command=list" in record.message
        for record in caplog.records
    )


def test_validate_remote_args_requires_session_when_fallback_missing(capsys):
    args = SimpleNamespace(host="10.0.0.1", port=10000, token="t", name="")
    assert remote_claude.validate_remote_args(args) is None
    assert "错误: 请指定会话名称" in capsys.readouterr().out


def test_cmd_kill_remote_logs_tracing(monkeypatch, caplog):
    args = SimpleNamespace(remote=True, host="10.0.0.1", token="secret-token", port=10000, name="demo")

    monkeypatch.setattr(remote_claude, "run_remote_control", lambda host, port, session, token, action: 0)

    with caplog.at_level(logging.INFO):
        result = remote_claude.cmd_kill(args)

    assert result == 0
    assert any(
        "stage=remote_args_parsed" in record.message and "command=kill" in record.message
        for record in caplog.records
    )
