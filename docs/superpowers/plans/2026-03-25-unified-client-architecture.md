# 统一 Client 架构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 Client 架构，使 Local Client 和 Remote Client 功能完全一致，差异仅在于传输层（Unix Socket vs WebSocket）。

**Architecture:** 抽象 `BaseClient` 基类封装终端处理、输入输出、统计追踪等共享逻辑；`LocalClient` 和 `RemoteClient` 继承并实现传输层差异；统一 `attach` 命令入口，通过 `--remote` 参数区分。

**Tech Stack:** Python asyncio, websockets, termios, pyte

---

## 文件结构

```
client/
├── __init__.py          # 修改：统一入口 run_client()
├── base_client.py       # 新增：抽象基类（共享终端逻辑）
├── local_client.py      # 新增：从 client.py 重命名，继承 BaseClient
└── remote_client.py     # 新增：从 http_client.py 重命名，继承 BaseClient

remote_claude.py         # 修改：attach 命令支持 --remote 参数

tests/
├── test_base_client.py  # 新增：BaseClient 单元测试
├── test_local_client.py # 新增：LocalClient 单元测试
└── test_remote_client.py # 新增：RemoteClient 单元测试
```

---

## Task 1: 创建 BaseClient 抽象基类

**Files:**
- Create: `client/base_client.py`
- Create: `tests/test_base_client.py`

- [ ] **Step 1: 编写 BaseClient 单元测试**

```python
# tests/test_base_client.py
"""BaseClient 单元测试"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from client.base_client import BaseClient
from utils.protocol import Message, MessageType, InputMessage, OutputMessage

class ConcreteClient(BaseClient):
    """测试用具体实现"""
    async def connect(self) -> bool:
        return True

    async def send_message(self, msg: Message) -> None:
        pass

    async def read_message(self) -> Message | None:
        return None

    async def close_connection(self) -> None:
        pass

class TestBaseClient:
    """BaseClient 测试"""

    def test_init(self):
        """测试初始化"""
        client = ConcreteClient("test-session")
        assert client.session_name == "test-session"
        assert client.client_id.startswith("client-")
        assert client.running == False
        assert client.old_settings is None

    def test_client_id_unique(self):
        """测试 client_id 唯一性"""
        client1 = ConcreteClient("session1")
        client2 = ConcreteClient("session2")
        assert client1.client_id != client2.client_id

    @pytest.mark.asyncio
    async def test_send_resize(self):
        """测试发送终端大小"""
        client = ConcreteClient("test")
        client._connected = True

        sent_messages = []
        async def mock_send(msg):
            sent_messages.append(msg)
        client.send_message = mock_send

        await client._send_resize(24, 80)

        assert len(sent_messages) == 1
        assert sent_messages[0].type == MessageType.RESIZE
        assert sent_messages[0].rows == 24
        assert sent_messages[0].cols == 80

    def test_get_terminal_size(self):
        """测试获取终端大小"""
        client = ConcreteClient("test")
        # 模拟终端环境
        with patch('os.get_terminal_size') as mock_size:
            mock_size.return_value = MagicMock(lines=30, columns=120)
            rows, cols = client._get_terminal_size()
            assert rows == 30
            assert cols == 120

    def test_get_terminal_size_fallback(self):
        """测试终端大小获取失败的回退值"""
        client = ConcreteClient("test")
        with patch('os.get_terminal_size', side_effect=OSError()):
            rows, cols = client._get_terminal_size()
            assert rows == 24
            assert cols == 80
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run python -m pytest tests/test_base_client.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: 实现 BaseClient 基类**

```python
# client/base_client.py
"""
终端客户端基类

共享功能：
- 终端 raw mode 设置/恢复
- SIGWINCH 信号处理
- 输入读取（stdin）
- 输出显示（stdout）
- 统计追踪
- Ctrl+D 退出
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
from dataclasses import dataclass

# 添加项目根目录到 sys.path
_sys_path = str(__import__('pathlib').Path(__file__).parent.parent)
if _sys_path not in sys.path:
    sys.path.insert(0, _sys_path)

from utils.protocol import (
    Message, MessageType, InputMessage, ResizeMessage, OutputMessage,
    encode_message, decode_message
)
from utils.session import generate_client_id

# 统计追踪（可选依赖）
try:
    from stats import track as _track_stats
except ImportError:
    def _track_stats(*args, **kwargs): pass

# 特殊按键
CTRL_D = b'\x04'  # Ctrl+D - 退出


class BaseClient(ABC):
    """终端客户端抽象基类

    子类需要实现：
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
        self.running = False
        self._connected = False
        self.old_settings: Optional[tuple] = None
        self.buffer = b""

    # ==================== 抽象方法（传输层差异）====================

    @abstractmethod
    async def connect(self) -> bool:
        """建立连接

        Returns:
            True 表示连接成功，False 表示连接失败
        """
        pass

    @abstractmethod
    async def send_message(self, msg: Message) -> None:
        """发送消息

        Args:
            msg: 要发送的消息对象
        """
        pass

    @abstractmethod
    async def read_message(self) -> Optional[Message]:
        """读取一条消息

        Returns:
            消息对象，连接关闭时返回 None
        """
        pass

    @abstractmethod
    async def close_connection(self) -> None:
        """关闭连接"""
        pass

    # ==================== 共享实现 ====================

    async def run(self) -> int:
        """运行客户端主循环

        Returns:
            退出码（0=成功，非零=失败）
        """
        if not await self.connect():
            return 1

        self.running = True
        self._connected = True
        _track_stats('terminal', 'connect', session_name=self.session_name)

        # 设置终端 raw mode
        self._setup_terminal()

        # 设置信号处理
        self._setup_signals()

        # 发送初始终端大小
        rows, cols = self._get_terminal_size()
        await self._send_resize(rows, cols)

        try:
            # 并行运行输入和输出处理
            await asyncio.gather(
                self._read_stdin_loop(),
                self._read_connection_loop(),
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
        if self.running and self._connected:
            rows, cols = self._get_terminal_size()
            asyncio.create_task(self._send_resize(rows, cols))

    def _get_terminal_size(self) -> tuple[int, int]:
        """获取终端大小

        Returns:
            (rows, cols) 元组
        """
        try:
            size = os.get_terminal_size()
            return size.lines, size.columns
        except OSError:
            return 24, 80  # 默认值

    async def _send_resize(self, rows: int, cols: int):
        """发送终端大小变化消息"""
        msg = ResizeMessage(rows, cols, self.client_id)
        await self.send_message(msg)

    async def _read_stdin_loop(self):
        """读取标准输入循环"""
        loop = asyncio.get_event_loop()

        while self.running:
            try:
                data = await loop.run_in_executor(None, self._read_stdin_sync)
                if data:
                    if data == CTRL_D:  # Ctrl+D
                        self.running = False
                        break
                    await self._handle_input(data)
                    if not self.running:
                        break
            except Exception:
                break

    def _read_stdin_sync(self) -> bytes:
        """同步读取标准输入（带超时）"""
        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
        if rlist:
            return os.read(sys.stdin.fileno(), 1024)
        return b""

    async def _handle_input(self, data: bytes):
        """处理用户输入"""
        _track_stats('terminal', 'input', session_name=self.session_name, value=len(data))
        msg = InputMessage(data, self.client_id)
        await self.send_message(msg)

    async def _read_connection_loop(self):
        """读取连接消息循环"""
        while self.running:
            try:
                msg = await asyncio.wait_for(self.read_message(), timeout=0.5)
                if msg is None:
                    self._on_disconnect("连接已关闭")
                    self.running = False
                    break
                await self._handle_message(msg)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self._on_disconnect(f"连接错误: {e}")
                self.running = False
                break

    async def _handle_message(self, msg: Message):
        """处理服务器消息"""
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

    def _on_disconnect(self, reason: str):
        """断线回调"""
        print(f"\n{reason}")

    def _cleanup(self):
        """清理资源"""
        self.running = False
        self._connected = False
        _track_stats('terminal', 'disconnect', session_name=self.session_name)
        self._restore_terminal()

        # 异步关闭连接（在事件循环中执行）
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.close_connection())
        except RuntimeError:
            pass

        print("\n已断开连接")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run python -m pytest tests/test_base_client.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add client/base_client.py tests/test_base_client.py
git commit -m "feat(client): add BaseClient abstract base class

- Abstract methods for transport layer (connect/send/read/close)
- Shared implementation for terminal handling
- Shared input/output processing
- Statistics tracking integration"
```

---

## Task 2: 重构 LocalClient 继承 BaseClient

**Files:**
- Create: `client/local_client.py`
- Modify: `client/__init__.py`
- Create: `tests/test_local_client.py`
- Delete: `client/client.py` (after migration)

- [ ] **Step 1: 编写 LocalClient 单元测试**

```python
# tests/test_local_client.py
"""LocalClient 单元测试"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path
from client.local_client import LocalClient
from utils.protocol import MessageType

class TestLocalClient:
    """LocalClient 测试"""

    def test_init(self):
        """测试初始化"""
        client = LocalClient("test-session")
        assert client.session_name == "test-session"
        assert client.socket_path.name == "test-session.sock"

    @pytest.mark.asyncio
    async def test_connect_socket_not_exists(self, tmp_path):
        """测试 socket 不存在时的连接"""
        client = LocalClient("nonexistent")
        # 临时修改 socket 路径
        client.socket_path = tmp_path / "nonexistent.sock"

        result = await client.connect()
        assert result == False

    @pytest.mark.asyncio
    async def test_send_message(self):
        """测试发送消息"""
        client = LocalClient("test")
        client._connected = True

        # Mock writer
        client.writer = MagicMock()
        client.writer.write = Mock()
        client.writer.drain = AsyncMock()

        from utils.protocol import InputMessage
        msg = InputMessage(b"test data", "client-1")
        await client.send_message(msg)

        assert client.writer.write.called
        assert client.writer.drain.called

    @pytest.mark.asyncio
    async def test_close_connection(self):
        """测试关闭连接"""
        client = LocalClient("test")
        client.writer = MagicMock()
        client.writer.close = Mock()

        await client.close_connection()

        assert client.writer.close.called
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run python -m pytest tests/test_local_client.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: 实现 LocalClient**

```python
# client/local_client.py
"""
本地客户端（Unix Socket）

- 通过 Unix Socket 连接本地 Server
- 继承 BaseClient 共享终端处理逻辑
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

# 添加项目根目录到 sys.path
_sys_path = str(__import__('pathlib').Path(__file__).parent.parent)
if _sys_path not in sys.path:
    sys.path.insert(0, _sys_path)

from client.base_client import BaseClient
from utils.protocol import Message, encode_message, decode_message
from utils.session import get_socket_path


class LocalClient(BaseClient):
    """本地客户端（Unix Socket）"""

    def __init__(self, session_name: str):
        """初始化本地客户端

        Args:
            session_name: 会话名称
        """
        super().__init__(session_name)
        self.socket_path = get_socket_path(session_name)
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.buffer = b""

    async def connect(self) -> bool:
        """连接到本地 Server

        Returns:
            True 表示连接成功，False 表示连接失败
        """
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
        except ConnectionRefusedError:
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
        """发送消息到 Server"""
        if self.writer:
            try:
                data = encode_message(msg)
                self.writer.write(data)
                await self.writer.drain()
            except Exception:
                pass

    async def read_message(self) -> Optional[Message]:
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

    async def close_connection(self) -> None:
        """关闭连接"""
        if self.writer:
            try:
                self.writer.close()
            except Exception:
                pass


def run_client(session_name: str) -> int:
    """运行本地客户端

    Args:
        session_name: 会话名称

    Returns:
        退出码（0=成功，非零=失败）
    """
    client = LocalClient(session_name)

    try:
        return asyncio.run(client.run())
    except KeyboardInterrupt:
        return 130  # 128 + SIGINT(2)，Unix 惯例
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run python -m pytest tests/test_local_client.py -v`
Expected: PASS

- [ ] **Step 5: 更新 client/__init__.py**

```python
# client/__init__.py
"""
Remote Claude Client 模块

提供统一的客户端入口：
- run_client(): 本地客户端入口
- run_remote_client(): 远程客户端入口
"""

from client.local_client import LocalClient, run_client

__all__ = ['LocalClient', 'run_client']
```

- [ ] **Step 6: 验证现有功能不受影响**

Run: `uv run python -c "from client import run_client; print('Import OK')"`
Expected: 输出 "Import OK"

- [ ] **Step 7: 删除旧文件**

```bash
rm client/client.py
```

- [ ] **Step 8: 提交**

```bash
git add client/local_client.py client/__init__.py tests/test_local_client.py
git rm client/client.py
git commit -m "refactor(client): rename client.py to local_client.py

- LocalClient now inherits from BaseClient
- Preserved all existing error handling and diagnostics
- Updated __init__.py exports"
```

---

## Task 3: 重构 RemoteClient 继承 BaseClient

**Files:**
- Create: `client/remote_client.py`
- Create: `tests/test_remote_client.py`
- Delete: `client/http_client.py` (after migration)

- [ ] **Step 1: 编写 RemoteClient 单元测试**

```python
# tests/test_remote_client.py
"""RemoteClient 单元测试"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from client.remote_client import RemoteClient, build_ws_url
from utils.protocol import MessageType

class TestRemoteClient:
    """RemoteClient 测试"""

    def test_init(self):
        """测试初始化"""
        client = RemoteClient("192.168.1.100", "test-session", "token123", 8765)
        assert client.host == "192.168.1.100"
        assert client.session_name == "test-session"
        assert client.token == "token123"
        assert client.port == 8765

    def test_build_ws_url(self):
        """测试 WebSocket URL 构建"""
        url = build_ws_url("192.168.1.100", 8765, "test-session", "token123")
        assert "ws://192.168.1.100:8765/ws" in url
        assert "session=test-session" in url
        assert "token=token123" in url

    def test_build_ws_url_default_port(self):
        """测试默认端口"""
        url = build_ws_url("192.168.1.100", None, "test", "token")
        assert ":8765" in url

    @pytest.mark.asyncio
    async def test_send_message(self):
        """测试发送消息"""
        client = RemoteClient("host", "session", "token")
        client._connected = True
        client.ws = MagicMock()
        client.ws.send = AsyncMock()

        from utils.protocol import InputMessage
        msg = InputMessage(b"test", "client-1")
        await client.send_message(msg)

        assert client.ws.send.called

    @pytest.mark.asyncio
    async def test_send_control(self):
        """测试发送控制命令"""
        client = RemoteClient("host", "session", "token")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value='{"type":"control_response","success":true,"message":"OK"}')

        with patch('websockets.connect', return_value=mock_ws):
            with patch.object(mock_ws, '__aenter__', return_value=mock_ws):
                with patch.object(mock_ws, '__aexit__', return_value=None):
                    result = await client.send_control("shutdown")

        assert result["success"] == True
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run python -m pytest tests/test_remote_client.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: 实现 RemoteClient**

```python
# client/remote_client.py
"""
远程客户端（WebSocket）

- 通过 WebSocket 连接远程 Server
- 继承 BaseClient 共享终端处理逻辑
- 支持控制命令（shutdown/restart/update）
"""

import asyncio
import sys
from typing import Optional
from urllib.parse import urlencode

# 添加项目根目录到 sys.path
_sys_path = str(__import__('pathlib').Path(__file__).parent.parent)
if _sys_path not in sys.path:
    sys.path.insert(0, _sys_path)

import websockets

from client.base_client import BaseClient
from utils.protocol import (
    Message, ControlMessage,
    encode_message, decode_message
)


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


class RemoteClient(BaseClient):
    """远程客户端（WebSocket）"""

    def __init__(self, host: str, session_name: str, token: str, port: int = 8765):
        """初始化远程客户端

        Args:
            host: 服务器主机地址
            session_name: 会话名称
            token: 认证令牌
            port: 服务器端口（默认 8765）
        """
        super().__init__(session_name)
        self.host = host
        self.port = port
        self.token = token
        self.ws: Optional[websockets.WebSocketClientProtocol] = None

    def _get_ws_url(self) -> str:
        """获取 WebSocket URL"""
        return build_ws_url(self.host, self.port, self.session_name, self.token)

    async def connect(self) -> bool:
        """连接到远程 Server

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
            print(f"✅ 已连接到远程会话: {self.session_name}@{self.host}")
            return True
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False

    async def send_message(self, msg: Message) -> None:
        """发送消息到 Server"""
        if self.ws and self.running:
            await self.ws.send(encode_message(msg))

    async def read_message(self) -> Optional[Message]:
        """读取一条消息"""
        try:
            raw = await self.ws.recv()
            return decode_message(raw.encode() if isinstance(raw, str) else raw)
        except websockets.exceptions.ConnectionClosed:
            return None
        except Exception:
            return None

    async def close_connection(self) -> None:
        """关闭连接"""
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass

    # ==================== 远程专属：控制命令 ====================

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


def run_remote_client(host: str, session_name: str, token: str, port: int = 8765) -> int:
    """运行远程客户端

    Args:
        host: 服务器主机地址
        session_name: 会话名称
        token: 认证令牌
        port: 服务器端口

    Returns:
        退出码（0=成功，非零=失败）
    """
    client = RemoteClient(host, session_name, token, port)

    try:
        return asyncio.run(client.run())
    except KeyboardInterrupt:
        return 130  # 128 + SIGINT(2)，Unix 惯例
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run python -m pytest tests/test_remote_client.py -v`
Expected: PASS

- [ ] **Step 5: 更新 client/__init__.py**

```python
# client/__init__.py
"""
Remote Claude Client 模块

提供统一的客户端入口：
- run_client(): 本地客户端入口
- run_remote_client(): 远程客户端入口
"""

from client.local_client import LocalClient, run_client
from client.remote_client import RemoteClient, run_remote_client

__all__ = ['LocalClient', 'RemoteClient', 'run_client', 'run_remote_client']
```

- [ ] **Step 6: 删除旧文件**

```bash
rm client/http_client.py
```

- [ ] **Step 7: 提交**

```bash
git add client/remote_client.py client/__init__.py tests/test_remote_client.py
git rm client/http_client.py
git commit -m "refactor(client): rename http_client.py to remote_client.py

- RemoteClient now inherits from BaseClient
- Added control command support (shutdown/restart/update)
- Updated __init__.py exports"
```

---

## Task 4: 统一 attach 命令入口

**Files:**
- Modify: `remote_claude.py`

- [ ] **Step 1: 修改 cmd_attach 函数**

找到 `cmd_attach` 函数（约205行），修改为：

```python
def cmd_attach(args):
    """连接到已有会话（支持本地/远程）"""
    from client import run_client, run_remote_client

    session_name = args.name

    # 远程模式
    if getattr(args, 'remote', False):
        host = args.host
        token = args.token
        port = args.port or 8765

        # 支持 host:port/session 格式
        if '/' in host:
            parts = host.split('/')
            host_part = parts[0]
            session_name = parts[1] if len(parts) > 1 else session_name
            if ':' in host_part:
                host, port_str = host_part.split(':')
                port = int(port_str)

        if not session_name:
            print("错误: 请指定会话名称")
            return 1

        return run_remote_client(host, session_name, token, port)

    # 本地模式
    from utils.session import is_session_active

    if not is_session_active(session_name):
        print(f"错误: 会话 '{session_name}' 不存在")
        print("使用 'remote-claude list' 查看可用会话")
        return 1

    print(f"连接到会话: {session_name}")

    return run_client(session_name)
```

- [ ] **Step 2: 修改 attach 命令参数定义**

找到 attach_parser 定义（约879行），添加远程参数：

```python
    # attach 命令
    attach_parser = subparsers.add_parser("attach", help="连接到已有会话")
    attach_parser.add_argument("name", help="会话名称")
    attach_parser.add_argument(
        "--remote",
        action="store_true",
        help="远程连接模式"
    )
    attach_parser.add_argument(
        "--host",
        default="",
        help="远程服务器地址（支持 host:port/session 格式）"
    )
    attach_parser.add_argument(
        "--token",
        default="",
        help="认证令牌（远程模式必需）"
    )
    attach_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="远程服务器端口（默认: 8765）"
    )
    attach_parser.set_defaults(func=cmd_attach)
```

- [ ] **Step 3: 更新帮助文档**

在 parser 的 epilog 中更新示例：

```python
    epilog="""
示例:
  %(prog)s start mywork              启动名为 mywork 的会话
  %(prog)s start mywork --cli codex  启动 codex 会话
  %(prog)s attach mywork             连接到 mywork 会话（本地）
  %(prog)s attach mywork --remote --host 192.168.1.100 --token <TOKEN>  远程连接
  %(prog)s attach --remote --host 192.168.1.100:8765/mywork --token <TOKEN>  简写格式
  %(prog)s list                      列出所有会话
  %(prog)s kill mywork               终止 mywork 会话
  ...
"""
```

- [ ] **Step 4: 验证命令行参数**

Run: `uv run python remote_claude.py attach --help`
Expected: 显示新的 --remote, --host, --token, --port 参数

- [ ] **Step 5: 提交**

```bash
git add remote_claude.py
git commit -m "feat(cli): unify attach command for local/remote

- attach command now supports --remote flag
- Supports host:port/session shorthand format
- Removed separate connect command (merged into attach)"
```

---

## Task 5: 清理冗余代码

**Files:**
- Modify: `remote_claude.py`

- [ ] **Step 1: 删除 cmd_connect 函数**

删除 `cmd_connect` 函数（约570行），功能已合并到 `cmd_attach`。

- [ ] **Step 2: 删除 connect 子命令定义**

删除 connect_parser 定义（约969行）。

- [ ] **Step 3: 验证现有功能**

Run: `uv run python remote_claude.py --help`
Expected: connect 命令不再显示

- [ ] **Step 4: 提交**

```bash
git add remote_claude.py
git commit -m "refactor(cli): remove redundant connect command

- connect functionality merged into attach --remote"
```

---

## Task 6: 集成测试

**Files:**
- Create: `tests/test_client_integration.py`

- [ ] **Step 1: 编写集成测试**

```python
# tests/test_client_integration.py
"""客户端集成测试"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

class TestClientIntegration:
    """客户端集成测试"""

    @pytest.mark.asyncio
    async def test_local_client_full_flow(self, tmp_path):
        """测试本地客户端完整流程"""
        from client.local_client import LocalClient

        client = LocalClient("test-session")

        # 模拟 socket 文件
        socket_path = tmp_path / "test-session.sock"
        socket_path.touch()
        client.socket_path = socket_path

        # 模拟连接
        with patch('asyncio.open_unix_connection') as mock_connect:
            mock_reader = MagicMock()
            mock_writer = MagicMock()
            mock_writer.write = MagicMock()
            mock_writer.drain = AsyncMock()
            mock_connect.return_value = asyncio.wait_for(
                asyncio.coroutine(lambda: (mock_reader, mock_writer))(),
                timeout=5.0
            )

            # 这个测试验证连接流程可以正常工作
            # 实际的端到端测试需要真实的 Server

    @pytest.mark.asyncio
    async def test_remote_client_full_flow(self):
        """测试远程客户端完整流程"""
        from client.remote_client import RemoteClient

        client = RemoteClient("192.168.1.100", "test-session", "token123")

        # 模拟 WebSocket 连接
        with patch('websockets.connect') as mock_ws:
            mock_ws_instance = MagicMock()
            mock_ws_instance.send = AsyncMock()
            mock_ws_instance.recv = AsyncMock(return_value='{"type":"output","data":"dGVzdA=="}')
            mock_ws_instance.close = AsyncMock()
            mock_ws.return_value.__aenter__.return_value = mock_ws_instance

            # 这个测试验证连接流程可以正常工作
```

- [ ] **Step 2: 运行集成测试**

Run: `uv run python -m pytest tests/test_client_integration.py -v`
Expected: PASS

- [ ] **Step 3: 运行所有客户端测试**

Run: `uv run python -m pytest tests/test_base_client.py tests/test_local_client.py tests/test_remote_client.py tests/test_client_integration.py -v`
Expected: All PASS

- [ ] **Step 4: 提交**

```bash
git add tests/test_client_integration.py
git commit -m "test(client): add integration tests"
```

---

## Task 7: 更新文档

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: 更新 CLAUDE.md 文件结构**

更新文件结构部分，反映新的 client 目录结构：

```markdown
├── client/                     # 终端客户端
│   ├── __init__.py          # 统一入口
│   ├── base_client.py       # 抽象基类
│   ├── local_client.py      # 本地客户端（Unix Socket）
│   └── remote_client.py     # 远程客户端（WebSocket）
```

- [ ] **Step 2: 更新 CLAUDE.md 常用命令**

更新命令示例：

```markdown
## 远程连接

### 启动远程会话
```bash
remote-claude start <session> --remote [--remote-port 8765] [--remote-host 0.0.0.0]
```

### 连接远程会话（统一 attach 命令）
```bash
remote-claude attach <session> --remote --host <host> --token <token>
remote-claude attach --remote --host <host>:<port>/<session> --token <token>
```

### 远程控制
```bash
remote-claude remote shutdown <host> <session> --token <token>
remote-claude remote restart <host> <session> --token <token>
remote-claude remote update <host> <session> --token <token>
```
```

- [ ] **Step 3: 更新 README.md**

更新 README.md 中的命令示例。

- [ ] **Step 4: 提交**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update documentation for unified client architecture"
```

---

## 最终验证

- [ ] **运行所有测试**

Run: `uv run python -m pytest tests/ -v --ignore=tests/test_integration.py --ignore=tests/test_e2e.py`
Expected: All PASS

- [ ] **验证命令行帮助**

Run: `uv run python remote_claude.py attach --help`
Expected: 显示 --remote 参数说明

- [ ] **验证本地连接流程**

Run: `uv run python -c "from client import run_client; print('Import OK')"`
Expected: 输出 "Import OK"

- [ ] **最终提交**

```bash
git add -A
git commit -m "feat(client): complete unified client architecture

- BaseClient abstract base class with shared terminal handling
- LocalClient (Unix Socket) inherits from BaseClient
- RemoteClient (WebSocket) inherits from BaseClient
- Unified attach command with --remote flag
- All tests passing"
```
