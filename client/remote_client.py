"""
远程客户端（WebSocket 实现）

通过 WebSocket 连接远程 Server，继承 BaseWSClient 实现：
- connect() - WebSocket 连接
- send_message() - WebSocket 发送
- read_message() - WebSocket 接收
- close_connection() - WebSocket 关闭
"""

import argparse
import asyncio
import sys
from typing import Optional

from websockets.asyncio.client import connect, ClientConnection
from websockets import exceptions as ws_exceptions

from client.base_client import BaseWSClient
from utils.protocol import Message, encode_message, decode_message


class RemoteClient(BaseWSClient):
    """远程客户端（WebSocket 实现）

    通过 WebSocket 连接远程 PTY 服务器。
    """

    def __init__(self, host: str, session_name: str, token: str, port: int = 8765):
        """初始化远程客户端

        Args:
            host: 服务器主机地址
            session_name: 会话名称
            token: 认证令牌
            port: 服务器端口（默认 8765）
        """
        super().__init__(session_name, host, port, token)

        # WebSocket 连接
        self._ws: Optional[ClientConnection] = None

    async def connect(self) -> bool:
        """建立 WebSocket 连接

        Returns:
            True 表示连接成功，False 表示连接失败
        """
        try:
            url = self._get_ws_url()
            self._ws = await connect(
                url,
                ping_interval=30,
                ping_timeout=60,
            )
            self._connected = True
            print(f"✅ 已连接到远程会话: {self.session_name}@{self.host}")
            return True
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False

    async def send_message(self, msg: Message) -> None:
        """发送消息

        Args:
            msg: 要发送的消息

        Raises:
            ConnectionError: 连接已断开或发送失败
        """
        if not self._ws or not self._connected:
            raise ConnectionError("连接未建立")

        try:
            await self._ws.send(encode_message(msg))
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"发送失败: {e}") from e

    async def read_message(self) -> Optional[Message]:
        """读取消息

        Returns:
            Message: 接收到的消息，连接关闭返回 None
        """
        if not self._ws or not self._connected:
            return None

        try:
            raw = await self._ws.recv()
            # 处理字符串或字节类型
            if isinstance(raw, str):
                raw = raw.encode()
            msg = decode_message(raw)
            return msg
        except ws_exceptions.ConnectionClosed:
            self._connected = False
            return None
        except Exception:
            return None

    async def close_connection(self) -> None:
        """关闭 WebSocket 连接"""
        self._connected = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None


def run_remote_client(host: str, session: str, token: str, port: int = 8765) -> int:
    """运行远程客户端

    Args:
        host: 服务器主机地址
        session: 会话名称
        token: 认证令牌
        port: 服务器端口

    Returns:
        退出码（0=成功，非零=失败）
    """
    client = RemoteClient(host, session, token, port)
    try:
        return asyncio.run(client.run())
    except KeyboardInterrupt:
        return 130  # 128 + SIGINT(2)，Unix 惯例


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remote Claude WebSocket Client")
    parser.add_argument("host", help="服务器主机地址")
    parser.add_argument("session", help="会话名称")
    parser.add_argument("token", help="认证令牌")
    parser.add_argument("--port", type=int, default=8765, help="服务器端口")
    args = parser.parse_args()

    sys.exit(run_remote_client(args.host, args.session, args.token, args.port))
