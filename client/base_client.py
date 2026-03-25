"""
终端客户端抽象基类

封装共享的终端处理逻辑：
- 终端 raw mode 设置/恢复
- 信号处理（终端大小变化）
- 输入/输出处理循环
- 统计追踪

传输层差异由子类实现：
- connect() - 建立连接
- send_message() - 发送消息
- read_message() - 读取消息
- close_connection() - 关闭连接
"""

import asyncio
import os
import sys
import tty
import termios
import signal
import select
from abc import ABC, abstractmethod
from typing import Optional

from utils.protocol import (
    Message, MessageType, InputMessage, ResizeMessage,
    encode_message, decode_message
)
from utils.session import generate_client_id

try:
    from stats import track as _track_stats
except Exception:
    def _track_stats(*args, **kwargs): pass


# 特殊按键
CTRL_D = b'\x04'  # Ctrl+D - 退出


class BaseClient(ABC):
    """终端客户端抽象基类

    子类需要实现传输层差异方法：
    - connect(): 建立连接
    - send_message(): 发送消息
    - read_message(): 读取消息
    - close_connection(): 关闭连接
    """

    def __init__(self, session_name: str):
        """初始化客户端

        Args:
            session_name: 会话名称
        """
        self.session_name = session_name
        self.client_id = generate_client_id()

        # 状态
        self.running = False
        self._connected = False

        # 终端设置
        self.old_settings: Optional[tuple] = None

        # 消息缓冲区
        self.buffer = b""

    # ==================== 抽象方法（传输层差异）====================

    @abstractmethod
    async def connect(self) -> bool:
        """建立连接

        Returns:
            bool: 连接成功返回 True，失败返回 False
        """
        pass

    @abstractmethod
    async def send_message(self, msg: Message) -> None:
        """发送消息

        Args:
            msg: 要发送的消息
        """
        pass

    @abstractmethod
    async def read_message(self) -> Optional[Message]:
        """读取消息

        Returns:
            Message: 接收到的消息，无消息返回 None
        """
        pass

    @abstractmethod
    async def close_connection(self) -> None:
        """关闭连接"""
        pass

    # ==================== 共享实现 ====================

    async def run(self) -> int:
        """运行客户端，返回退出码

        Returns:
            int: 退出码（0=成功，非零=失败）
        """
        if not await self.connect():
            return 1  # 连接失败

        self.running = True
        self._connected = True
        _track_stats('terminal', 'connect', session_name=self.session_name)

        # 设置终端 raw mode
        self._setup_terminal()

        # 设置信号处理
        self._setup_signals()

        # 发送初始终端尺寸
        rows, cols = self._get_terminal_size()
        await self._send_resize(rows, cols)

        try:
            # 并行运行输入和输出处理
            await asyncio.gather(
                self._read_connection_loop(),
                self._read_stdin_loop(),
                return_exceptions=True
            )
        finally:
            await self._cleanup()

        return 0  # 正常退出

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
        if self.running and self._connected:
            rows, cols = self._get_terminal_size()
            asyncio.create_task(self._send_resize(rows, cols))

    def _get_terminal_size(self) -> tuple[int, int]:
        """获取终端大小

        Returns:
            tuple[int, int]: (rows, cols)
        """
        try:
            size = os.get_terminal_size()
            return (size.lines, size.columns)
        except OSError:
            return (24, 80)  # 默认大小

    async def _send_resize(self, rows: int, cols: int):
        """发送终端大小变化消息

        Args:
            rows: 行数
            cols: 列数
        """
        msg = ResizeMessage(rows, cols, self.client_id)
        await self.send_message(msg)

    async def _read_stdin_loop(self):
        """读取标准输入循环"""
        loop = asyncio.get_event_loop()

        while self.running:
            try:
                # 在线程池中读取标准输入
                data = await loop.run_in_executor(None, self._read_stdin_sync)
                if data:
                    await self._handle_input(data)
                    if not self.running:
                        break
            except Exception:
                break

    def _read_stdin_sync(self) -> bytes:
        """同步读取标准输入（带超时）

        Returns:
            bytes: 读取到的数据，无数据返回空 bytes
        """
        # 使用 select 等待输入，超时 0.1 秒
        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
        if rlist:
            return os.read(sys.stdin.fileno(), 1024)
        return b""

    async def _handle_input(self, data: bytes):
        """处理用户输入

        Args:
            data: 用户输入数据
        """
        # Ctrl+D 退出
        if data == CTRL_D:
            self.running = False
            return

        # 其他按键发送给服务端
        _track_stats('terminal', 'input', session_name=self.session_name,
                     value=len(data))

        msg = InputMessage(data, self.client_id)
        await self.send_message(msg)

    async def _read_connection_loop(self):
        """读取连接消息循环"""
        while self.running:
            try:
                msg = await asyncio.wait_for(
                    self.read_message(),
                    timeout=0.5
                )
                if msg is None:
                    # 连接关闭
                    await self._on_disconnect("连接已关闭")
                    self.running = False
                    break
                await self._handle_message(msg)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

    async def _handle_message(self, msg: Message):
        """处理服务器消息

        Args:
            msg: 服务器消息
        """
        if msg.type == MessageType.OUTPUT:
            data = msg.get_data()
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

        elif msg.type == MessageType.HISTORY:
            data = msg.get_data()
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

    async def _on_disconnect(self, reason: str):
        """断线回调

        Args:
            reason: 断线原因
        """
        print("\n已断开连接")

    async def _cleanup(self):
        """清理资源"""
        self.running = False
        _track_stats('terminal', 'disconnect', session_name=self.session_name)

        # 恢复终端
        self._restore_terminal()

        # 关闭连接
        await self.close_connection()
