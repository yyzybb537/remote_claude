# tests/test_server_ws.py

import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path


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
