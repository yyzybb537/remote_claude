"""
本地客户端

通过 Unix Socket 连接到本地服务器的终端客户端实现

功能：
- Unix Socket 连接管理
- 错误诊断（socket 不存在、连接超时、连接拒绝等）
- 消息收发
"""

import argparse
import asyncio
import sys
from typing import Optional

from client.base_client import BaseClient
from utils.protocol import Message, encode_message, decode_message
from utils.session import get_socket_path


class LocalClient(BaseClient):
    """本地客户端（Unix Socket 连接）

    通过 Unix Domain Socket 连接到本地 PTY 代理服务器。
    """

    def __init__(self, session_name: str):
        """初始化本地客户端

        Args:
            session_name: 会话名称
        """
        super().__init__(session_name)

        # Socket 路径
        self.socket_path = get_socket_path(session_name)

        # 连接对象
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

    async def connect(self) -> bool:
        """连接到 Unix Socket 服务器

        Returns:
            bool: 连接成功返回 True，失败返回 False
        """
        # 检查 socket 文件是否存在
        if not self.socket_path.exists():
            print(
                f"❌ 错误: Socket 文件不存在\n"
                f"   会话名: {self.session_name}\n"
                f"   Socket 路径: {self.socket_path}\n"
                f"\n"
                f"   请使用 `remote-claude list` 查看可用会话"
            )
            return False

        try:
            # 添加连接超时（5秒），避免在服务器关闭时无限阻塞
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_unix_connection(path=str(self.socket_path)),
                timeout=5.0
            )
            print(f"✅ 已连接到会话: {self.session_name}")
            return True

        except asyncio.TimeoutError:
            print(
                f"❌ 连接超时\n"
                f"   会话名: {self.session_name}\n"
                f"   Socket 路径: {self.socket_path}\n"
                f"\n"
                f"   可能原因: Server 进程正在关闭或无响应"
            )
            return False

        except ConnectionRefusedError as e:
            # 检查进程状态
            from utils.session import list_active_sessions
            sessions = list_active_sessions()
            session_exists = any(s["name"] == self.session_name for s in sessions)

            print(
                f"❌ 连接失败: Connection refused\n"
                f"   会话名: {self.session_name}\n"
                f"   Socket 路径: {self.socket_path}\n"
                f"   文件存在: {self.socket_path.exists()}\n"
                f"   会话在列表中: {session_exists}\n"
                f"\n"
                f"   当前活跃会话:"
            )
            for s in sessions:
                print(f"     - {s['name']} (PID: {s.get('pid', 'N/A')})")
            print(
                f"\n"
                f"   可能原因:\n"
                f"     1. Server 进程已终止但 Socket 文件残留\n"
                f"     2. Socket 文件权限错误\n"
                f"\n"
                f"   建议操作:\n"
                f"     remote-claude kill {self.session_name}\n"
                f"     remote-claude start {self.session_name}"
            )
            return False

        except Exception as e:
            print(
                f"❌ 连接失败: {type(e).__name__}: {e}\n"
                f"   会话名: {self.session_name}\n"
                f"   Socket 路径: {self.socket_path}"
            )
            return False

    async def send_message(self, msg: Message) -> None:
        """发送消息

        Args:
            msg: 要发送的消息

        Raises:
            ConnectionError: 连接已断开或发送失败
        """
        if not self.writer:
            raise ConnectionError("连接未建立")

        try:
            data = encode_message(msg)
            self.writer.write(data)
            await self.writer.drain()
        except Exception as e:
            # 连接可能已断开，标记状态
            self._connected = False
            raise ConnectionError(f"发送失败: {e}") from e

    async def read_message(self) -> Optional[Message]:
        """读取消息

        Returns:
            Message: 接收到的消息，连接关闭返回 None
        """
        while True:
            # 检查 buffer 中是否有完整消息
            if b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                try:
                    return decode_message(line)
                except Exception:
                    continue

            # 从 reader 读取更多数据
            try:
                data = await self.reader.read(4096)
                if not data:
                    return None
                self.buffer += data
            except Exception:
                return None

    async def close_connection(self) -> None:
        """关闭连接"""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            finally:
                self.writer = None
                self.reader = None


def run_client(session_name: str) -> int:
    """运行本地客户端

    Args:
        session_name: 会话名称

    Returns:
        int: 退出码（0=成功，非零=失败）
    """
    client = LocalClient(session_name)

    try:
        return asyncio.run(client.run())
    except KeyboardInterrupt:
        return 130  # 128 + SIGINT(2)，Unix 惯例


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remote Claude Local Client")
    parser.add_argument("session_name", help="会话名称")
    args = parser.parse_args()
    sys.exit(run_client(args.session_name))
