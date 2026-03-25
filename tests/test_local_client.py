"""
LocalClient 本地客户端测试

测试 Unix Socket 连接的本地客户端实现
"""

import sys
import os
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# 添加项目根目录到 sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pytest

from client.local_client import LocalClient
from utils.protocol import Message, MessageType, InputMessage, ResizeMessage, encode_message


class TestLocalClientInit:
    """测试 LocalClient 初始化"""

    def test_init(self):
        """测试基本初始化"""
        client = LocalClient("my_session")
        assert client.session_name == "my_session"
        assert client.socket_path is not None
        assert client.client_id is not None
        assert len(client.client_id) == 8  # uuid[:8]
        assert client.running is False
        assert client._connected is False
        assert client.reader is None
        assert client.writer is None
        assert client.buffer == b""

    def test_socket_path_generation(self):
        """测试 socket 路径生成"""
        client = LocalClient("test_session")
        # socket_path 应该是 Path 对象
        assert isinstance(client.socket_path, Path)
        # 路径应该包含会话名
        assert "test_session" in str(client.socket_path)
        # 应该在 /tmp/remote-claude/ 目录下
        assert "/tmp/remote-claude/" in str(client.socket_path)


class TestLocalClientConnect:
    """测试 LocalClient 连接"""

    @pytest.mark.anyio
    async def test_connect_socket_not_exists(self, capsys):
        """测试 socket 文件不存在时的错误处理"""
        # 使用一个不存在的路径
        client = LocalClient("nonexistent_session_xyz")
        # 确保路径不存在
        client.socket_path = Path("/tmp/nonexistent_socket_path_xyz.sock")

        result = await client.connect()

        assert result is False

        captured = capsys.readouterr()
        assert "Socket 文件不存在" in captured.out
        assert "nonexistent_session_xyz" in captured.out

    @pytest.mark.anyio
    async def test_connect_timeout(self, capsys):
        """测试连接超时"""
        client = LocalClient("test_session")

        # 创建一个临时的 socket 文件用于测试
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".sock", delete=False) as f:
            client.socket_path = Path(f.name)

        try:
            # 模拟 wait_for 超时
            async def mock_wait_for(coro, timeout):
                raise asyncio.TimeoutError()

            with patch('asyncio.wait_for', side_effect=mock_wait_for):
                result = await client.connect()

            assert result is False

            captured = capsys.readouterr()
            assert "连接超时" in captured.out
        finally:
            # 清理临时文件
            client.socket_path.unlink(missing_ok=True)

    @pytest.mark.anyio
    async def test_connect_connection_refused(self, capsys):
        """测试连接被拒绝"""
        client = LocalClient("test_session")

        # 创建一个临时的 socket 文件用于测试
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".sock", delete=False) as f:
            client.socket_path = Path(f.name)

        try:
            # 模拟 wait_for 抛出 ConnectionRefusedError
            async def mock_wait_for(coro, timeout):
                raise ConnectionRefusedError()

            with patch('asyncio.wait_for', side_effect=mock_wait_for):
                with patch('utils.session.list_active_sessions', return_value=[]):
                    result = await client.connect()

            assert result is False

            captured = capsys.readouterr()
            assert "Connection refused" in captured.out
        finally:
            # 清理临时文件
            client.socket_path.unlink(missing_ok=True)

    @pytest.mark.anyio
    async def test_connect_success(self, capsys):
        """测试成功连接"""
        client = LocalClient("test_session")

        # 创建模拟的 reader 和 writer
        mock_reader = AsyncMock()
        mock_writer = MagicMock()

        # 创建一个临时的 socket 文件用于测试
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".sock", delete=False) as f:
            client.socket_path = Path(f.name)

        try:
            # 模拟成功连接
            async def mock_wait_for(coro, timeout):
                return (mock_reader, mock_writer)

            with patch('asyncio.wait_for', side_effect=mock_wait_for):
                with patch('asyncio.open_unix_connection', return_value=(mock_reader, mock_writer)):
                    result = await client.connect()

            assert result is True
            assert client.reader is mock_reader
            assert client.writer is mock_writer

            captured = capsys.readouterr()
            assert "已连接到会话" in captured.out
        finally:
            # 清理临时文件
            client.socket_path.unlink(missing_ok=True)


class TestLocalClientSendMessage:
    """测试发送消息"""

    @pytest.mark.anyio
    async def test_send_message(self):
        """测试发送消息"""
        client = LocalClient("test_session")

        # 设置模拟的 writer
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        client.writer = mock_writer

        # 发送消息
        msg = InputMessage(b"test input", client.client_id)
        await client.send_message(msg)

        # 验证 writer.write 被调用
        assert mock_writer.write.called
        # 验证 drain 被调用
        mock_writer.drain.assert_called_once()

    @pytest.mark.anyio
    async def test_send_message_no_writer(self):
        """测试没有 writer 时发送消息"""
        client = LocalClient("test_session")
        client.writer = None

        # 不应该抛出异常
        msg = InputMessage(b"test input", client.client_id)
        await client.send_message(msg)


class TestLocalClientReadMessage:
    """测试读取消息"""

    @pytest.mark.anyio
    async def test_read_message_with_complete_message(self):
        """测试读取完整消息"""
        client = LocalClient("test_session")

        # 设置模拟的 reader
        mock_reader = AsyncMock()
        client.reader = mock_reader

        # 准备一条完整的消息（包含换行符）
        msg = InputMessage(b"test data", "test_client")
        encoded = encode_message(msg)
        client.buffer = encoded

        # 读取消息
        result = await client.read_message()

        assert result is not None
        assert result.type == MessageType.INPUT

    @pytest.mark.anyio
    async def test_read_message_with_partial_data(self):
        """测试读取部分数据（需要从 reader 读取更多）"""
        client = LocalClient("test_session")

        # 设置模拟的 reader
        mock_reader = AsyncMock()
        client.reader = mock_reader

        # 准备部分数据
        msg = InputMessage(b"test data", "test_client")
        encoded = encode_message(msg)
        half_len = len(encoded) // 2

        client.buffer = encoded[:half_len]
        # 模拟 reader.read 返回剩余数据
        mock_reader.read.return_value = encoded[half_len:]

        # 读取消息
        result = await client.read_message()

        assert result is not None
        assert result.type == MessageType.INPUT
        mock_reader.read.assert_called_once()

    @pytest.mark.anyio
    async def test_read_message_connection_closed(self):
        """测试连接关闭时读取消息"""
        client = LocalClient("test_session")

        # 设置模拟的 reader
        mock_reader = AsyncMock()
        client.reader = mock_reader

        # buffer 为空，reader 返回空数据
        client.buffer = b""
        mock_reader.read.return_value = b""

        # 读取消息
        result = await client.read_message()

        assert result is None


class TestLocalClientCloseConnection:
    """测试关闭连接"""

    @pytest.mark.anyio
    async def test_close_connection(self):
        """测试关闭连接"""
        client = LocalClient("test_session")

        # 设置模拟的 writer
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        client.writer = mock_writer
        client._connected = True

        await client.close_connection()

        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_called_once()

    @pytest.mark.anyio
    async def test_close_connection_no_writer(self):
        """测试没有 writer 时关闭连接"""
        client = LocalClient("test_session")
        client.writer = None

        # 不应该抛出异常
        await client.close_connection()


class TestLocalClientBuffer:
    """测试 buffer 处理"""

    @pytest.mark.anyio
    async def test_buffer_accumulation(self):
        """测试 buffer 累积"""
        client = LocalClient("test_session")

        # 设置模拟的 reader
        mock_reader = AsyncMock()
        client.reader = mock_reader

        # 模拟分两次读取
        msg = InputMessage(b"test data", "test_client")
        encoded = encode_message(msg)
        part1 = encoded[:10]
        part2 = encoded[10:]

        client.buffer = part1
        mock_reader.read.return_value = part2

        result = await client.read_message()

        assert result is not None
        assert result.type == MessageType.INPUT


class TestRunClient:
    """测试 run_client 函数"""

    def test_run_client_function_exists(self):
        """测试 run_client 函数存在"""
        from client.local_client import run_client
        assert callable(run_client)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
