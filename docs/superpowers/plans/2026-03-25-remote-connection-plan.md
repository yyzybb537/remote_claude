# 远程连接实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Remote Claude 添加远程连接能力，支持从本地 client 通过 WebSocket 连接远端 server

**Architecture:** Server 内置 WebSocket 支持（使用 websockets 库），本地 Unix Socket 和远程 WebSocket 双模式共存，静态 Token 认证

**Tech Stack:** Python asyncio, websockets>=12.0, secrets/base64

---

## 文件结构

```
新增文件:
├── server/token_manager.py   # Token 管理器
├── server/ws_handler.py      # WebSocket 处理器
├── client/http_client.py     # HTTP/WebSocket 客户端

修改文件:
├── utils/protocol.py         # 新增 CONTROL/CONTROL_RESPONSE 消息类型
├── server/server.py          # 集成 WebSocket Server
├── remote_claude.py          # CLI 子命令扩展
├── pyproject.toml            # 添加 websockets 依赖

测试文件:
├── tests/test_token_manager.py
├── tests/test_ws_handler.py
├── tests/test_http_client.py
```

---

### Task 1: 添加 websockets 依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 添加 websockets 依赖到 pyproject.toml**

在 `dependencies` 数组中添加 `websockets>=12.0`：

```toml
dependencies = [
    # ... 现有依赖 ...
    "websockets>=12.0",
]
```

- [ ] **Step 2: 同步依赖**

Run: `uv sync`
Expected: 成功安装 websockets

- [ ] **Step 3: 验证安装**

Run: `uv run python -c "import websockets; print(websockets.__version__)"`
Expected: 输出 websockets 版本号

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: 添加 websockets 依赖

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: 扩展消息协议（CONTROL 类型）

**Files:**
- Modify: `utils/protocol.py`
- Create: `tests/test_protocol_control.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_protocol_control.py

from utils.protocol import (
    Message, MessageType, ControlMessage, ControlResponseMessage,
    encode_message, decode_message
)

def test_control_message_creation():
    """测试 CONTROL 消息创建"""
    msg = ControlMessage("shutdown", "client-123")
    assert msg.type == MessageType.CONTROL
    assert msg.action == "shutdown"
    assert msg.client_id == "client-123"

def test_control_message_encode_decode():
    """测试 CONTROL 消息编解码"""
    msg = ControlMessage("restart", "client-456")
    encoded = encode_message(msg)
    decoded = decode_message(encoded.strip())
    assert decoded.type == MessageType.CONTROL
    assert decoded.action == "restart"
    assert decoded.client_id == "client-456"

def test_control_response_message():
    """测试 CONTROL_RESPONSE 消息"""
    msg = ControlResponseMessage(True, "重启成功")
    encoded = encode_message(msg)
    decoded = decode_message(encoded.strip())
    assert decoded.type == MessageType.CONTROL_RESPONSE
    assert decoded.success is True
    assert decoded.message == "重启成功"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_protocol_control.py -v`
Expected: FAIL with "cannot import name 'ControlMessage'"

- [ ] **Step 3: Write minimal implementation**

```python
# utils/protocol.py
# 在 MessageType 枚举中添加:
class MessageType(str, Enum):
    """消息类型"""
    INPUT = "input"
    OUTPUT = "output"
    HISTORY = "history"
    ERROR = "error"
    RESIZE = "resize"
    CONTROL = "control"              # 新增
    CONTROL_RESPONSE = "control_response"  # 新增


# 新增 CONTROL 消息类:
@dataclass
class ControlMessage(Message):
    """控制命令消息"""
    action: str  # shutdown / restart / update
    client_id: str

    def __init__(self, action: str, client_id: str):
        super().__init__(type=MessageType.CONTROL)
        self.action = action
        self.client_id = client_id

    @classmethod
    def from_dict(cls, obj: dict) -> "ControlMessage":
        msg = object.__new__(cls)
        msg.type = obj["type"]
        msg.action = obj["action"]
        msg.client_id = obj["client_id"]
        return msg


@dataclass
class ControlResponseMessage(Message):
    """控制命令响应"""
    success: bool
    message: str

    def __init__(self, success: bool, message: str):
        super().__init__(type=MessageType.CONTROL_RESPONSE)
        self.success = success
        self.message = message

    @classmethod
    def from_dict(cls, obj: dict) -> "ControlResponseMessage":
        msg = object.__new__(cls)
        msg.type = obj["type"]
        msg.success = obj["success"]
        msg.message = obj["message"]
        return msg


# 修改 Message.from_json() 添加新类型:
@classmethod
def from_json(cls, data: str) -> "Message":
    obj = json.loads(data)
    msg_type = obj.get("type")
    # ... 现有类型 ...
    elif msg_type == MessageType.CONTROL:
        return ControlMessage.from_dict(obj)
    elif msg_type == MessageType.CONTROL_RESPONSE:
        return ControlResponseMessage.from_dict(obj)
    # ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_protocol_control.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add utils/protocol.py tests/test_protocol_control.py
git commit -m "feat(protocol): 新增 CONTROL/CONTROL_RESPONSE 消息类型

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: 实现 Token 管理器

**Files:**
- Create: `server/token_manager.py`
- Create: `tests/test_token_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_token_manager.py

import os
import json
import tempfile
from pathlib import Path
from server.token_manager import TokenManager, generate_token

class TestTokenManager:
    """Token 管理器测试"""

    def test_generate_token_length(self):
        """测试 token 长度为 32 字节的 base64"""
        token = generate_token()
        assert len(token) >= 43  # 32 bytes base64 编码后至少 43 字符

    def test_generate_token_uniqueness(self):
        """测试每次生成的 token 不同"""
        token1 = generate_token()
        token2 = generate_token()
        assert token1 != token2

    def test_get_or_create_token_creates_new(self, tmp_path):
        """测试首次获取时创建新 token"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        token = manager.get_or_create_token()
        assert token is not None
        assert manager.verify_token(token)

    def test_get_or_create_token_loads_existing(self, tmp_path):
        """测试已存在时加载 token"""
        manager1 = TokenManager("test-session", data_dir=tmp_path)
        token1 = manager1.get_or_create_token()

        manager2 = TokenManager("test-session", data_dir=tmp_path)
        token2 = manager2.get_or_create_token()
        assert token1 == token2

    def test_verify_token_correct(self, tmp_path):
        """测试正确 token 验证"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        token = manager.get_or_create_token()
        assert manager.verify_token(token) is True

    def test_verify_token_incorrect(self, tmp_path):
        """测试错误 token 验证"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        manager.get_or_create_token()
        assert manager.verify_token("wrong-token") is False

    def test_regenerate_token(self, tmp_path):
        """测试重新生成 token"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        old_token = manager.get_or_create_token()

        new_token = manager.regenerate_token()
        assert new_token != old_token
        assert manager.verify_token(old_token) is False
        assert manager.verify_token(new_token) is True

    def test_token_file_permissions(self, tmp_path):
        """测试 token 文件权限为 0600"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        manager.get_or_create_token()

        token_file = tmp_path / "test-session_token.json"
        stat_info = os.stat(token_file)
        assert (stat_info.st_mode & 0o777) == 0o600

    def test_token_file_tamper_detection(self, tmp_path):
        """测试 token 文件篡改检测"""
        manager = TokenManager("test-session", data_dir=tmp_path)
        token = manager.get_or_create_token()

        # 篡改文件
        token_file = tmp_path / "test-session_token.json"
        with open(token_file, 'r') as f:
            content = json.load(f)
        content['token'] = 'tampered-token'
        with open(token_file, 'w') as f:
            json.dump(content, f)

        # 验证应失败
        manager2 = TokenManager("test-session", data_dir=tmp_path)
        assert manager2.verify_token(token) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_token_manager.py -v`
Expected: FAIL with "No module named 'server.token_manager'"

- [ ] **Step 3: Write minimal implementation**

```python
# server/token_manager.py

import secrets
import base64
import json
import hashlib
import os
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone


def generate_token() -> str:
    """生成 32 字节随机 token (base64 编码)"""
    random_bytes = secrets.token_bytes(32)
    return base64.b64encode(random_bytes).decode('ascii')


class TokenManager:
    """会话 Token 管理器"""

    TOKEN_FILE_MODE = 0o600  # 仅所有者可读写

    def __init__(self, session_name: str, data_dir: Path = None):
        self.session_name = session_name
        self.data_dir = data_dir or Path.home() / ".remote-claude"
        self.token_file = self.data_dir / f"{session_name}_token.json"
        self._token: Optional[str] = None
        self._file_hash: Optional[str] = None

    def get_or_create_token(self) -> str:
        """获取或创建 token"""
        if self._token:
            return self._token

        loaded = self._load_token()
        if loaded:
            self._token = loaded['token']
            return self._token

        # 创建新 token
        self._token = generate_token()
        self._save_token(self._token)
        return self._token

    def regenerate_token(self) -> str:
        """重新生成 token"""
        self._token = generate_token()
        self._save_token(self._token)
        return self._token

    def verify_token(self, token: str) -> bool:
        """验证 token"""
        if not self._token:
            loaded = self._load_token()
            if not loaded:
                return False
            self._token = loaded['token']

        return secrets.compare_digest(self._token, token)

    def _load_token(self) -> Optional[dict]:
        """从文件加载 token"""
        if not self.token_file.exists():
            return None

        try:
            with open(self.token_file, 'r') as f:
                content = f.read()

            data = json.loads(content)

            # 验证文件完整性
            if not self._verify_file_integrity(content, data):
                return None

            return data
        except Exception:
            return None

    def _save_token(self, token: str):
        """保存 token 到文件"""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()
        data = {
            "session": self.session_name,
            "token": token,
            "created_at": now,
            "last_used_at": now,
        }

        content = json.dumps(data, indent=2)

        # 计算 hash 并添加
        file_hash = self._compute_file_hash(content)
        data['file_hash'] = file_hash
        content = json.dumps(data, indent=2)

        # 写入文件
        fd = os.open(str(self.token_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, self.TOKEN_FILE_MODE)
        try:
            os.write(fd, content.encode('utf-8'))
        finally:
            os.close(fd)

    def _compute_file_hash(self, content: str) -> str:
        """计算文件内容 hash"""
        return "sha256:" + hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _verify_file_integrity(self, content: str, data: dict) -> bool:
        """验证文件完整性"""
        if 'file_hash' not in data:
            return False

        stored_hash = data['file_hash']
        # 计算不含 file_hash 字段的 hash
        temp_data = {k: v for k, v in data.items() if k != 'file_hash'}
        temp_content = json.dumps(temp_data, indent=2)
        computed_hash = self._compute_file_hash(temp_content)

        return stored_hash == computed_hash
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_token_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/token_manager.py tests/test_token_manager.py
git commit -m "feat(token): 实现会话 Token 管理器

- Token 生成/验证/重新生成
- 文件权限 0600
- 文件完整性 hash 校验

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: 实现 WebSocket Handler

**Files:**
- Create: `server/ws_handler.py`
- Create: `tests/test_ws_handler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ws_handler.py

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch
from server.ws_handler import WebSocketHandler, parse_url_params

class TestWebSocketHandler:
    """WebSocket 处理器测试"""

    def test_parse_url_params_valid(self):
        """测试解析有效 URL 参数"""
        session, token = parse_url_params("/ws?session=mywork&token=abc123")
        assert session == "mywork"
        assert token == "abc123"

    def test_parse_url_params_missing_token(self):
        """测试缺少 token 参数"""
        session, token = parse_url_params("/ws?session=mywork")
        assert session == "mywork"
        assert token is None

    def test_parse_url_params_missing_session(self):
        """测试缺少 session 参数"""
        session, token = parse_url_params("/ws?token=abc123")
        assert session is None
        assert token == "abc123"

    @pytest.mark.asyncio
    async def test_authenticate_valid_token(self, tmp_path):
        """测试有效 token 认证"""
        mock_server = Mock()
        mock_server.session_name = "test-session"

        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)
        # 先创建 token
        handler.token_manager.get_or_create_token()
        token = handler.token_manager._token

        result = handler._authenticate(token)
        assert result is True

    @pytest.mark.asyncio
    async def test_authenticate_invalid_token(self, tmp_path):
        """测试无效 token 认证"""
        mock_server = Mock()
        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)
        handler.token_manager.get_or_create_token()

        result = handler._authenticate("wrong-token")
        assert result is False

    @pytest.mark.asyncio
    async def test_max_connections_limit(self, tmp_path):
        """测试最大连接数限制"""
        mock_server = Mock()
        handler = WebSocketHandler(mock_server, "test-session", data_dir=tmp_path)

        # 添加最大数量的连接
        for i in range(handler.MAX_WS_CONNECTIONS):
            mock_ws = Mock()
            handler.ws_connections.add(mock_ws)

        # 尝试添加第 11 个连接应该被拒绝
        assert len(handler.ws_connections) == handler.MAX_WS_CONNECTIONS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_ws_handler.py -v`
Expected: FAIL with "No module named 'server.ws_handler'"

- [ ] **Step 3: Write minimal implementation**

```python
# server/ws_handler.py

import asyncio
import logging
from typing import Set, Tuple, Optional
from urllib.parse import urlparse, parse_qs
from pathlib import Path

import websockets
from websockets.server import WebSocketServerProtocol

from utils.protocol import (
    Message, MessageType, InputMessage, ResizeMessage,
    OutputMessage, ErrorMessage, ControlMessage, ControlResponseMessage,
    encode_message, decode_message
)
from server.token_manager import TokenManager

logger = logging.getLogger('WSHandler')


def parse_url_params(path: str) -> Tuple[Optional[str], Optional[str]]:
    """解析 URL 参数"""
    parsed = urlparse(path)
    params = parse_qs(parsed.query)

    session = params.get('session', [None])[0]
    token = params.get('token', [None])[0]

    return session, token


class WebSocketHandler:
    """WebSocket 连接处理器"""

    MAX_WS_CONNECTIONS = 10

    def __init__(self, server, session_name: str, data_dir: Path = None):
        self.server = server
        self.session_name = session_name
        self.token_manager = TokenManager(session_name, data_dir)
        self.ws_connections: Set[WebSocketServerProtocol] = set()

    async def handle_connection(self, websocket: WebSocketServerProtocol, path: str):
        """处理 WebSocket 连接"""
        # 1. 解析 URL 参数
        session, token = parse_url_params(path)

        if session != self.session_name:
            await self._send_error(websocket, "SESSION_NOT_FOUND", f"会话 {session} 不存在")
            return

        # 2. 验证 token
        if not self._authenticate(token):
            await self._send_error(websocket, "INVALID_TOKEN", "认证失败，请检查 token")
            return

        # 3. 检查连接数限制
        if len(self.ws_connections) >= self.MAX_WS_CONNECTIONS:
            await self._send_error(websocket, "TOO_MANY_CONNECTIONS", "连接数已达上限")
            return

        # 4. 加入连接集合
        self.ws_connections.add(websocket)
        client_id = f"ws-{id(websocket)}"
        logger.info(f"WebSocket 客户端连接: {client_id}, 当前连接数: {len(self.ws_connections)}")

        try:
            # 5. 发送历史输出（如果有）
            if hasattr(self.server, 'history_buffer') and self.server.history_buffer:
                history_msg = OutputMessage(self.server.history_buffer)
                await websocket.send(encode_message(history_msg))

            # 6. 消息处理循环
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
        """验证 token"""
        if not token:
            return False
        return self.token_manager.verify_token(token)

    async def _handle_message(self, websocket: WebSocketServerProtocol, msg: Message, client_id: str):
        """处理消息"""
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
        """处理控制命令"""
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
        """广播输出到所有 WebSocket 客户端"""
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

    async def _safe_send(self, websocket: WebSocketServerProtocol, data: bytes):
        """安全发送消息"""
        try:
            await websocket.send(data)
        except Exception:
            self.ws_connections.discard(websocket)

    async def _send_error(self, websocket: WebSocketServerProtocol, code: str, message: str):
        """发送错误消息"""
        msg = ErrorMessage(message, code)
        await websocket.send(encode_message(msg))
        await websocket.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_ws_handler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/ws_handler.py tests/test_ws_handler.py
git commit -m "feat(ws): 实现 WebSocket 处理器

- URL 参数解析
- Token 认证
- 消息转发
- 连接数限制
- 控制命令处理框架

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: 扩展 Server 支持 WebSocket

**Files:**
- Modify: `server/server.py`
- Create: `tests/test_server_ws.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_ws.py

import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock

class TestServerWebSocketIntegration:
    """Server WebSocket 集成测试"""

    @pytest.mark.asyncio
    async def test_server_enable_remote_flag(self):
        """测试 enable_remote 标志"""
        # 这个测试验证 server 能正确初始化 WebSocket 相关参数
        from server.server import ProxyServer

        # Mock 必要的依赖
        with patch('server.server.ensure_socket_dir'), \
             patch('server.server.get_socket_path') as mock_socket_path:
            mock_socket_path.return_value = '/tmp/test.sock'

            server = ProxyServer(
                session_name="test-session",
                enable_remote=True,
                remote_host="0.0.0.0",
                remote_port=8765
            )

            assert server.enable_remote is True
            assert server.remote_host == "0.0.0.0"
            assert server.remote_port == 8765

    @pytest.mark.asyncio
    async def test_server_ws_handler_lazy_init(self):
        """测试 ws_handler 延迟初始化"""
        from server.server import ProxyServer

        with patch('server.server.ensure_socket_dir'), \
             patch('server.server.get_socket_path') as mock_socket_path:
            mock_socket_path.return_value = '/tmp/test.sock'

            server = ProxyServer(
                session_name="test-session",
                enable_remote=False  # 不启用远程
            )

            assert server.ws_handler is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_server_ws.py -v`
Expected: FAIL (可能因为 ProxyServer 构造函数参数不存在)

- [ ] **Step 3: Modify server.py to add WebSocket support**

阅读现有 server.py 找到 ProxyServer 类的 `__init__` 方法，添加以下参数和属性：

```python
# 在 __init__ 参数中添加:
def __init__(self, ..., enable_remote: bool = False,
             remote_host: str = "0.0.0.0",
             remote_port: int = 8765):

    # ... 现有初始化 ...

    # 新增: WebSocket 相关
    self.enable_remote = enable_remote
    self.remote_host = remote_host
    self.remote_port = remote_port
    self.ws_handler: Optional['WebSocketHandler'] = None
```

修改 `run()` 或 `start()` 方法，在启动时检查是否需要启动 WebSocket Server：

```python
# 在主循环开始前:
if self.enable_remote:
    import websockets
    from server.ws_handler import WebSocketHandler

    self.ws_handler = WebSocketHandler(self, self.session_name)

    # 输出 token
    token = self.ws_handler.token_manager.get_or_create_token()
    print(f"\nRemote token: {token}")
    print(f"WebSocket: ws://{self.remote_host}:{self.remote_port}/ws?session={self.session_name}&token={token}\n")

    # 启动 WebSocket Server (在后台任务中)
    asyncio.create_task(self._run_websocket_server())
```

添加 WebSocket Server 运行方法：

```python
async def _run_websocket_server(self):
    """运行 WebSocket Server"""
    import websockets

    async with websockets.serve(
        self.ws_handler.handle_connection,
        self.remote_host,
        self.remote_port,
        ping_interval=30,
        ping_timeout=60,
    ):
        # 等待关闭信号
        await self._shutdown_event.wait()
```

修改 `_broadcast()` 方法：

```python
async def _broadcast(self, data: bytes):
    """广播到所有客户端"""
    # 现有: Unix Socket 客户端
    for writer in self.clients.values():
        try:
            writer.write(encode_message(OutputMessage(data)))
            await writer.drain()
        except Exception:
            pass

    # 新增: WebSocket 客户端
    if self.ws_handler:
        await self.ws_handler.broadcast_to_ws(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_server_ws.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/server.py tests/test_server_ws.py
git commit -m "feat(server): 集成 WebSocket 支持

- 新增 enable_remote/remote_host/remote_port 参数
- 启动时输出 token
- 广播输出同时发送到 Unix Socket 和 WebSocket

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: 实现 HTTP Client

**Files:**
- Create: `client/http_client.py`
- Create: `tests/test_http_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_http_client.py

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch
from client.http_client import HTTPClient, build_ws_url

class TestHTTPClient:
    """HTTP Client 测试"""

    def test_build_ws_url_full(self):
        """测试构建 WebSocket URL - 完整参数"""
        url = build_ws_url("192.168.1.100", 8765, "mywork", "abc123")
        assert url == "ws://192.168.1.100:8765/ws?session=mywork&token=abc123"

    def test_build_ws_url_default_port(self):
        """测试构建 WebSocket URL - 默认端口"""
        url = build_ws_url("192.168.1.100", None, "mywork", "abc123")
        assert url == "ws://192.168.1.100:8765/ws?session=mywork&token=abc123"

    @pytest.mark.asyncio
    async def test_client_initialization(self):
        """测试客户端初始化"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)
        assert client.host == "192.168.1.100"
        assert client.session == "mywork"
        assert client.token == "abc123"
        assert client.port == 8765

    @pytest.mark.asyncio
    async def test_send_control(self):
        """测试发送控制命令"""
        client = HTTPClient("192.168.1.100", "mywork", "abc123", 8765)

        # Mock WebSocket 连接
        with patch('websockets.connect') as mock_connect:
            mock_ws = AsyncMock()
            mock_ws.__aiter__ = Mock(return_value=iter([]))
            mock_ws.send = AsyncMock()
            mock_ws.recv = AsyncMock(return_value='{"type":"control_response","success":true,"message":"OK"}')
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_ws)

            result = await client.send_control("shutdown")
            assert result['success'] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_http_client.py -v`
Expected: FAIL with "No module named 'client.http_client'"

- [ ] **Step 3: Write minimal implementation**

```python
# client/http_client.py

import asyncio
import sys
import tty
import termios
import signal
import select
import os
from typing import Optional
from urllib.parse import urlencode

import websockets

from utils.protocol import (
    Message, MessageType, InputMessage, ResizeMessage,
    ControlMessage, encode_message, decode_message
)
from utils.session import get_terminal_size, generate_client_id


def build_ws_url(host: str, port: Optional[int], session: str, token: str) -> str:
    """构建 WebSocket URL"""
    port = port or 8765
    params = urlencode({"session": session, "token": token})
    return f"ws://{host}:{port}/ws?{params}"


class HTTPClient:
    """HTTP/WebSocket 客户端"""

    def __init__(self, host: str, session: str, token: str, port: int = 8765):
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
        """连接到 Server"""
        try:
            url = self._get_ws_url()
            self.ws = await websockets.connect(
                url,
                ping_interval=30,
                ping_timeout=60,
            )
            return True
        except Exception as e:
            print(f"连接失败: {e}")
            return False

    async def run(self) -> int:
        """运行客户端"""
        if not await self.connect():
            return 1

        self.running = True

        # 设置终端 raw mode
        self._setup_terminal()

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

    async def _read_stdin(self):
        """读取本地输入"""
        loop = asyncio.get_event_loop()

        while self.running:
            try:
                data = await loop.run_in_executor(None, self._read_stdin_sync)
                if data:
                    if data == b'\x04':  # Ctrl+D
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
            except Exception as e:
                break

    async def _handle_message(self, msg: Message):
        """处理消息"""
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
        """发送输入"""
        if self.ws and self.running:
            msg = InputMessage(data, self.client_id)
            await self.ws.send(encode_message(msg))

    async def _send_resize(self, rows: int, cols: int):
        """发送终端大小"""
        if self.ws and self.running:
            msg = ResizeMessage(rows, cols, self.client_id)
            await self.ws.send(encode_message(msg))

    async def send_control(self, action: str) -> dict:
        """发送控制命令"""
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

    def _setup_terminal(self):
        """设置终端 raw mode"""
        if sys.stdin.isatty():
            self.old_settings = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin.fileno())

    def _restore_terminal(self):
        """恢复终端设置"""
        if self.old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)

    def _on_disconnect(self, reason: str):
        """断线回调"""
        print(f"\n{reason}")

    def _cleanup(self):
        """清理"""
        self.running = False
        self._restore_terminal()

        if self.ws:
            asyncio.create_task(self.ws.close())


def run_http_client(host: str, session: str, token: str, port: int = 8765) -> int:
    """运行 HTTP 客户端"""
    client = HTTPClient(host, session, token, port)
    try:
        return asyncio.run(client.run())
    except KeyboardInterrupt:
        return 130
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_http_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add client/http_client.py tests/test_http_client.py
git commit -m "feat(client): 实现 HTTP/WebSocket 客户端

- WebSocket 连接和认证
- 终端 raw mode 处理
- 输入转发和输出显示
- 控制命令发送

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: 扩展 CLI 子命令

**Files:**
- Modify: `remote_claude.py`

- [ ] **Step 1: 添加 --remote 参数到 start 命令**

找到 `cmd_start` 函数，添加以下参数：

```python
# 在 argparse 配置中添加:
parser.add_argument("--remote", action="store_true",
                    help="启用远程连接模式")
parser.add_argument("--remote-port", type=int, default=8765,
                    help="远程连接端口 (默认: 8765)")
parser.add_argument("--remote-host", default="0.0.0.0",
                    help="远程连接监听地址 (默认: 0.0.0.0)")
```

修改 server 命令构建，传递远程参数：

```python
# 在构建 server_cmd 时:
if args.remote:
    server_cmd += f" --remote --remote-port {args.remote_port} --remote-host {args.remote_host}"
```

- [ ] **Step 2: 添加 connect 子命令**

```python
def cmd_connect(args):
    """连接到远程会话"""
    from client.http_client import run_http_client

    # 解析 host/session/port
    host = args.host
    session = args.session
    port = args.port or 8765
    token = args.token

    # 支持 host:port/session 格式
    if '/' in host:
        parts = host.split('/')
        host_part = parts[0]
        session = parts[1] if len(parts) > 1 else session
        if ':' in host_part:
            host, port_str = host_part.split(':')
            port = int(port_str)

    return run_http_client(host, session, token, port)


# 在 main() 中添加子命令:
subparsers = parser.add_subparsers(dest="command")

# connect 子命令
connect_parser = subparsers.add_parser("connect", help="连接到远程会话")
connect_parser.add_argument("host", help="服务器地址 (或 host:port/session)")
connect_parser.add_argument("session", nargs="?", help="会话名称")
connect_parser.add_argument("--token", required=True, help="认证 token")
connect_parser.add_argument("--port", type=int, help="端口 (默认: 8765)")
connect_parser.set_defaults(func=cmd_connect)
```

- [ ] **Step 3: 添加 remote 子命令组**

```python
def cmd_remote(args):
    """远程控制命令"""
    from client.http_client import HTTPClient
    import asyncio

    host = args.host
    session = args.session
    token = args.token
    port = args.port or 8765

    # 解析 host:port/session 格式
    if '/' in host:
        parts = host.split('/')
        host_part = parts[0]
        session = parts[1] if len(parts) > 1 else session
        if ':' in host_part:
            host, port_str = host_part.split(':')
            port = int(port_str)

    client = HTTPClient(host, session, token, port)

    async def run_action():
        result = await client.send_control(args.action)
        if result['success']:
            print(f"✓ {result['message']}")
            return 0
        else:
            print(f"✗ {result['message']}")
            return 1

    return asyncio.run(run_action())


# remote 子命令
remote_parser = subparsers.add_parser("remote", help="远程控制")
remote_parser.add_argument("action", choices=["shutdown", "restart", "update"],
                           help="控制命令")
remote_parser.add_argument("host", help="服务器地址")
remote_parser.add_argument("session", nargs="?", help="会话名称")
remote_parser.add_argument("--token", required=True, help="认证 token")
remote_parser.add_argument("--port", type=int, help="端口")
remote_parser.set_defaults(func=cmd_remote)
```

- [ ] **Step 4: 添加 token 管理子命令**

```python
def cmd_token(args):
    """显示会话 token"""
    from server.token_manager import TokenManager
    from utils.session import USER_DATA_DIR

    manager = TokenManager(args.session, USER_DATA_DIR)
    token = manager.get_or_create_token()
    print(f"Session: {args.session}")
    print(f"Token: {token}")
    return 0


def cmd_regenerate_token(args):
    """重新生成 token"""
    from server.token_manager import TokenManager
    from utils.session import USER_DATA_DIR

    manager = TokenManager(args.session, USER_DATA_DIR)
    old_token = manager._token
    new_token = manager.regenerate_token()
    print(f"Session: {args.session}")
    print(f"旧 Token 已失效")
    print(f"新 Token: {new_token}")
    return 0


# token 子命令
token_parser = subparsers.add_parser("token", help="显示会话 token")
token_parser.add_argument("session", help="会话名称")
token_parser.set_defaults(func=cmd_token)

# regenerate-token 子命令
regen_parser = subparsers.add_parser("regenerate-token", help="重新生成 token")
regen_parser.add_argument("session", help="会话名称")
regen_parser.set_defaults(func=cmd_regenerate_token)
```

- [ ] **Step 5: 验证 CLI**

Run: `uv run python remote_claude.py --help`
Expected: 显示包含 connect/remote/token 子命令的帮助

Run: `uv run python remote_claude.py start --help`
Expected: 显示包含 --remote/--remote-port/--remote-host 参数的帮助

- [ ] **Step 6: Commit**

```bash
git add remote_claude.py
git commit -m "feat(cli): 添加远程连接相关子命令

- start --remote 启用远程模式
- connect 连接远程会话
- remote shutdown/restart/update 远程控制
- token/regenerate-token token 管理

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 8: 更新 CLAUDE.md 文档

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 更新文件结构说明**

在文件结构部分添加新文件：

```markdown
├── server/
│   ├── server.py          # PTY 代理服务器（扩展 WebSocket 支持）
│   ├── ws_handler.py      # WebSocket 处理器
│   └── token_manager.py   # Token 管理
│
├── client/
│   ├── client.py          # Unix Socket 客户端
│   └── http_client.py     # HTTP/WebSocket 客户端
```

- [ ] **Step 2: 添加远程连接命令说明**

在常用命令部分添加：

```markdown
## 远程连接

### 启动远程会话
remote-claude start <session> --remote [--remote-port 8765]

### 连接远程会话
remote-claude connect <host> <session> --token <token>

### 远程控制
remote-claude remote shutdown <host> <session> --token <token>
remote-claude remote restart <host> <session> --token <token>

### Token 管理
remote-claude token <session>
remote-claude regenerate-token <session>
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 更新远程连接文档

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## 完成标准

实现完成后，以下功能应可用：

1. **Server 端**:
   - `remote-claude start mywork --remote` 启动会话并输出 token
   - WebSocket Server 监听 8765 端口
   - 同时支持 Unix Socket 和 WebSocket 客户端

2. **Client 端**:
   - `remote-claude connect 192.168.1.100 mywork --token xxx` 远程连接
   - 输入/输出正常工作
   - Ctrl+D 正常断开

3. **远程控制**:
   - `remote-claude remote shutdown ...` 远程关闭
   - `remote-claude remote restart ...` 远程重启（框架已建，待实现）

4. **Token 管理**:
   - `remote-claude token mywork` 显示 token
   - `remote-claude regenerate-token mywork` 重新生成
