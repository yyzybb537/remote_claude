# tests/test_server_ws.py

import asyncio
import logging
import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_server_main_parse_remote_args_and_forward(monkeypatch, tmp_path):
    """测试 __main__ 参数解析并透传 remote 参数到 run_server"""
    from server import server as server_module

    captured = {}

    class _DummyFileHandler:
        def __init__(self, *args, **kwargs):
            self._startup_handler = True

        def setFormatter(self, *args, **kwargs):
            return None

    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)

    info_mock = Mock()

    def fake_run_server(session_name, cli_args, **kwargs):
        captured["session_name"] = session_name
        captured["cli_args"] = cli_args
        captured.update(kwargs)

    monkeypatch.setattr(server_module, "run_server", fake_run_server)
    monkeypatch.setattr(server_module.logger, "info", info_mock)
    monkeypatch.setattr(server_module.logging, "basicConfig", lambda *args, **kwargs: None)
    monkeypatch.setattr(server_module.logging, "FileHandler", _DummyFileHandler)
    monkeypatch.setattr("utils.session.USER_DATA_DIR", tmp_path)

    try:
        server_module.main([
            "demo-session",
            "foo",
            "bar",
            "--cli-type", "codex",
            "--remote",
            "--remote-host", "127.0.0.1",
            "--remote-port", "9001",
        ])
    finally:
        root_logger.handlers[:] = original_handlers

    assert captured["session_name"] == "demo-session"
    assert captured["cli_args"] == ["foo", "bar"]
    assert captured["cli_type"] == "codex"
    assert captured["enable_remote"] is True
    assert captured["remote_host"] == "127.0.0.1"
    assert captured["remote_port"] == 9001
    info_mock.assert_any_call(
        "stage=server_bootstrap session=%s cli_type=%s enable_remote=%s remote_host=%s remote_port=%s cli_args_count=%s",
        "demo-session", "codex", True, "127.0.0.1", 9001, 2,
    )


def test_run_server_logs_entry_trace(monkeypatch):
    """测试 run_server 入口会输出启动参数追溯日志"""
    from server import server as server_module

    mock_server = Mock()
    mock_server.start = AsyncMock()

    def fake_asyncio_run(coro):
        coro.close()
        return None

    info_mock = Mock()

    monkeypatch.setattr(server_module, "ProxyServer", Mock(return_value=mock_server))
    monkeypatch.setattr(server_module.asyncio, "run", fake_asyncio_run)
    monkeypatch.setattr(server_module.signal, "signal", lambda *args, **kwargs: None)
    monkeypatch.setattr(server_module.logger, "info", info_mock)

    server_module.run_server(
        session_name="trace-session",
        cli_args=["--model", "sonnet"],
        cli_type=server_module.CliType.CODEX,
        enable_remote=True,
        remote_host="127.0.0.1",
        remote_port=9001,
    )

    info_mock.assert_any_call(
        "stage=run_server_enter session=%s cli_type=%s enable_remote=%s remote_host=%s remote_port=%s cli_args_count=%s",
        "trace-session", "codex", True, "127.0.0.1", 9001, 2,
    )


def test_start_pty_log_command_is_sanitized(monkeypatch):
    """测试 _start_pty 记录的启动命令会脱敏敏感参数"""
    from server import server as server_module

    fake_server = object.__new__(server_module.ProxyServer)
    fake_server.session_name = "s1"
    fake_server.cli_type = server_module.CliType.CLAUDE
    fake_server.cli_args = ["--token", "plain-token", "--password=abc123", "--secret", "s3"]
    fake_server.PTY_ROWS = 10
    fake_server.PTY_COLS = 20
    fake_server._get_effective_cmd = lambda: "claude"

    import utils.session as session_module
    monkeypatch.setattr(session_module, "get_env_snapshot_path", lambda _s: Path("/tmp/missing_env.json"))
    monkeypatch.setattr(server_module.pty, "fork", lambda: (1234, 99))
    monkeypatch.setattr(server_module.fcntl, "ioctl", lambda *args, **kwargs: None)
    monkeypatch.setattr(server_module.fcntl, "fcntl", lambda *args, **kwargs: 0)
    info_mock = Mock()
    monkeypatch.setattr(server_module.logger, "info", info_mock)

    fake_server._start_pty()

    startup_logs = [
        call.args[0]
        for call in info_mock.call_args_list
        if call.args and isinstance(call.args[0], str) and call.args[0].startswith("启动命令:")
    ]
    assert startup_logs, "未记录启动命令日志"
    startup_cmd = startup_logs[0]
    assert "plain-token" not in startup_cmd
    assert "abc123" not in startup_cmd
    assert "--token ***" in startup_cmd
    assert "--password=***" in startup_cmd
    assert "--secret ***" in startup_cmd


class TestServerWebSocketIntegration:
    """Server WebSocket 集成测试"""

    @pytest.mark.anyio
    async def test_server_enable_remote_flag(self):
        """测试 enable_remote 标志"""
        # 这个测试验证 server 能正确初始化 WebSocket 相关参数
        from server.server import ProxyServer

        # Mock 必要的依赖
        with patch('server.server.ensure_socket_dir'), \
             patch('server.server.get_socket_path') as mock_socket_path, \
             patch('server.server.get_pid_file') as mock_pid_file, \
             patch('shared_state.SharedStateWriter'), \
             patch('server.server.OutputWatcher') as mock_watcher, \
             patch('utils.session._safe_filename', return_value='test-session'):

            mock_socket_path.return_value = Path('/tmp/test.sock')
            mock_pid_file.return_value = Path('/tmp/test.pid')

            server = ProxyServer(
                session_name="test-session",
                enable_remote=True,
                remote_host="0.0.0.0",
                remote_port=8765
            )

            assert server.enable_remote is True
            assert server.remote_host == "0.0.0.0"
            assert server.remote_port == 8765

    @pytest.mark.anyio
    async def test_server_ws_handler_lazy_init(self):
        """测试 ws_handler 延迟初始化"""
        from server.server import ProxyServer

        with patch('server.server.ensure_socket_dir'), \
             patch('server.server.get_socket_path') as mock_socket_path, \
             patch('server.server.get_pid_file') as mock_pid_file, \
             patch('shared_state.SharedStateWriter'), \
             patch('server.server.OutputWatcher'), \
             patch('utils.session._safe_filename', return_value='test-session'):
            mock_socket_path.return_value = Path('/tmp/test.sock')
            mock_pid_file.return_value = Path('/tmp/test.pid')

            server = ProxyServer(
                session_name="test-session",
                enable_remote=False  # 不启用远程
            )

            assert server.ws_handler is None

    @pytest.mark.anyio
    async def test_server_default_remote_params(self):
        """测试 WebSocket 默认参数"""
        from server.server import ProxyServer

        with patch('server.server.ensure_socket_dir'), \
             patch('server.server.get_socket_path') as mock_socket_path, \
             patch('server.server.get_pid_file') as mock_pid_file, \
             patch('shared_state.SharedStateWriter'), \
             patch('server.server.OutputWatcher'), \
             patch('utils.session._safe_filename', return_value='test-session'):
            mock_socket_path.return_value = Path('/tmp/test.sock')
            mock_pid_file.return_value = Path('/tmp/test.pid')

            server = ProxyServer(
                session_name="test-session"
            )

            # 默认值
            assert server.enable_remote is False
            assert server.remote_host == "0.0.0.0"
            assert server.remote_port == 8765
            assert server.ws_handler is None

    @pytest.mark.anyio
    async def test_server_shutdown_event_for_ws(self):
        """测试 shutdown_event 用于 WebSocket 服务器关闭"""
        from server.server import ProxyServer

        with patch('server.server.ensure_socket_dir'), \
             patch('server.server.get_socket_path') as mock_socket_path, \
             patch('server.server.get_pid_file') as mock_pid_file, \
             patch('shared_state.SharedStateWriter'), \
             patch('server.server.OutputWatcher'), \
             patch('utils.session._safe_filename', return_value='test-session'):
            mock_socket_path.return_value = Path('/tmp/test.sock')
            mock_pid_file.return_value = Path('/tmp/test.pid')

            server = ProxyServer(
                session_name="test-session",
                enable_remote=True
            )

            # 应该有 shutdown_event
            assert hasattr(server, '_shutdown_event')
            assert isinstance(server._shutdown_event, asyncio.Event)

    @pytest.mark.anyio
    async def test_broadcast_output_to_ws(self):
        """测试广播输出同时发送到 WebSocket"""
        from server.server import ProxyServer

        with patch('server.server.ensure_socket_dir'), \
             patch('server.server.get_socket_path') as mock_socket_path, \
             patch('server.server.get_pid_file') as mock_pid_file, \
             patch('shared_state.SharedStateWriter'), \
             patch('server.server.OutputWatcher'), \
             patch('utils.session._safe_filename', return_value='test-session'):
            mock_socket_path.return_value = Path('/tmp/test.sock')
            mock_pid_file.return_value = Path('/tmp/test.pid')

            server = ProxyServer(
                session_name="test-session",
                enable_remote=True
            )

            # Mock ws_handler
            mock_ws_handler = AsyncMock()
            server.ws_handler = mock_ws_handler

            # Mock output_watcher
            server.output_watcher = Mock()
            server.output_watcher.feed = Mock()

            # 调用广播方法
            test_data = b"test output data"
            await server._broadcast_output(test_data)

            # 验证 ws_handler.broadcast_to_ws 被调用
            mock_ws_handler.broadcast_to_ws.assert_called_once_with(test_data)

    @pytest.mark.anyio
    async def test_broadcast_output_no_ws_handler(self):
        """测试没有 ws_handler 时的广播（不应报错）"""
        from server.server import ProxyServer

        with patch('server.server.ensure_socket_dir'), \
             patch('server.server.get_socket_path') as mock_socket_path, \
             patch('server.server.get_pid_file') as mock_pid_file, \
             patch('shared_state.SharedStateWriter'), \
             patch('server.server.OutputWatcher'), \
             patch('utils.session._safe_filename', return_value='test-session'):
            mock_socket_path.return_value = Path('/tmp/test.sock')
            mock_pid_file.return_value = Path('/tmp/test.pid')

            server = ProxyServer(
                session_name="test-session",
                enable_remote=False
            )

            # 确认 ws_handler 为 None
            assert server.ws_handler is None

            # Mock output_watcher
            server.output_watcher = Mock()
            server.output_watcher.feed = Mock()

            # 调用广播方法不应报错
            test_data = b"test output data"
            await server._broadcast_output(test_data)  # 不应抛出异常
