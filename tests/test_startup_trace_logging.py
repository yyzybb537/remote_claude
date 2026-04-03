import logging
import json
from types import SimpleNamespace

import remote_claude
from utils.runtime_config import Settings, Launcher


def _build_args(**overrides):
    data = {
        "name": "demo-session",
        "cli_args": ["--token", "secret-token", "--password=abc123", "--secret", "s3"],
        "debug_screen": False,
        "debug_verbose": False,
        "cli": "claude",
        "launcher": "Claude",
        "remote": True,
        "remote_port": 9999,
        "remote_host": "0.0.0.0",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _mock_settings():
    """返回包含默认 Launcher 的 Settings"""
    return Settings(
        launchers=[Launcher(name="Claude", cli_type="claude", command="claude")]
    )


def test_cmd_start_logs_trace_fields_and_sanitized_command_on_timeout(monkeypatch, tmp_path):
    log_file = tmp_path / "startup.log"
    env_snapshot_file = tmp_path / "env.json"
    missing_socket = tmp_path / "missing.sock"

    start_logger = logging.getLogger("Start")
    original_handlers = list(start_logger.handlers)
    original_level = start_logger.level
    original_propagate = start_logger.propagate
    for handler in list(start_logger.handlers):
        start_logger.removeHandler(handler)

    class _DummyConfig:
        pass

    monkeypatch.setattr(remote_claude, "USER_DATA_DIR", tmp_path)
    monkeypatch.setattr(remote_claude, "is_session_active", lambda _s: False)
    def _tmux_session_exists(_s):
        _tmux_session_exists.calls += 1
        # 第一次调用用于“启动前是否已存在 tmux 会话”检查，必须 False
        # 之后调用用于“server 是否仍在运行”检查，返回 True 以走 timeout 分支
        return _tmux_session_exists.calls > 1

    _tmux_session_exists.calls = 0

    monkeypatch.setattr(remote_claude, "tmux_session_exists", _tmux_session_exists)
    monkeypatch.setattr(remote_claude, "ensure_socket_dir", lambda: None)
    monkeypatch.setattr(remote_claude, "get_env_snapshot_path", lambda _s: env_snapshot_file)
    monkeypatch.setattr(remote_claude, "tmux_create_session", lambda *_a, **_kw: True)
    monkeypatch.setattr(remote_claude, "get_socket_path", lambda _s: missing_socket)
    monkeypatch.setattr(remote_claude, "tmux_kill_session", lambda _s: None)
    monkeypatch.setattr(remote_claude, "time", type("T", (), {"sleep": staticmethod(lambda _x: None)})())

    monkeypatch.setenv("STARTUP_TIMEOUT", "1")

    import utils.runtime_config as runtime_config_module
    import utils.session as session_module

    monkeypatch.setattr(runtime_config_module, "load_state", lambda: _DummyConfig())
    monkeypatch.setattr(runtime_config_module, "load_settings", _mock_settings)
    monkeypatch.setattr(session_module, "resolve_session_name", lambda original, _cfg: original)

    try:
        rc = remote_claude.cmd_start(_build_args())

        assert rc == 1
        assert log_file.exists()

        text = log_file.read_text(encoding="utf-8")
        assert "stage=server_spawn" in text
        assert "remote_host=0.0.0.0" in text
        assert "remote_port=9999" in text
        assert "cli_args_count=5" in text
        assert "server_cmd_sanitized=" in text
        assert "stage=server_start_failed" in text
        assert "reason=startup_timeout" in text

        assert "secret-token" not in text
        assert "abc123" not in text
        assert "--token ***" in text
        assert "--password=***" in text
        assert "--secret ***" in text
    finally:
        for handler in list(start_logger.handlers):
            start_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        for handler in original_handlers:
            start_logger.addHandler(handler)
        start_logger.setLevel(original_level)
        start_logger.propagate = original_propagate


def test_cmd_start_kills_session_when_socket_missing_after_spawn(monkeypatch, tmp_path):
    env_snapshot_file = tmp_path / "env.json"
    env_snapshot_file.write_text(json.dumps({}), encoding="utf-8")
    missing_socket = tmp_path / "missing.sock"

    killed = []

    class _DummyConfig:
        pass

    monkeypatch.setattr(remote_claude, "USER_DATA_DIR", tmp_path)
    monkeypatch.setattr(remote_claude, "is_session_active", lambda _s: False)

    def _tmux_session_exists(_s):
        _tmux_session_exists.calls += 1
        return _tmux_session_exists.calls > 1

    _tmux_session_exists.calls = 0

    monkeypatch.setattr(remote_claude, "tmux_session_exists", _tmux_session_exists)
    monkeypatch.setattr(remote_claude, "ensure_socket_dir", lambda: None)
    monkeypatch.setattr(remote_claude, "get_env_snapshot_path", lambda _s: env_snapshot_file)
    monkeypatch.setattr(remote_claude, "tmux_create_session", lambda *_a, **_kw: True)
    monkeypatch.setattr(remote_claude, "get_socket_path", lambda _s: missing_socket)
    monkeypatch.setattr(remote_claude, "tmux_kill_session", lambda s: killed.append(s))

    import utils.runtime_config as runtime_config_module
    import utils.session as session_module
    import client as client_module

    monkeypatch.setattr(runtime_config_module, "load_state", lambda: _DummyConfig())
    monkeypatch.setattr(runtime_config_module, "load_settings", _mock_settings)
    monkeypatch.setattr(session_module, "resolve_session_name", lambda original, _cfg: original)
    monkeypatch.setattr(client_module, "run_client", lambda _s: 99)

    rc = remote_claude.cmd_start(_build_args(name="socket-missing-session", remote=False, remote_host="127.0.0.1", remote_port=8765, cli_args=[]))

    assert rc == 1
    assert killed == ["socket-missing-session"]


def test_cmd_start_rejects_help_like_cli_args_before_spawning_session(monkeypatch, tmp_path, capsys):
    class _DummyConfig:
        pass

    spawned = []

    monkeypatch.setattr(remote_claude, "USER_DATA_DIR", tmp_path)
    monkeypatch.setattr(remote_claude, "is_session_active", lambda _s: False)
    monkeypatch.setattr(remote_claude, "tmux_session_exists", lambda _s: False)
    monkeypatch.setattr(remote_claude, "ensure_socket_dir", lambda: None)
    monkeypatch.setattr(remote_claude, "tmux_create_session", lambda *_a, **_kw: spawned.append(True) or True)

    import utils.runtime_config as runtime_config_module
    import utils.session as session_module

    monkeypatch.setattr(runtime_config_module, "load_state", lambda: _DummyConfig())
    monkeypatch.setattr(runtime_config_module, "load_settings", _mock_settings)
    monkeypatch.setattr(session_module, "resolve_session_name", lambda original, _cfg: original)

    rc = remote_claude.cmd_start(_build_args(name="help-session", remote=False, remote_host="127.0.0.1", remote_port=8765, cli_args=["--help"]))

    captured = capsys.readouterr()
    assert rc == 1
    assert spawned == []
    assert "start 子命令不支持透传帮助参数" in captured.out




def test_detect_hard_startup_failure_matches_shell_exec_error_line():
    line = "2099-04-01 12:00:00.000 [Start] ERROR launcher failed: exited with status 127"

    assert remote_claude._detect_hard_startup_failure([line]) == line



def test_cmd_start_accepts_monkeypatched_user_data_dir_path(monkeypatch, tmp_path):
    monkeypatch.setattr(remote_claude, "USER_DATA_DIR", tmp_path)
    assert remote_claude._get_user_data_dir() == tmp_path


def test_cmd_start_fails_fast_on_hard_startup_error_log(monkeypatch, tmp_path, capsys):
    env_snapshot_file = tmp_path / "env.json"
    startup_log = tmp_path / "startup.log"
    startup_log.write_text(
        "2099-04-01 12:00:00.000 [Start] INFO launcher failed: command not found\n",
        encoding="utf-8",
    )

    class _DummyConfig:
        pass

    monkeypatch.setattr(remote_claude, "USER_DATA_DIR", tmp_path)
    monkeypatch.setattr(remote_claude, "is_session_active", lambda _s: False)

    def _tmux_session_exists(_s):
        _tmux_session_exists.calls += 1
        return _tmux_session_exists.calls > 1

    _tmux_session_exists.calls = 0

    monkeypatch.setattr(remote_claude, "tmux_session_exists", _tmux_session_exists)
    monkeypatch.setattr(remote_claude, "ensure_socket_dir", lambda: None)
    monkeypatch.setattr(remote_claude, "ensure_user_data_dir", lambda: None)
    monkeypatch.setattr(remote_claude, "get_env_snapshot_path", lambda _s: env_snapshot_file)
    monkeypatch.setattr(remote_claude, "tmux_create_session", lambda *_a, **_kw: True)
    monkeypatch.setattr(remote_claude, "get_socket_path", lambda _s: tmp_path / "missing.sock")
    monkeypatch.setattr(remote_claude, "tmux_kill_session", lambda _s: None)
    monkeypatch.setattr(remote_claude, "time", type("T", (), {"sleep": staticmethod(lambda _x: None)})())

    import utils.runtime_config as runtime_config_module
    import utils.session as session_module

    monkeypatch.setattr(runtime_config_module, "load_state", lambda: _DummyConfig())
    monkeypatch.setattr(runtime_config_module, "load_settings", _mock_settings)
    monkeypatch.setattr(session_module, "resolve_session_name", lambda original, _cfg: original)

    rc = remote_claude.cmd_start(_build_args(name="hard-fail-session", remote=False, remote_host="127.0.0.1", remote_port=8765, cli_args=[]))

    captured = capsys.readouterr()
    assert rc == 1
    assert "错误: Server 启动失败" in captured.out
    assert "command not found" in captured.out
