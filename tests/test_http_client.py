# tests/test_http_client.py

import asyncio
import io
import pytest
from unittest.mock import Mock, AsyncMock, patch
from client.http_client import HTTPClient, build_ws_url


class TestBuildWsUrl:
    """WebSocket URL 构建测试"""

    def test_build_ws_url_full(self):
        """测试构建 WebSocket URL - 完整参数"""
        url = build_ws_url("192.168.1.100", 8765, "mywork", "abc123")
        assert url == "ws://192.168.1.100:8765/ws?session=mywork&token=abc123"

    def test_build_ws_url_default_port(self):
        """测试构建 WebSocket URL - 默认端口"""
        url = build_ws_url("192.168.1.100", None, "mywork", "abc123")
        assert url == "ws://192.168.1.100:8765/ws?session=mywork&token=abc123"

    def test_build_ws_url_special_chars(self):
        """测试构建 WebSocket URL - 特殊字符编码"""
        url = build_ws_url("example.com", 9000, "my session", "token/with/slashes")
        assert "session=my+session" in url or "session=my%20session" in url
        assert "token=token%2Fwith%2Fslashes" in url


class TestHTTPClient:
    """HTTP Client 测试"""

    def test_client_initialization(self):
        """测试客户端初始化"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)
        assert client.host == "192.168.1.100"
        assert client.session == "mywork"
        assert client.token == "abc123"
        assert client.port == 8765

    def test_client_initialization_default_port(self):
        """测试客户端初始化 - 默认端口"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123")
        assert client.port == 8765

    def test_client_id_generation(self):
        """测试客户端 ID 生成"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123")
        assert client.client_id is not None
        assert len(client.client_id) == 8

    def test_get_ws_url(self):
        """测试获取 WebSocket URL"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)
        url = client._get_ws_url()
        assert url == "ws://192.168.1.100:8765/ws?session=mywork&token=abc123"

    @pytest.mark.anyio
    async def test_connect_success(self):
        """测试连接成功"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)

        # websockets.connect 返回一个协程，await 后得到 WebSocket 对象
        mock_ws = AsyncMock()

        # 创建一个 async mock 函数来模拟 websockets.connect
        async def mock_connect_func(*args, **kwargs):
            return mock_ws

        with patch('websockets.connect', side_effect=mock_connect_func):
            result = await client.connect()
            assert result is True
            assert client.ws is mock_ws

    @pytest.mark.anyio
    async def test_connect_failure(self):
        """测试连接失败"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)

        with patch('websockets.connect') as mock_connect:
            mock_connect.side_effect = Exception("Connection refused")

            result = await client.connect()
            assert result is False

    @pytest.mark.anyio
    async def test_send_input(self):
        """测试发送输入"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)
        client.ws = AsyncMock()
        client.running = True

        await client._send_input(b"hello\n")

        # 验证 send 被调用
        assert client.ws.send.called
        sent_data = client.ws.send.call_args[0][0]
        assert b'"type": "input"' in sent_data

    @pytest.mark.anyio
    async def test_send_resize(self):
        """测试发送终端大小"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)
        client.ws = AsyncMock()
        client.running = True

        await client._send_resize(24, 80)

        # 验证 send 被调用
        assert client.ws.send.called
        sent_data = client.ws.send.call_args[0][0]
        assert b'"type": "resize"' in sent_data
        assert b'"rows": 24' in sent_data
        assert b'"cols": 80' in sent_data

    @pytest.mark.anyio
    async def test_send_control(self):
        """测试发送控制命令"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)

        # Mock WebSocket 连接
        with patch('websockets.connect') as mock_connect:
            mock_ws = AsyncMock()
            mock_ws.send = AsyncMock()
            mock_ws.recv = AsyncMock(return_value='{"type":"control_response","success":true,"message":"OK"}')
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_ws)

            result = await client.send_control("shutdown")
            assert result['success'] is True
            assert result['message'] == "OK"

    @pytest.mark.anyio
    async def test_handle_output_message(self):
        """测试处理输出消息"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)

        from utils.protocol import OutputMessage

        msg = OutputMessage(b"Hello, World!")

        # 捕获 stdout
        import io
        import sys
        captured = io.BytesIO()

        with patch('sys.stdout') as mock_stdout:
            mock_stdout.buffer = captured
            mock_stdout.buffer.flush = Mock()

            await client._handle_message(msg)

        # 验证输出被写入
        captured.seek(0)
        assert captured.read() == b"Hello, World!"

    @pytest.mark.anyio
    async def test_handle_error_message(self):
        """测试处理错误消息"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)

        from utils.protocol import ErrorMessage

        msg = ErrorMessage("Something went wrong", "ERR001")

        # 捕获 stderr 或 print
        with patch('builtins.print') as mock_print:
            await client._handle_message(msg)

            # 验证错误消息被打印
            mock_print.assert_called()
            args = mock_print.call_args[0]
            assert "错误" in args[0]
            assert "Something went wrong" in args[0]

    def test_setup_terminal(self):
        """测试终端设置"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)

        mock_stdin = Mock()
        mock_stdin.isatty.return_value = True
        mock_stdin.fileno.return_value = 0

        with patch('sys.stdin', mock_stdin):
            with patch('tty.setraw') as mock_setraw:
                with patch('termios.tcgetattr', return_value=Mock()) as mock_tcgetattr:
                    client._setup_terminal()

                    assert client.old_settings is not None
                    mock_setraw.assert_called_once()

    def test_restore_terminal(self):
        """测试恢复终端设置"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)

        mock_settings = Mock()
        client.old_settings = mock_settings

        with patch('termios.tcsetattr') as mock_tcsetattr:
            client._restore_terminal()

            mock_tcsetattr.assert_called_once()

    def test_cleanup(self):
        """测试清理"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)
        client.running = True
        client.old_settings = Mock()

        with patch('termios.tcsetattr'):
            client._cleanup()

            assert client.running is False
