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


def test_remote_claude_module_doc_and_epilog_use_current_public_entrypoints():
    content = (REPO_ROOT / "remote_claude.py").read_text(encoding="utf-8")
    assert 'Remote Claude - 双端共享 Claude/Codex CLI 工具' in content
    assert 'python3 remote_claude.py' not in content
    assert 'start mywork --launcher Codex' in content
    assert 'connect <host>' in content
    assert 'remote list' in content


def test_main_help_exits_cleanly(capsys):
    with patch("sys.argv", ["remote_claude.py", "lark", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            remote_claude.main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "usage: remote-claude lark" in out
    assert "usage: remote_claude.py lark" not in out
    assert "查看飞书客户端状态" in out


def test_main_help_includes_uninstall_command():
    content = (REPO_ROOT / "remote_claude.py").read_text(encoding="utf-8")
    assert 'subparsers.add_parser("uninstall"' in content


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
    assert "usage: remote-claude lark" in result.stdout
    assert "usage: remote_claude.py lark" not in result.stdout
    assert "飞书客户端尚未配置" not in result.stdout


def test_lark_without_subcommand_prints_help_and_returns_zero():
    output = io.StringIO()
    with patch("sys.argv", ["remote_claude.py", "lark"]):
        with redirect_stdout(output):
            result = remote_claude.main()

    assert result == 0
    text = output.getvalue()
    assert "usage: remote-claude lark" in text
    assert "usage: remote_claude.py lark" not in text
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
    assert "Remote Claude - 双端共享 Claude/Codex CLI 工具" in result.stdout
    assert "启动新会话" in result.stdout
    assert "remote_claude.py" not in result.stdout


def test_main_help_uses_launcher_wording_only(tmp_path):
    home_dir = tmp_path / "main_help_launcher_only"
    (home_dir / ".remote-claude").mkdir(parents=True)

    install_dir_file = REPO_ROOT / "test-results" / "install_dir.txt"
    env = {**os.environ, "HOME": str(home_dir)}
    command_path = REPO_ROOT / "bin" / "remote-claude"
    if install_dir_file.exists():
        install_dir = Path(install_dir_file.read_text(encoding="utf-8").strip())
        candidate = install_dir / "node_modules" / "remote-claude"
        if candidate.exists():
            broken_python = candidate / ".venv" / "bin" / "python3"
            if broken_python.exists() or broken_python.is_symlink():
                broken_python.unlink()
            command_path = candidate / "bin" / "remote-claude"

    result = subprocess.run(
        [str(command_path), "start", "demo", "--help"],
        cwd=command_path.parent.parent,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert "--launcher" in result.stdout
    assert "--cli-type" not in result.stdout
    assert "--cli_type" not in result.stdout


def test_management_subcommand_help_and_empty_invocation_do_not_create_side_effects(tmp_path):
    commands = [
        ["config", "--help"],
        ["connection", "--help"],
        ["conn", "--help"],
        ["connect", "--help"],
        ["remote", "--help"],
        ["token", "--help"],
        ["regenerate-token", "--help"],
        ["uninstall", "--help"],
        ["connection", "list", "--help"],
        ["connection", "show", "--help"],
        ["connection", "delete", "--help"],
        ["connection", "set-default", "--help"],
        ["config", "reset", "--help"],
        ["lark", "--help"],
    ]

    install_dir_file = REPO_ROOT / "test-results" / "install_dir.txt"
    command_path = REPO_ROOT / "bin" / "remote-claude"
    command_cwd = REPO_ROOT
    env_overrides = {}
    broken_python = None
    if install_dir_file.exists():
        install_dir = Path(install_dir_file.read_text(encoding="utf-8").strip())
        candidate = install_dir / "node_modules" / "remote-claude"
        if candidate.exists():
            command_path = candidate / "bin" / "remote-claude"
            command_cwd = candidate
            env_overrides = {
                "REMOTE_CLAUDE_UV_PROJECT_DIR": str(candidate),
                "REMOTE_CLAUDE_FORCE_UV_RUN": "1",
            }
            broken_python = candidate / ".venv" / "bin" / "python3"

    for command in commands:
        home_dir = tmp_path / "_".join(command).replace("-", "_")
        (home_dir / ".remote-claude").mkdir(parents=True)

        if broken_python is not None and (broken_python.exists() or broken_python.is_symlink()):
            broken_python.unlink()

        before = {p.name for p in Path("/tmp/remote-claude").glob("*")}
        env = {**os.environ, "HOME": str(home_dir), **env_overrides}
        result = subprocess.run(
            [str(command_path), *command],
            cwd=command_cwd,
            capture_output=True,
            text=True,
            env=env,
        )
        after = {p.name for p in Path("/tmp/remote-claude").glob("*")}

        assert result.returncode == 0, (command, result.stdout, result.stderr)
        assert "检测到依赖变更，正在更新 Python 环境..." not in result.stdout, (command, result.stdout)
        assert "scripts/setup.sh --npm --lazy" not in result.stderr, (command, result.stderr)
        assert "飞书客户端尚未配置" not in result.stdout, (command, result.stdout)
        assert not any(name.startswith(home_dir.name) for name in after - before), (command, sorted(after - before))


def test_connection_shortcuts_fall_back_to_uv_when_system_python_too_old(tmp_path):
    install_dir_file = REPO_ROOT / "test-results" / "install_dir.txt"
    if not install_dir_file.exists():
        pytest.skip("requires installed package fixture")

    install_dir = Path(install_dir_file.read_text(encoding="utf-8").strip())
    candidate = install_dir / "node_modules" / "remote-claude"
    if not candidate.exists():
        pytest.skip("requires installed package fixture")

    home_dir = tmp_path / "connection_shortcut_old_python"
    (home_dir / ".remote-claude").mkdir(parents=True)
    broken_python = candidate / ".venv" / "bin" / "python3"
    if broken_python.exists() or broken_python.is_symlink():
        broken_python.unlink()

    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir()
    (shim_dir / "python3").write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"--version\" ]; then\n"
        "  echo 'Python 3.9.0'\n"
        "  exit 0\n"
        "fi\n"
        "exec /usr/bin/python3 \"$@\"\n",
        encoding="utf-8",
    )
    (shim_dir / "python3").chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(home_dir),
        "PATH": f"{shim_dir}:{os.environ.get('PATH', '')}",
        "REMOTE_CLAUDE_UV_PROJECT_DIR": str(candidate),
        "REMOTE_CLAUDE_FORCE_UV_RUN": "1",
    }

    result = subprocess.run(
        [str(candidate / "bin" / "remote-claude"), "connection"],
        cwd=candidate,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "没有保存的连接配置" in result.stdout


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
        assert "检测到依赖变更，正在更新 Python 环境..." not in result.stdout, (rel, result.stdout)
        assert "scripts/setup.sh --npm --lazy" not in result.stderr, (rel, result.stderr)
        assert "Remote Claude 快捷命令" in result.stdout, (rel, result.stdout)
        assert "cla    Claude   正常（需确认）    启动 Claude 会话" in result.stdout, (rel, result.stdout)
        assert "cl     Claude   跳过权限确认      快速启动 Claude 会话" in result.stdout, (rel, result.stdout)
        assert "cx     Codex    跳过权限确认      快速启动 Codex 会话" in result.stdout, (rel, result.stdout)
        assert "cdx    Codex    正常（需确认）    启动 Codex 会话" in result.stdout, (rel, result.stdout)
        assert "start 子命令不支持透传帮助参数" not in result.stdout, (rel, result.stdout)
        assert "飞书客户端尚未配置" not in result.stdout, (rel, result.stdout)
        assert not any(name.startswith(home_dir.name) for name in after - before), (rel, sorted(after - before))


def test_main_help_lists_management_commands(tmp_path):
    home_dir = tmp_path / "main_help_commands"
    (home_dir / ".remote-claude").mkdir(parents=True)

    result = subprocess.run(
        [str(REPO_ROOT / "bin/remote-claude"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home_dir)},
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "Remote Claude - 双端共享 Claude/Codex CLI 工具" in result.stdout
    assert "connection       远程连接配置管理" in result.stdout
    assert "regenerate-token 重新生成 token" in result.stdout
    assert "remote           远程控制" in result.stdout




def test_remote_client_module_imports_without_deprecation_warning_when_asyncio_client_available():
    import importlib
    import sys
    import warnings

    sys.modules.pop("client.remote_client", None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        remote_client = importlib.import_module("client.remote_client")

    messages = [str(item.message) for item in caught if issubclass(item.category, DeprecationWarning)]
    assert callable(remote_client.connect)
    assert not any("websockets.client" in message for message in messages)
    assert not any("websockets.legacy" in message for message in messages)


def test_cmd_attach_remote_logs_tracing(monkeypatch, caplog):
    args = SimpleNamespace(remote=True, host="10.0.0.1", token="secret-token", port=10000, name="")

    calls = []

    def fake_run_remote_control(host, port, session, token, action):
        calls.append((host, port, session, token, action))
        return 0

    monkeypatch.setattr(remote_claude, "run_remote_control", fake_run_remote_control)

    result = remote_claude.cmd_list(args)

    assert result == 0
    assert calls == [("10.0.0.1", 10000, "list", "secret-token", "list")]


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


def test_lark_commands_use_public_remote_claude_entrypoint_in_runtime_output():
    content = (REPO_ROOT / "remote_claude.py").read_text(encoding="utf-8")
    assert "remote-claude lark status" in content
    assert "remote-claude lark stop" in content
    assert "remote-claude lark start" in content
    assert "python3 remote_claude.py lark status" not in content
    assert "python3 remote_claude.py lark stop" not in content
    assert "python3 remote_claude.py lark start" not in content


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
