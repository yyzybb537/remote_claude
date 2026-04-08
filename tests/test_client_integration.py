"""
客户端集成测试

测试本地和远程客户端的端到端流程
"""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from websockets import exceptions as ws_exceptions

# 添加项目根目录到 sys.path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from client.local_client import LocalClient
from client.remote_client import RemoteClient


class TestLocalClientIntegration:
    """本地客户端集成测试"""

    @pytest.mark.asyncio
    async def test_local_client_init(self):
        """测试本地客户端初始化"""
        client = LocalClient("test-session")
        assert client.session_name == "test-session"
        assert client._connected == False

    @pytest.mark.asyncio
    async def test_local_client_url_generation(self):
        """测试本地客户端 URL 生成"""
        client = LocalClient("my-session")
        # 验证 socket_path 属性
        assert hasattr(client, 'socket_path')

    @pytest.mark.asyncio
    async def test_local_client_connect_failure(self):
        """测试本地客户端连接失败"""
        client = LocalClient("nonexistent-session")
        # 连接不存在的 socket 应该失败
        result = await client.connect()
        assert result == False
        assert client._connected == False


class TestRemoteClientIntegration:
    """远程客户端集成测试"""

    @pytest.mark.asyncio
    async def test_remote_client_init(self):
        """测试远程客户端初始化"""
        client = RemoteClient("192.168.1.100", "test-session", "token123", 8765)
        assert client.host == "192.168.1.100"
        assert client.session_name == "test-session"
        assert client.token == "token123"
        assert client.port == 8765
        assert client._connected == False

    @pytest.mark.asyncio
    async def test_remote_client_ws_url(self):
        """测试远程客户端 WebSocket URL 构建"""
        client = RemoteClient("192.168.1.100", "test-session", "token123", 8765)
        url = client._get_ws_url()
        assert "ws://192.168.1.100:8765/ws" in url
        assert "session=test-session" in url
        assert "token=token123" in url

    @pytest.mark.asyncio
    async def test_remote_client_ws_url_with_custom_port(self):
        """测试自定义端口的 WebSocket URL"""
        client = RemoteClient("example.com", "my-session", "mytoken", 9000)
        url = client._get_ws_url()
        assert "ws://example.com:9000/ws" in url
        assert "session=my-session" in url
        assert "token=mytoken" in url

    @pytest.mark.asyncio
    async def test_remote_client_connect_mocked(self):
        """测试远程客户端连接（模拟）"""
        client = RemoteClient("192.168.1.100", "test-session", "token123", 8765)

        # 模拟 WebSocket 连接
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value='{"type":"output","data":"dGVzdA=="}')
        mock_ws.close = AsyncMock()

        # 创建一个可 await 的 mock
        async def mock_websockets_connect(*args, **kwargs):
            return mock_ws

        # patch 模块中导入的 connect 函数
        with patch('client.remote_client.connect', side_effect=mock_websockets_connect):
            result = await client.connect()
            assert result == True
            assert client._connected == True

    @pytest.mark.asyncio
    async def test_remote_client_send_message_mocked(self):
        """测试远程客户端发送消息（模拟）"""
        client = RemoteClient("192.168.1.100", "test-session", "token123", 8765)

        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value='{"type":"output","data":"dGVzdA=="}')
        mock_ws.close = AsyncMock()

        async def mock_websockets_connect(*args, **kwargs):
            return mock_ws

        with patch('client.remote_client.connect', side_effect=mock_websockets_connect):
            await client.connect()

            # 发送消息
            from utils.protocol import InputMessage
            msg = InputMessage(b"test input", "test-client")
            await client.send_message(msg)

            # 验证 send 被调用
            mock_ws.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_remote_client_read_message_mocked(self):
        """测试远程客户端读取消息（模拟）"""
        client = RemoteClient("192.168.1.100", "test-session", "token123", 8765)

        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        # 返回有效的 JSON 消息
        mock_ws.recv = AsyncMock(return_value='{"type":"output","data":"dGVzdA=="}')
        mock_ws.close = AsyncMock()

        async def mock_websockets_connect(*args, **kwargs):
            return mock_ws

        with patch('client.remote_client.connect', side_effect=mock_websockets_connect):
            await client.connect()

            # 读取消息
            msg = await client.read_message()
            assert msg is not None

    @pytest.mark.asyncio
    async def test_remote_client_read_message_closed_sets_disconnect_reason(self):
        """测试远程客户端关闭时记录断开原因"""
        client = RemoteClient("192.168.1.100", "test-session", "token123", 8765)

        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=ws_exceptions.ConnectionClosedOK(None, None))
        mock_ws.close = AsyncMock()

        async def mock_websockets_connect(*args, **kwargs):
            return mock_ws

        with patch('client.remote_client.connect', side_effect=mock_websockets_connect):
            await client.connect()
            msg = await client.read_message()

            assert msg is None
            reason = client._consume_disconnect_reason()
            assert reason is not None
            assert "连接关闭:" in reason

    @pytest.mark.asyncio
    async def test_remote_client_send_message_failure_sets_disconnect_reason(self):
        """测试发送失败时记录断开原因"""
        client = RemoteClient("192.168.1.100", "test-session", "token123", 8765)

        mock_ws = MagicMock()
        mock_ws.send = AsyncMock(side_effect=RuntimeError("network down"))
        mock_ws.recv = AsyncMock(return_value='{"type":"output","data":"dGVzdA=="}')
        mock_ws.close = AsyncMock()

        async def mock_websockets_connect(*args, **kwargs):
            return mock_ws

        with patch('client.remote_client.connect', side_effect=mock_websockets_connect):
            await client.connect()

            from utils.protocol import InputMessage
            msg = InputMessage(b"test input", "test-client")
            with pytest.raises(ConnectionError) as exc_info:
                await client.send_message(msg)

            assert "发送失败:" in str(exc_info.value)
            reason = client._consume_disconnect_reason()
            assert reason is not None
            assert "发送失败:" in reason

    @pytest.mark.asyncio
    async def test_remote_client_send_control_uses_module_connect(self):
        """测试控制命令链路复用 remote_client 的 connect 实现"""
        client = RemoteClient("192.168.1.100", "test-session", "token123", 8765)

        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value='{"type":"control_response","success":true,"message":"ok"}')
        mock_ws.close = AsyncMock()

        class _AsyncContextManager:
            async def __aenter__(self):
                return mock_ws

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch('client.remote_client.connect', return_value=_AsyncContextManager()):
            result = await client.send_control("status")

        assert result == {"success": True, "message": "ok"}
        mock_ws.send.assert_awaited_once()
        mock_ws.recv.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remote_client_close_mocked(self):
        """测试远程客户端关闭连接（模拟）"""
        client = RemoteClient("192.168.1.100", "test-session", "token123", 8765)

        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value='{"type":"output","data":"dGVzdA=="}')
        mock_ws.close = AsyncMock()

        async def mock_websockets_connect(*args, **kwargs):
            return mock_ws

        with patch('client.remote_client.connect', side_effect=mock_websockets_connect):
            await client.connect()
            assert client._connected == True

            await client.close_connection()
            assert client._connected == False


class TestClientProtocol:
    """客户端协议测试"""

    def test_input_message_creation(self):
        """测试输入消息创建"""
        from utils.protocol import InputMessage
        msg = InputMessage(b"test input", "test-client")
        # data 存储的是 base64 编码后的值
        assert msg.get_data() == b"test input"
        assert msg.client_id == "test-client"

    def test_output_message_creation(self):
        """测试输出消息创建"""
        from utils.protocol import OutputMessage
        msg = OutputMessage(b"test output")
        assert msg.get_data() == b"test output"

    def test_control_message_creation(self):
        """测试控制消息创建"""
        from utils.protocol import ControlMessage
        msg = ControlMessage("shutdown", "test-client")
        assert msg.action == "shutdown"
        assert msg.client_id == "test-client"

    def test_message_encoding(self):
        """测试消息编码"""
        from utils.protocol import OutputMessage, encode_message
        msg = OutputMessage(b"hello")
        encoded = encode_message(msg)
        assert isinstance(encoded, bytes)
        assert b'\n' in encoded  # 消息以换行符结束

    def test_message_decoding(self):
        """测试消息解码"""
        from utils.protocol import OutputMessage, encode_message, decode_message
        original = OutputMessage(b"hello world")
        encoded = encode_message(original)
        decoded = decode_message(encoded)
        assert decoded is not None
        # 使用 get_data() 获取原始数据
        assert decoded.get_data() == b"hello world"
