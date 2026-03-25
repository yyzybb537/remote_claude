"""
HTTP/WebSocket 客户端

- 从本地终端连接远程 Server
- 通过 WebSocket 进行认证
- 处理终端 raw mode
- 转发用户输入到远程
- 接收并显示远程输出
- 发送控制命令（shutdown/restart/update）
"""

import asyncio
import os
import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))  # 根目录 → protocol, utils
import sys
import tty
import termios
import signal
import select
from typing import Optional
from urllib.parse import urlencode

import websockets

from utils.protocol import (
    Message, MessageType, InputMessage, ResizeMessage,
    ControlMessage, OutputMessage, ErrorMessage,
    encode_message, decode_message
)
from utils.session import get_terminal_size, generate_client_id


def build_ws_url(host: str, port: Optional[int], session: str, token: str) -> str:
    """构建 WebSocket URL

    Args:
        host: 服务器主机地址
        port: 服务器端口（None 时使用默认端口 8765）
        session: 会话名称
        token: 认证令牌

    Returns:
        完整的 WebSocket URL
    """
    port = port or 8765
    params = urlencode({"session": session, "token": token})
    return f"ws://{host}:{port}/ws?{params}"


# 特殊按键
CTRL_D = b'\x04'  # Ctrl+D - 退出


class HTTPClient:
    """HTTP/WebSocket 客户端"""

    def __init__(self, host: str, session: str, token: str, port: int = 8765):
        """初始化客户端

        Args:
            host: 服务器主机地址
            session: 会话名称
            token: 认证令牌
            port: 服务器端口（默认 8765）
        """
        self.host = host
        self.session = session
        self.token = token
        self.port = port
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        self.old_settings = None
        self.client_id = generate_client_id()

    def _get_ws_url(self) -> str:
        """获取 WebSocket URL"""
        return build_ws_url(self.host, self.port, self.session, self.token)

    async def connect(self) -> bool:
        """连接到 Server

        Returns:
            True 表示连接成功，False 表示连接失败
        """
        try:
            url = self._get_ws_url()
            self.ws = await websockets.connect(
                url,
                ping_interval=30,
                ping_timeout=60,
            )
            print(f"✅ 已连接到远程会话: {self.session}@{self.host}")
            return True
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False

    async def run(self) -> int:
        """运行客户端

        Returns:
            退出码（0=成功，非零=失败）
        """
        if not await self.connect():
            return 1

        self.running = True

        # 设置终端 raw mode
        self._setup_terminal()

        # 设置信号处理
        self._setup_signals()

        # 发送初始终端大小
        rows, cols = get_terminal_size()
        await self._send_resize(rows, cols)

        try:
            # 并行运行输入和输出处理
            await asyncio.gather(
                self._read_stdin(),
                self._read_websocket(),
                return_exceptions=True
            )
        finally:
            self._cleanup()

        return 0

    def _setup_terminal(self):
        """设置终端 raw mode"""
        if sys.stdin.isatty():
            self.old_settings = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin.fileno())

    def _restore_terminal(self):
        """恢复终端设置"""
        if self.old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)

    def _setup_signals(self):
        """设置信号处理"""
        signal.signal(signal.SIGWINCH, self._handle_resize)

    def _handle_resize(self, signum, frame):
        """处理终端大小变化"""
        if self.running and self.ws:
            rows, cols = get_terminal_size()
            asyncio.create_task(self._send_resize(rows, cols))

    async def _read_stdin(self):
        """读取本地输入"""
        loop = asyncio.get_event_loop()

        while self.running:
            try:
                data = await loop.run_in_executor(None, self._read_stdin_sync)
                if data:
                    if data == CTRL_D:  # Ctrl+D
                        self.running = False
                        break
                    await self._send_input(data)
            except Exception:
                break

    def _read_stdin_sync(self) -> bytes:
        """同步读取标准输入"""
        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
        if rlist:
            return os.read(sys.stdin.fileno(), 1024)
        return b""

    async def _read_websocket(self):
        """读取远端输出"""
        while self.running:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=0.5)
                msg = decode_message(raw.encode() if isinstance(raw, str) else raw)
                await self._handle_message(msg)
            except asyncio.TimeoutError:
                continue
            except websockets.exceptions.ConnectionClosed:
                self._on_disconnect("连接已断开")
                self.running = False
                break
            except Exception:
                break

    async def _handle_message(self, msg: Message):
        """处理消息

        Args:
            msg: 接收到的消息
        """
        if msg.type == MessageType.OUTPUT:
            data = msg.get_data()
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

        elif msg.type == MessageType.HISTORY:
            data = msg.get_data()
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

        elif msg.type == MessageType.ERROR:
            print(f"\n错误: {msg.message} ({msg.code})")

    async def _send_input(self, data: bytes):
        """发送输入

        Args:
            data: 输入数据
        """
        if self.ws and self.running:
            msg = InputMessage(data, self.client_id)
            await self.ws.send(encode_message(msg))

    async def _send_resize(self, rows: int, cols: int):
        """发送终端大小

        Args:
            rows: 行数
            cols: 列数
        """
        if self.ws and self.running:
            msg = ResizeMessage(rows, cols, self.client_id)
            await self.ws.send(encode_message(msg))

    async def send_control(self, action: str) -> dict:
        """发送控制命令

        Args:
            action: 控制动作（shutdown/restart/update）

        Returns:
            响应字典，包含 success 和 message 字段
        """
        async with websockets.connect(self._get_ws_url()) as ws:
            msg = ControlMessage(action, self.client_id)
            await ws.send(encode_message(msg))

            # 等待响应
            response = await ws.recv()
            result = decode_message(response.encode() if isinstance(response, str) else response)
            return {
                "success": result.success if hasattr(result, 'success') else False,
                "message": result.message if hasattr(result, 'message') else ""
            }

    def _on_disconnect(self, reason: str):
        """断线回调

        Args:
            reason: 断线原因
        """
        print(f"\n{reason}")

    def _cleanup(self):
        """清理"""
        self.running = False
        self._restore_terminal()

        if self.ws:
            asyncio.create_task(self.ws.close())

        print("\n已断开连接")


def run_http_client(host: str, session: str, token: str, port: int = 8765) -> int:
    """运行 HTTP 客户端

    Args:
        host: 服务器主机地址
        session: 会话名称
        token: 认证令牌
        port: 服务器端口

    Returns:
        退出码（0=成功，非零=失败）
    """
    client = HTTPClient(host, session, token, port)
    try:
        return asyncio.run(client.run())
    except KeyboardInterrupt:
        return 130  # 128 + SIGINT(2)，Unix 惯例


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Remote Claude HTTP Client")
    parser.add_argument("host", help="服务器主机地址")
    parser.add_argument("session", help="会话名称")
    parser.add_argument("token", help="认证令牌")
    parser.add_argument("--port", type=int, default=8765, help="服务器端口")
    args = parser.parse_args()

    sys.exit(run_http_client(args.host, args.session, args.token, args.port))
