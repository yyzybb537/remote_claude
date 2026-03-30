import logging
from types import SimpleNamespace

import remote_claude


def _build_args(**overrides):
    data = {
        "name": "demo-session",
        "cli_args": ["--token", "secret-token", "--password=abc123", "--secret", "s3"],
        "debug_screen": False,
        "debug_verbose": False,
        "cli": "claude",
        "remote": True,
        "remote_port": 9999,
        "remote_host": "0.0.0.0",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


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

    monkeypatch.setattr(runtime_config_module, "load_runtime_config", lambda: _DummyConfig())
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
