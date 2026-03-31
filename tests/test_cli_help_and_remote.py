#!/usr/bin/env python3

import io
import logging
import os
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import remote_claude


REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_bin_remote_claude_lark_help_exits_cleanly_without_env_prompt(tmp_path):
    home_dir = tmp_path / "lark_help_home"
    (home_dir / ".remote-claude").mkdir(parents=True)

    result = subprocess.run(
        [str(REPO_ROOT / "bin/remote-claude"), "lark", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home_dir)},
    )

    assert result.returncode == 0
    assert "usage: remote_claude.py lark" in result.stdout
    assert "飞书客户端尚未配置" not in result.stdout


def test_lark_without_subcommand_prints_help_and_returns_zero():
    output = io.StringIO()
    with patch("sys.argv", ["remote_claude.py", "lark"]):
        with redirect_stdout(output):
            result = remote_claude.main()

    assert result == 0
    text = output.getvalue()
    assert "usage: remote_claude.py lark" in text
    assert "查看飞书客户端状态" in text


def test_bin_remote_claude_help_exits_cleanly_without_spawning_session(tmp_path):
    home_dir = tmp_path / "remote_help_home"
    (home_dir / ".remote-claude").mkdir(parents=True)

    result = subprocess.run(
        [str(REPO_ROOT / "bin/remote-claude"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home_dir)},
    )

    assert result.returncode == 0
    assert "Remote Claude - 双端共享 Claude CLI 工具" in result.stdout
    assert "启动新会话" in result.stdout


def test_management_subcommand_help_and_empty_invocation_do_not_create_side_effects(tmp_path):
    commands = [
        ["config", "--help"],
        ["config"],
        ["connection", "--help"],
        ["connection"],
        ["conn", "--help"],
        ["connect", "--help"],
        ["remote", "--help"],
        ["token", "--help"],
        ["regenerate-token", "--help"],
        ["connection", "list", "--help"],
        ["connection", "show", "--help"],
        ["connection", "delete", "--help"],
        ["connection", "set-default", "--help"],
        ["config", "reset", "--help"],
    ]

    for command in commands:
        home_dir = tmp_path / "_".join(command).replace("-", "_")
        (home_dir / ".remote-claude").mkdir(parents=True)

        before = {p.name for p in Path("/tmp/remote-claude").glob("*")}
        result = subprocess.run(
            [str(REPO_ROOT / "bin/remote-claude"), *command],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(home_dir)},
        )
        after = {p.name for p in Path("/tmp/remote-claude").glob("*")}

        assert result.returncode == 0, (command, result.stdout, result.stderr)
        assert "飞书客户端尚未配置" not in result.stdout, (command, result.stdout)
        assert not any(name.startswith(home_dir.name) for name in after - before), (command, sorted(after - before))


def test_shortcut_help_commands_exit_cleanly_without_spawn_error(tmp_path):
    for rel in ("bin/cla", "bin/cl", "bin/cx", "bin/cdx"):
        home_dir = tmp_path / rel.replace("/", "_")
        remote_home = home_dir / ".remote-claude"
        remote_home.mkdir(parents=True)

        before = {p.name for p in Path("/tmp/remote-claude").glob("*")}
        result = subprocess.run(
            [str(REPO_ROOT / rel), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(home_dir)},
        )
        after = {p.name for p in Path("/tmp/remote-claude").glob("*")}

        assert result.returncode == 0, (rel, result.stdout, result.stderr)
        assert "usage: remote_claude.py start" in result.stdout, (rel, result.stdout)
        assert "start 子命令不支持透传帮助参数" not in result.stdout, (rel, result.stdout)
        assert "飞书客户端尚未配置" not in result.stdout, (rel, result.stdout)
        assert not any(name.startswith(home_dir.name) for name in after - before), (rel, sorted(after - before))


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


def test_validate_remote_args_returns_parse_error_without_duplicate_host_message(capsys):
    args = SimpleNamespace(host="10.0.0.1:bad/demo", port=10000, token="t", name="demo")
    assert remote_claude.validate_remote_args(args) is None
    out = capsys.readouterr().out
    assert "错误: 端口格式无效: bad" in out
    assert "错误: 远程模式需要 --host 参数" not in out


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


def test_cmd_kill_deletes_token_file(monkeypatch, tmp_path):
    args = SimpleNamespace(remote=False, name="demo")
    token_file = tmp_path / "demo_token.json"
    token_file.write_text("token")

    monkeypatch.setattr(remote_claude, "is_session_active", lambda session_name: True)
    monkeypatch.setattr(remote_claude, "tmux_session_exists", lambda session_name: False)
    monkeypatch.setattr(remote_claude, "cleanup_session", lambda session_name: None)

    class FakeTokenManager:
        def __init__(self, session_name):
            self.session_name = session_name

        def delete_token_file(self):
            token_file.unlink(missing_ok=True)
            return True

    monkeypatch.setattr("server.token_manager.TokenManager", FakeTokenManager)

    removed_sessions = []
    monkeypatch.setattr(
        "utils.runtime_config.remove_session_mapping",
        lambda session_name: removed_sessions.append(session_name),
    )

    result = remote_claude.cmd_kill(args)

    assert result == 0
    assert token_file.exists() is False
    assert removed_sessions == ["demo"]
