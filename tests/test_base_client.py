"""
BaseClient 抽象基类测试
"""

import sys
import os
import asyncio
from typing import Optional

# 添加项目根目录到 sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pytest

from client.base_client import BaseClient
from utils.protocol import Message, MessageType, InputMessage, ResizeMessage


class MockClient(BaseClient):
    """测试用的 Mock 客户端"""

    def __init__(self, session_name: str = "test_session"):
        super().__init__(session_name)
        self._connect_result = True
        self._sent_messages: list = []
        self._read_queue: list = []
        self._closed = False

    async def connect(self) -> bool:
        """模拟连接"""
        self._connected = True
        return self._connect_result

    async def send_message(self, msg: Message) -> None:
        """模拟发送消息"""
        self._sent_messages.append(msg)

    async def read_message(self) -> Optional[Message]:
        """模拟读取消息"""
        if self._read_queue:
            return self._read_queue.pop(0)
        return None

    async def close_connection(self) -> None:
        """模拟关闭连接"""
        self._closed = True
        self._connected = False


class TestBaseClientInit:
    """测试 BaseClient 初始化"""

    def test_init(self):
        """测试初始化"""
        client = MockClient("my_session")
        assert client.session_name == "my_session"
        assert client.client_id is not None
        assert len(client.client_id) == 8  # uuid[:8]
        assert client.running is False
        assert client._connected is False
        assert client.old_settings is None
        assert client.buffer == b""

    def test_client_id_uniqueness(self):
        """测试 client_id 唯一性"""
        client1 = MockClient()
        client2 = MockClient()
        assert client1.client_id != client2.client_id


class TestBaseClientTerminalSize:
    """测试终端大小相关方法"""

    def test_get_terminal_size(self):
        """测试获取终端大小"""
        client = MockClient()
        rows, cols = client._get_terminal_size()
        # 默认回退值为 (24, 80)，真实终端会有其他值
        assert isinstance(rows, int)
        assert isinstance(cols, int)
        assert rows > 0
        assert cols > 0

    def test_get_terminal_size_fallback(self, monkeypatch):
        """测试终端大小获取失败的回退值"""
        client = MockClient()

        # 模拟 os.get_terminal_size 抛出异常
        def mock_get_terminal_size(fd=None):
            raise OSError("Not a terminal")

        monkeypatch.setattr(os, "get_terminal_size", mock_get_terminal_size)

        rows, cols = client._get_terminal_size()
        assert rows == 24
        assert cols == 80


class TestBaseClientSendResize:
    """测试发送终端大小"""

    @pytest.mark.anyio
    async def test_send_resize(self):
        """测试发送终端大小消息"""
        client = MockClient()
        await client._send_resize(30, 120)

        assert len(client._sent_messages) == 1
        msg = client._sent_messages[0]
        assert isinstance(msg, ResizeMessage)
        assert msg.rows == 30
        assert msg.cols == 120
        assert msg.client_id == client.client_id


class TestBaseClientHandleInput:
    """测试处理用户输入"""

    @pytest.mark.anyio
    async def test_handle_normal_input(self):
        """测试处理普通输入"""
        client = MockClient()
        client.running = True

        await client._handle_input(b"hello")

        assert len(client._sent_messages) == 1
        msg = client._sent_messages[0]
        assert isinstance(msg, InputMessage)
        assert msg.get_data() == b"hello"

    @pytest.mark.anyio
    async def test_handle_ctrl_d_exits(self):
        """测试 Ctrl+D 退出"""
        client = MockClient()
        client.running = True

        await client._handle_input(b'\x04')  # Ctrl+D

        assert client.running is False
        assert len(client._sent_messages) == 0  # 不发送消息


class TestBaseClientHandleMessage:
    """测试处理服务器消息"""

    @pytest.mark.anyio
    async def test_handle_output_message(self, capsys):
        """测试处理 OUTPUT 消息"""
        client = MockClient()

        from utils.protocol import OutputMessage
        msg = OutputMessage(b"test output")

        await client._handle_message(msg)

        captured = capsys.readouterr()
        assert "test output" in captured.out

    @pytest.mark.anyio
    async def test_handle_history_message(self, capsys):
        """测试处理 HISTORY 消息"""
        client = MockClient()

        from utils.protocol import HistoryMessage
        msg = HistoryMessage(b"test history")

        await client._handle_message(msg)

        captured = capsys.readouterr()
        assert "test history" in captured.out


class TestBaseClientCleanup:
    """测试清理方法"""

    @pytest.mark.anyio
    async def test_cleanup(self):
        """测试清理"""
        client = MockClient()
        client.running = True
        client._connected = True

        await client._cleanup()

        assert client.running is False
        assert client._closed is True
        assert client._connected is False


class TestBaseClientOnDisconnect:
    """测试断线回调"""

    @pytest.mark.anyio
    async def test_on_disconnect(self, capsys):
        """测试断线回调"""
        client = MockClient()

        await client._on_disconnect("test reason")

        captured = capsys.readouterr()
        assert "已断开连接" in captured.out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
