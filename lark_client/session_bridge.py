"""
会话桥接器 - 连接到 remote_claude 的 Unix Socket

职责：连接管理 + 输入发送。
输出处理由 SharedMemoryPoller 通过 .mq 共享内存文件负责，这里不处理。
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional, Callable, Dict

logger = logging.getLogger('SessionBridge')

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.protocol import (
    Message, MessageType, InputMessage,
    encode_message, decode_message
)
from utils.session import get_socket_path, generate_client_id, list_active_sessions


class SessionBridge:
    """连接到 remote_claude 会话的桥接器（仅负责输入发送）"""

    def __init__(self, session_name: str,
                 on_input: Optional[Callable[[str], None]] = None,
                 on_disconnect: Optional[Callable[[], None]] = None):
        self.session_name = session_name
        self.socket_path = get_socket_path(session_name)
        self.client_id = generate_client_id()
        self.on_input = on_input          # 其他客户端输入广播回调
        self.on_disconnect = on_disconnect  # 服务端关闭连接时的回调

        self._input_bytes = bytearray()   # 终端输入字节缓冲

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.buffer = b""
        self.running = False
        self._read_task: Optional[asyncio.Task] = None
        self._manually_disconnected = False  # 主动断开标志

    async def connect(self) -> bool:
        """连接到会话"""
        if not self.socket_path.exists():
            logger.error(
                f"连接失败: Socket 文件不存在\n"
                f"  会话名: {self.session_name}\n"
                f"  Socket 路径: {self.socket_path}\n"
                f"  请确认:\n"
                f"    1. 会话已启动 (使用 /list 查看)\n"
                f"    2. 会话名拼写正确"
            )
            return False
        try:
            self.reader, self.writer = await asyncio.open_unix_connection(
                path=str(self.socket_path)
            )
            self.running = True
            self._read_task = asyncio.create_task(self._read_loop())
            logger.info(f"连接成功: {self.session_name}")
            return True
        except FileNotFoundError:
            logger.error(
                f"连接失败: Socket 文件不存在\n"
                f"  会话名: {self.session_name}\n"
                f"  Socket 路径: {self.socket_path}\n"
                f"  可能原因: Socket 文件在连接前被删除"
            )
            return False
        except ConnectionRefusedError as e:
            # 检查进程状态
            sessions = list_active_sessions()
            session_exists = any(s["name"] == self.session_name for s in sessions)

            logger.error(
                f"连接失败: Connection refused\n"
                f"  会话名: {self.session_name}\n"
                f"  Socket 路径: {self.socket_path}\n"
                f"  文件存在: {self.socket_path.exists()}\n"
                f"  会话在列表中: {session_exists}\n"
                f"  当前活跃会话: {[s['name'] for s in sessions]}\n"
                f"  可能原因:\n"
                f"    1. Server 进程已终止但 Socket 文件残留\n"
                f"    2. Socket 文件权限错误\n"
                f"    建议: 使用 /kill {self.session_name} 清理后重新启动"
            )
            return False
        except Exception as e:
            logger.error(
                f"连接失败: {type(e).__name__}: {e}\n"
                f"  会话名: {self.session_name}\n"
                f"  Socket 路径: {self.socket_path}"
            )
            return False

    async def disconnect(self):
        """断开连接"""
        self._manually_disconnected = True
        self.running = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass

    async def send_input(self, text: str) -> bool:
        """发送输入到 Claude"""
        if not self.writer or not self.running:
            return False
        try:
            # 分两步发送：先发文本，等 Ink 框架处理完毕，再发 Enter
            # 不能合并为 text+\r 一次写入（Ink 同一 tick 处理时 \r 会被提前消费，导致需要两次 Enter）
            # 不能在文本前/后加 ESC（ESC+Enter 被终端解释为 Alt+Enter，导致换行而非提交）
            msg = InputMessage(text.encode('utf-8'), self.client_id)
            self.writer.write(encode_message(msg))
            await self.writer.drain()
            await asyncio.sleep(0.05)
            msg = InputMessage(b"\r", self.client_id)
            self.writer.write(encode_message(msg))
            await self.writer.drain()
            return True
        except Exception as e:
            logger.error(f"发送失败: {e}")
            return False

    async def send_key(self, key: str) -> bool:
        """发送单个按键到 Claude（用于交互式选项）

        注意：此方法会自动追加 Enter 以确认选项。对于不需要 Enter 的按键（如 ESC)，
        请使用 send_raw 方法发送原始字节。
        """
        if not self.writer or not self.running:
            return False
        try:
            logger.info(f"发送按键: {repr(key)}")
            # 将按键名转换为实际的按键序列
            KEY_MAP = {
                "up": b"\x1b[A",         # ↑ 上箭头
                "down": b"\x1b[B",       # ↓ 下箭头
                "ctrl_o": b"\x0f",       # Ctrl+O
                "shift_tab": b"\x1b[Z",  # Shift+Tab
                "esc": b"\x1b",        # ESC (单独发送，不追加 Enter)
                "enter": b"\r",       # Enter
            }
            key_bytes = KEY_MAP.get(key, key.encode('utf-8'))
            if not key_bytes:
                logger.warning(f"未知按键: {key}")
                return False

            # 发送按键序列
            msg = InputMessage(key_bytes, self.client_id)
            self.writer.write(encode_message(msg))
            await self.writer.drain()
            # ESC 键不需要追加 Enter
            if key == "esc":
                logger.debug(f"ESC 按键不追加 Enter")
                return True
            # 其他按键追加 Enter 以确认选项
            await asyncio.sleep(0.05)
            msg = InputMessage(b"\r", self.client_id)
            self.writer.write(encode_message(msg))
            await self.writer.drain()
            return True
        except Exception as e:
            logger.error(f"发送按键失败: {e}")
            return False

    async def send_raw(self, data: bytes) -> bool:
        """发送原始字节到 Claude（不自动追加回车）"""
        if not self.writer or not self.running:
            return False
        try:
            msg = InputMessage(data, self.client_id)
            self.writer.write(encode_message(msg))
            await self.writer.drain()
            return True
        except Exception as e:
            logger.error(f"发送原始字节失败: {e}")
            return False

    async def _read_loop(self):
        """读取服务器消息（OUTPUT/HISTORY 直接丢弃，由 SharedMemoryPoller 处理）"""
        while self.running:
            try:
                msg = await asyncio.wait_for(self._read_message(), timeout=1.0)
                if msg is None:
                    self.running = False
                    break
                if msg.type == MessageType.INPUT and self.on_input:
                    self._process_input_bytes(msg.get_data())
                # OUTPUT / HISTORY / STATUS 消息直接丢弃
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"读取错误: {e}")
                break

        if self.on_disconnect and not self._manually_disconnected:
            try:
                self.on_disconnect()
            except Exception as e:
                logger.error(f"on_disconnect 回调异常: {e}")

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

    def _process_input_bytes(self, data: bytes):
        """处理终端输入字节，触发 on_input 回调"""
        for byte in data:
            if byte in (0x0d, 0x0a):  # CR or LF → 完整一行
                if self._input_bytes:
                    try:
                        text = self._input_bytes.decode('utf-8').strip()
                    except UnicodeDecodeError:
                        text = self._input_bytes.decode('utf-8', errors='ignore').strip()
                    if text and self.on_input:
                        self.on_input(text)
                    self._input_bytes.clear()
            elif byte in (0x7f, 0x08):  # backspace
                if self._input_bytes:
                    self._input_bytes = self._input_bytes[:-1]
            elif byte == 0x1b:  # ESC → 清空
                self._input_bytes.clear()
            elif byte >= 0x20:
                self._input_bytes.append(byte)
