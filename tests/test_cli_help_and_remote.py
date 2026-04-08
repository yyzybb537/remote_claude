#!/usr/bin/env python3

import logging
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

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
    assert "飞书客户端尚未配置" not in result.stdout


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

    assert result.returncode == 0, result.stderr
    assert "scripts/setup.sh --npm --lazy" not in result.stderr


def test_remote_list_does_not_require_session_name():
    from remote_claude import validate_remote_args

    args = type("Args", (), {
        "host": "example.com",
        "port": 8765,
        "token": "secret-token",
        "name": "",
    })()

    result = validate_remote_args(args, session_fallback="list")
    assert result == ("example.com", 8765, "list", "secret-token")


def test_cmd_list_remote_prints_single_session_status(monkeypatch, capsys):
    def fake_validate_remote_args(args, session_fallback=None):
        assert session_fallback == "list"
        return ("10.0.0.1", 10000, "demo", "secret-token")

    def fake_print_remote_list_result(message):
        print("远程会话:")
        print("- demo (active=是, tmux=是)")

    calls = []

    def fake_run_remote_control(host, port, session, token, operation):
        calls.append((host, port, session, token, operation))
        remote_claude._print_remote_list_result('{"sessions":[{"session":"demo","active":true,"tmux":true}]}')
        return 0

    monkeypatch.setattr(remote_claude, "validate_remote_args", fake_validate_remote_args)
    monkeypatch.setattr(remote_claude, "_print_remote_list_result", fake_print_remote_list_result)
    monkeypatch.setattr(remote_claude, "run_remote_control", fake_run_remote_control)

    args = SimpleNamespace(remote=True, host="10.0.0.1", port=10000, token="secret-token", name="")

    result = remote_claude.cmd_list(args)

    assert result == 0
    assert calls == [("10.0.0.1", 10000, "demo", "secret-token", "list")]
    out = capsys.readouterr().out
    assert "远程会话:" in out
    assert "demo" in out
    assert "active=是" in out
    assert "tmux=是" in out


def test_cmd_remote_uses_validate_remote_args_and_run_remote_control(monkeypatch):
    calls = []

    def fake_validate_remote_args(args, session_fallback=None):
        calls.append(("validate", args, session_fallback))
        return ("10.0.0.1", 10000, "demo", "secret-token")

    def fake_run_remote_control(host, port, session, token, operation):
        calls.append(("run", host, port, session, token, operation))
        return 0

    monkeypatch.setattr(remote_claude, "validate_remote_args", fake_validate_remote_args)
    monkeypatch.setattr(remote_claude, "run_remote_control", fake_run_remote_control)

    args = SimpleNamespace(remote=True, host="10.0.0.1", port=10000, token="secret-token", session="demo")

    result = remote_claude.cmd_token(args)

    assert result == 0
    assert calls[0][0] == "validate"
    assert calls[1] == ("run", "10.0.0.1", 10000, "demo", "secret-token", "token")





def test_cmd_token_local_prints_human_readable_token(monkeypatch, capsys):
    class FakeManager:
        def __init__(self, session_name, data_dir):
            assert session_name == "demo"

        def get_or_create_token(self):
            return "secret-token-value"

    monkeypatch.setattr("server.token_manager.TokenManager", FakeManager)
    monkeypatch.setattr(remote_claude, "_get_user_data_dir", lambda: "/tmp/demo")

    args = SimpleNamespace(remote=False, session="demo")

    result = remote_claude.cmd_token(args)

    assert result == 0
    out = capsys.readouterr().out
    assert "会话 Token:" in out
    assert "demo" in out
    assert "secret-token-value" in out


def test_cmd_regenerate_token_local_prints_human_readable_token(monkeypatch, capsys):
    class FakeManager:
        def __init__(self, session_name, data_dir):
            assert session_name == "demo"

        def regenerate_token(self):
            return "new-secret-token"

    monkeypatch.setattr("server.token_manager.TokenManager", FakeManager)
    monkeypatch.setattr(remote_claude, "_get_user_data_dir", lambda: "/tmp/demo")

    args = SimpleNamespace(remote=False, session="demo")

    result = remote_claude.cmd_regenerate_token(args)

    assert result == 0
    out = capsys.readouterr().out
    assert "新会话 Token:" in out
    assert "demo" in out
    assert "new-secret-token" in out
def test_cmd_status_remote_prints_human_readable_status(monkeypatch, capsys):
    def fake_validate_remote_args(args, session_fallback=None):
        assert session_fallback == "demo"
        return ("10.0.0.1", 10000, "demo", "secret-token")

    calls = []

    def fake_run_remote_control(host, port, session, token, operation):
        calls.append((host, port, session, token, operation))
        remote_claude._print_remote_status_result('{"session":"demo","active":true,"tmux":false}')
        return 0

    monkeypatch.setattr(remote_claude, "validate_remote_args", fake_validate_remote_args)
    monkeypatch.setattr(remote_claude, "run_remote_control", fake_run_remote_control)

    args = SimpleNamespace(remote=True, host="10.0.0.1", port=10000, token="secret-token", name="demo")

    result = remote_claude.cmd_status(args)

    assert result == 0
    assert calls == [("10.0.0.1", 10000, "demo", "secret-token", "status")]
    out = capsys.readouterr().out
    assert "会话状态:" in out
    assert "demo" in out
    assert "active=是" in out
    assert "tmux=否" in out




def test_cmd_status_remote_prints_human_readable_status(monkeypatch, capsys):
    def fake_validate_remote_args(args, session_fallback=None):
        assert session_fallback == "demo"
        return ("10.0.0.1", 10000, "demo", "secret-token")

    calls = []

    def fake_run_remote_control(host, port, session, token, operation):
        calls.append((host, port, session, token, operation))
        remote_claude._print_remote_status_result('{"session":"demo","active":true,"tmux":false}')
        return 0

    monkeypatch.setattr(remote_claude, "validate_remote_args", fake_validate_remote_args)
    monkeypatch.setattr(remote_claude, "run_remote_control", fake_run_remote_control)

    args = SimpleNamespace(remote=True, host="10.0.0.1", port=10000, token="secret-token", name="demo")

    result = remote_claude.cmd_status(args)

    assert result == 0
    assert calls == [("10.0.0.1", 10000, "demo", "secret-token", "status")]
    out = capsys.readouterr().out
    assert "会话状态:" in out
    assert "demo" in out
    assert "active=是" in out
    assert "tmux=否" in out


def test_cmd_regenerate_token_uses_validate_remote_args_and_run_remote_control(monkeypatch):
    calls = []

    def fake_validate_remote_args(args, session_fallback=None):
        calls.append(("validate", args, session_fallback))
        return ("10.0.0.1", 10000, "demo", "secret-token")

    def fake_run_remote_control(host, port, session, token, operation):
        calls.append(("run", host, port, session, token, operation))
        return 0

    monkeypatch.setattr(remote_claude, "validate_remote_args", fake_validate_remote_args)
    monkeypatch.setattr(remote_claude, "run_remote_control", fake_run_remote_control)

    args = SimpleNamespace(remote=True, host="10.0.0.1", port=10000, token="secret-token", session="demo")

    result = remote_claude.cmd_regenerate_token(args)

    assert result == 0
    assert calls[0][0] == "validate"
    assert calls[1] == ("run", "10.0.0.1", 10000, "demo", "secret-token", "regenerate-token")
