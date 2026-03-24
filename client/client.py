"""
客户端连接器

- 终端 raw mode 处理
- Socket 连接
- 输入转发
- 输出显示
- Ctrl+D 退出
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

from utils.protocol import (
    Message, MessageType, InputMessage, ResizeMessage,
    encode_message, decode_message
)
from utils.session import get_socket_path, generate_client_id, get_terminal_size

try:
    from stats import track as _track_stats
except Exception:
    def _track_stats(*args, **kwargs): pass


# 特殊按键
CTRL_D = b'\x04'  # Ctrl+D - 退出


class RemoteClient:
    """远程客户端"""

    def __init__(self, session_name: str):
        self.session_name = session_name
        self.socket_path = get_socket_path(session_name)
        self.client_id = generate_client_id()

        # 连接
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.buffer = b""

        # 状态
        self.running = False

        # 终端设置
        self.old_settings = None

    async def connect(self) -> bool:
        """连接到服务器"""
        if not self.socket_path.exists():
            print(
                f"❌ 错误: Socket 文件不存在\n"
                f"   会话名: {self.session_name}\n"
                f"   Socket 路径: {self.socket_path}\n"
                f"\n"
                f"   请使用 `python3 remote_claude.py list` 查看可用会话"
            )
            return False

        try:
            self.reader, self.writer = await asyncio.open_unix_connection(
                path=str(self.socket_path)
            )
            print(f"✅ 已连接到会话: {self.session_name}")
            return True
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
                f"     python3 remote_claude.py kill {self.session_name}\n"
                f"     python3 remote_claude.py start {self.session_name}"
            )
            return False
        except Exception as e:
            print(
                f"❌ 连接失败: {type(e).__name__}: {e}\n"
                f"   会话名: {self.session_name}\n"
                f"   Socket 路径: {self.socket_path}"
            )
            return False

    async def run(self) -> int:
        """运行客户端，返回退出码（0=成功，非零=失败）"""
        if not await self.connect():
            return 1  # 连接失败

        self.running = True
        _track_stats('terminal', 'connect', session_name=self.session_name)

        # 设置终端 raw mode
        self._setup_terminal()

        # 设置信号处理
        self._setup_signals()

        # 发送初始终端尺寸，让 server 将 PTY 调整为实际终端大小
        rows, cols = get_terminal_size()
        await self._send_resize(rows, cols)

        try:
            # 并行运行输入和输出处理
            await asyncio.gather(
                self._read_server(),
                self._read_stdin(),
                return_exceptions=True
            )
        finally:
            self._cleanup()

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
        if self.running and self.writer:
            rows, cols = get_terminal_size()
            asyncio.create_task(self._send_resize(rows, cols))

    async def _send_resize(self, rows: int, cols: int):
        """发送终端大小"""
        msg = ResizeMessage(rows, cols, self.client_id)
        await self._send_message(msg)

    async def _read_server(self):
        """读取服务器消息"""
        while self.running:
            try:
                msg = await asyncio.wait_for(self._read_message(), timeout=0.5)
                if msg is None:
                    self.running = False
                    break
                await self._handle_server_message(msg)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

    async def _read_message(self) -> Optional[Message]:
        """读取一条消息"""
        while True:
            if b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                try:
                    return decode_message(line)
                except Exception:
                    continue

            try:
                data = await self.reader.read(4096)
                if not data:
                    return None
                self.buffer += data
            except Exception:
                return None

    async def _handle_server_message(self, msg: Message):
        """处理服务器消息"""
        if msg.type == MessageType.OUTPUT:
            data = msg.get_data()
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

        elif msg.type == MessageType.HISTORY:
            data = msg.get_data()
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

    async def _read_stdin(self):
        """读取标准输入"""
        loop = asyncio.get_event_loop()

        while self.running:
            try:
                # 在线程池中读取标准输入（带超时）
                data = await loop.run_in_executor(None, self._read_stdin_sync)
                if data:
                    await self._handle_input(data)
                    if not self.running:
                        break
            except Exception:
                break

    def _read_stdin_sync(self) -> bytes:
        """同步读取标准输入（带超时，便于检查 running 状态）"""
        # 使用 select 等待输入，超时 0.1 秒
        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
        if rlist:
            return os.read(sys.stdin.fileno(), 1024)
        return b""

    async def _handle_input(self, data: bytes):
        """处理输入"""
        # Ctrl+D 退出
        if data == CTRL_D:
            self.running = False
            return

        # 其他按键都发送给 Claude
        _track_stats('terminal', 'input', session_name=self.session_name,
                     value=len(data))
        await self._send_input(data)

    async def _send_input(self, data: bytes):
        """发送输入"""
        msg = InputMessage(data, self.client_id)
        await self._send_message(msg)

    async def _send_message(self, msg: Message):
        """发送消息"""
        if self.writer:
            try:
                data = encode_message(msg)
                self.writer.write(data)
                await self.writer.drain()
            except Exception:
                pass

    def _cleanup(self):
        """清理"""
        self.running = False
        _track_stats('terminal', 'disconnect', session_name=self.session_name)
        self._restore_terminal()

        if self.writer:
            try:
                self.writer.close()
            except Exception:
                pass

        print("\n已断开连接")


def run_client(session_name: str) -> int:
    """运行客户端，返回退出码（0=成功，非零=失败）"""
    client = RemoteClient(session_name)

    try:
        return asyncio.run(client.run())
    except KeyboardInterrupt:
        return 130  # 128 + SIGINT(2)，Unix 惯例


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Remote Claude Client")
    parser.add_argument("session_name", help="会话名称")
    args = parser.parse_args()

    sys.exit(run_client(args.session_name))
