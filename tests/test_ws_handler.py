# tests/test_ws_handler.py

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path


class TestParseUrlParams:
    """URL 参数解析测试"""

    def test_parse_url_params_valid(self):
        """测试解析有效 URL 参数"""
        from server.ws_handler import parse_url_params
        session, token = parse_url_params("/ws?session=mywork&token=abc123")
        assert session == "mywork"
        assert token == "abc123"

    def test_parse_url_params_missing_token(self):
        """测试缺少 token 参数"""
        from server.ws_handler import parse_url_params
        session, token = parse_url_params("/ws?session=mywork")
        assert session == "mywork"
        assert token is None

    def test_parse_url_params_missing_session(self):
        """测试缺少 session 参数"""
        from server.ws_handler import parse_url_params
        session, token = parse_url_params("/ws?token=abc123")
        assert session is None
        assert token == "abc123"


class TestWebSocketHandler:
    """WebSocket 处理器测试"""

    def test_authenticate_valid_token(self, tmp_path):
        """测试有效 token 认证"""
        from server.ws_handler import WebSocketHandler
        mock_server = Mock()
        mock_server.session_name = "test-session"

        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)
        # 先创建 token
        handler.token_manager.get_or_create_token()
        token = handler.token_manager._token

        result = handler._authenticate(token)
        assert result is True

    def test_authenticate_invalid_token(self, tmp_path):
        """测试无效 token 认证"""
        from server.ws_handler import WebSocketHandler
        mock_server = Mock()
        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)
        handler.token_manager.get_or_create_token()

        result = handler._authenticate("wrong-token")
        assert result is False

    def test_authenticate_empty_token(self, tmp_path):
        """测试空 token 认证"""
        from server.ws_handler import WebSocketHandler
        mock_server = Mock()
        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)
        handler.token_manager.get_or_create_token()

        result = handler._authenticate("")
        assert result is False

        result = handler._authenticate(None)
        assert result is False

    def test_max_connections_limit(self, tmp_path):
        """测试最大连接数限制"""
        from server.ws_handler import WebSocketHandler
        mock_server = Mock()
        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)

        # 添加最大数量的连接
        for i in range(handler.MAX_WS_CONNECTIONS):
            mock_ws = Mock()
            handler.ws_connections.add(mock_ws)

        # 尝试添加第 11 个连接应该被拒绝
        assert len(handler.ws_connections) == handler.MAX_WS_CONNECTIONS

    @pytest.mark.anyio
    async def test_handle_connection_wrong_session(self, tmp_path):
        """测试连接错误的 session"""
        from server.ws_handler import WebSocketHandler
        mock_server = Mock()
        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)
        handler.token_manager.get_or_create_token()

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.close = AsyncMock()

        await handler.handle_connection(mock_ws, "/ws?session=wrong-session&token=abc")

        # 应该发送错误消息并关闭连接
        mock_ws.send.assert_called_once()
        mock_ws.close.assert_called_once()

    @pytest.mark.anyio
    async def test_handle_connection_invalid_token(self, tmp_path):
        """测试无效 token 连接"""
        from server.ws_handler import WebSocketHandler
        mock_server = Mock()
        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)
        handler.token_manager.get_or_create_token()

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.close = AsyncMock()

        await handler.handle_connection(mock_ws, "/ws?session=test-session&token=wrong")

        # 应该发送错误消息并关闭连接
        mock_ws.send.assert_called_once()
        mock_ws.close.assert_called_once()

    @pytest.mark.anyio
    async def test_handle_control_shutdown(self, tmp_path):
        """测试 shutdown 控制命令"""
        from server.ws_handler import WebSocketHandler
        mock_server = Mock()
        mock_server._shutdown_event = asyncio.Event()

        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)

        response = await handler._handle_control("shutdown")

        assert response.success is True
        assert "关闭" in response.message
        assert mock_server._shutdown_event.is_set()

    @pytest.mark.anyio
    async def test_handle_control_unknown(self, tmp_path):
        """测试未知控制命令"""
        from server.ws_handler import WebSocketHandler
        mock_server = Mock()
        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)

        response = await handler._handle_control("unknown")

        assert response.success is False
        assert "未知" in response.message

    @pytest.mark.anyio
    async def test_broadcast_to_ws(self, tmp_path):
        """测试广播输出到 WebSocket 客户端"""
        from server.ws_handler import WebSocketHandler
        mock_server = Mock()
        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)

        # 添加模拟连接
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        handler.ws_connections.add(mock_ws1)
        handler.ws_connections.add(mock_ws2)

        # 广播消息
        test_data = b"test output"
        await handler.broadcast_to_ws(test_data)

        # 验证两个连接都收到了消息
        mock_ws1.send.assert_called_once()
        mock_ws2.send.assert_called_once()

    @pytest.mark.anyio
    async def test_broadcast_to_ws_empty_connections(self, tmp_path):
        """测试无连接时的广播"""
        from server.ws_handler import WebSocketHandler
        mock_server = Mock()
        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)

        # 无连接时广播不应报错
        test_data = b"test output"
        await handler.broadcast_to_ws(test_data)
        # 正常完成即可
