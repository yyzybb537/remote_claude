# server/ws_handler.py

import asyncio
import logging
from typing import Set, Tuple, Optional, TYPE_CHECKING
from urllib.parse import urlparse, parse_qs
from pathlib import Path

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection
else:
    ServerConnection = None

import websockets.exceptions

from utils.protocol import (
    Message, MessageType, InputMessage, ResizeMessage,
    OutputMessage, ErrorMessage, ControlMessage, ControlResponseMessage,
    encode_message, decode_message
)
from server.token_manager import TokenManager

logger = logging.getLogger('WSHandler')


def parse_url_params(path: str) -> Tuple[Optional[str], Optional[str]]:
    """解析 URL 参数

    Args:
        path: URL 路径，如 "/ws?session=mywork&token=abc123"

    Returns:
        (session, token) 元组，缺失的参数为 None
    """
    parsed = urlparse(path)
    params = parse_qs(parsed.query)

    session = params.get('session', [None])[0]
    token = params.get('token', [None])[0]

    return session, token


class WebSocketHandler:
    """WebSocket 连接处理器

    负责：
    - 处理 WebSocket 连接（认证、连接数限制）
    - 解析 URL 参数（session、token）
    - 消息转发（INPUT → PTY、RESIZE → PTY、CONTROL → 处理）
    - 广播输出到所有 WebSocket 客户端
    - 控制命令处理框架（shutdown/restart/update）
    """

    MAX_WS_CONNECTIONS = 10

    def __init__(self, server, session_name: str, data_dir: Path = None):
        """初始化 WebSocket 处理器

        Args:
            server: Server 实例，用于访问 PTY 写入方法等
            session_name: 会话名称
            data_dir: 数据目录，用于存储 token 文件
        """
        self.server = server
        self.session_name = session_name
        self.token_manager = TokenManager(session_name, data_dir)
        self.ws_connections: Set["ServerConnection"] = set()

    async def handle_connection(self, websocket: "ServerConnection", path: str):
        """处理 WebSocket 连接

        流程：
        1. 解析 URL 参数
        2. 验证 session 匹配
        3. 验证 token
        4. 检查连接数限制
        5. 发送历史输出
        6. 进入消息处理循环
        """
        # 1. 解析 URL 参数
        session, token = parse_url_params(path)

        # 2. 验证 session
        if session != self.session_name:
            await self._send_error(websocket, "SESSION_NOT_FOUND", f"会话 {session} 不存在")
            return

        # 3. 验证 token
        if not self._authenticate(token):
            await self._send_error(websocket, "INVALID_TOKEN", "认证失败，请检查 token")
            return

        # 4. 检查连接数限制
        if len(self.ws_connections) >= self.MAX_WS_CONNECTIONS:
            await self._send_error(websocket, "TOO_MANY_CONNECTIONS", "连接数已达上限")
            return

        # 5. 加入连接集合
        self.ws_connections.add(websocket)
        client_id = f"ws-{id(websocket)}"
        logger.info(f"WebSocket 客户端连接: {client_id}, 当前连接数: {len(self.ws_connections)}")

        try:
            # 6. 发送历史输出（如果有）
            if hasattr(self.server, 'history_buffer') and self.server.history_buffer:
                history_msg = OutputMessage(self.server.history_buffer)
                await websocket.send(encode_message(history_msg))

            # 7. 消息处理循环
            async for raw_message in websocket:
                try:
                    msg = decode_message(raw_message)
                    await self._handle_message(websocket, msg, client_id)
                except Exception as e:
                    logger.error(f"处理消息失败: {e}")

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.ws_connections.discard(websocket)
            logger.info(f"WebSocket 客户端断开: {client_id}, 当前连接数: {len(self.ws_connections)}")

    def _authenticate(self, token: str) -> bool:
        """验证 token

        Args:
            token: 要验证的 token 字符串

        Returns:
            True 如果 token 有效，False 否则
        """
        if not token:
            return False
        return self.token_manager.verify_token(token)

    async def _handle_message(self, websocket: "ServerConnection", msg: Message, client_id: str):
        """处理消息

        Args:
            websocket: WebSocket 连接
            msg: 解析后的消息对象
            client_id: 客户端标识
        """
        if msg.type == MessageType.INPUT:
            # 转发输入到 PTY
            data = msg.get_data()
            if hasattr(self.server, '_write_to_pty'):
                self.server._write_to_pty(data)

        elif msg.type == MessageType.RESIZE:
            # 转发终端大小变化
            if hasattr(self.server, '_resize_pty'):
                self.server._resize_pty(msg.rows, msg.cols)

        elif msg.type == MessageType.CONTROL:
            # 处理控制命令
            response = await self._handle_control(msg.action)
            await websocket.send(encode_message(response))

    async def _handle_control(self, action: str) -> ControlResponseMessage:
        """处理控制命令

        Args:
            action: 控制命令（shutdown/restart/update）

        Returns:
            控制命令响应
        """
        if action == "shutdown":
            logger.info("收到远程关闭命令")
            # 设置关闭标志，主循环会处理
            if hasattr(self.server, '_shutdown_event'):
                self.server._shutdown_event.set()
            return ControlResponseMessage(True, "正在关闭服务器...")

        elif action == "restart":
            logger.info("收到远程重启命令")
            # TODO: 实现重启逻辑
            return ControlResponseMessage(False, "重启功能尚未实现")

        elif action == "update":
            logger.info("收到远程更新命令")
            # TODO: 实现更新逻辑
            return ControlResponseMessage(False, "更新功能尚未实现")

        else:
            return ControlResponseMessage(False, f"未知命令: {action}")

    async def broadcast_to_ws(self, data: bytes):
        """广播输出到所有 WebSocket 客户端

        Args:
            data: 要广播的数据（通常是 PTY 输出）
        """
        if not self.ws_connections:
            return

        msg = OutputMessage(data)
        encoded = encode_message(msg)

        # 使用 gather 并行发送，忽略已断开的连接
        tasks = []
        for ws in list(self.ws_connections):
            tasks.append(self._safe_send(ws, encoded))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_send(self, websocket: "ServerConnection", data: bytes):
        """安全发送消息

        发送失败时自动移除连接。

        Args:
            websocket: WebSocket 连接
            data: 要发送的数据
        """
        try:
            await websocket.send(data)
        except Exception:
            self.ws_connections.discard(websocket)

    async def _send_error(self, websocket: "ServerConnection", code: str, message: str):
        """发送错误消息并关闭连接

        Args:
            websocket: WebSocket 连接
            code: 错误代码
            message: 错误消息
        """
        msg = ErrorMessage(message, code)
        await websocket.send(encode_message(msg))
        await websocket.close()
