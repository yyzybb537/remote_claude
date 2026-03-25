# Remote Claude 远程连接设计

## 概述

为 Remote Claude 添加远程连接能力，支持从本地电脑启动 client，连接到远端运行 server 的会话。采用 Server 内置 WebSocket 支持方案，在现有 Server 进程中直接添加 WebSocket 监听能力。

## 需求背景

- **场景**：企业内网协作，Server 运行在远程开发机上，本地 client 通过内网连接
- **通信协议**：WebSocket
- **认证方式**：静态 Token（持久化，长期有效，可重新生成）
- **兼容性**：保持现有 Unix Socket 方式，双模式共存

## 架构设计

### 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         远端机器                                 │
│  ┌─────────────┐                                               │
│  │ Claude CLI  │                                               │
│  └──────┬──────┘                                               │
│         │ PTY                                                   │
│  ┌──────▼──────────────────────────────────────────────────┐   │
│  │                    Server (PTY 代理)                     │   │
│  │  ┌─────────────┐     ┌─────────────────────────────┐    │   │
│  │  │ Unix Socket │     │  WebSocket Server (内置)    │    │   │
│  │  │   (本地)    │     │  websockets 库 (认证/转发)   │    │   │
│  │  └──────┬──────┘     └──────────────┬──────────────┘    │   │
│  └─────────┼───────────────────────────┼───────────────────┘   │
│            │                           │                        │
│     本地连接│                  WebSocket│                        │
│            │                           │                        │
└────────────┼───────────────────────────┼────────────────────────┘
             │                           │
      ┌──────▼──────┐           ┌───────▼───────┐
      │ Local Client│           │  HTTP Client  │
      │  (Terminal) │           │  (Terminal)   │
      └─────────────┘           └───────────────┘
           本地                      远程
```

### 组件职责

| 组件 | 职责 | 文件位置 |
|------|------|---------|
| HTTP Client | 远程终端客户端，WebSocket 连接，身份认证，Server 控制 | `client/http_client.py` |
| Server (PTY) | PTY 代理 + 内置 WebSocket Server | `server/server.py` (扩展) |
| WebSocket Handler | 认证、协议转换、连接管理、控制命令处理 | `server/ws_handler.py` (新增) |

### 设计原则

1. **单进程部署**：Server 内置 WebSocket 支持，无需额外 Gateway 进程
2. **协议复用**：复用现有 `utils/protocol.py` 消息格式
3. **双模式共存**：本地 Unix Socket 和远程 WebSocket 同时支持
4. **按需启用**：默认不启动 HTTP 服务，传参 `--remote` 时才启动

## 认证机制

### Token 管理

```
1. Server 启动时（启用远程模式）
   ├─ 生成或加载 token (32 字节，base64 编码)
   ├─ 持久化到 ~/.remote-claude/<session>_token.json
   │  └─ 文件权限: 0600 (仅所有者可读写)
   └─ 输出到终端: "Remote token: xxx"

2. Token 配置文件格式:
   {
     "session": "mywork",
     "token": "dGhpcyBpcyBhIHJhbmRvbSB0b2tlbg==",
     "created_at": "2026-03-25T10:30:00Z",
     "last_used_at": "2026-03-25T11:00:00Z",
     "file_hash": "sha256:abc123..."
   }

   file_hash 计算方式:
   ├─ 对整个 JSON 文件内容计算 SHA-256
   ├─ 在 _save_token() 时计算并写入 file_hash 字段
   └─ 在 _load_token() 时重新计算并验证

3. Token 文件安全措施:
   ├─ 文件权限设置为 0600，防止其他用户读取
   ├─ 每次加载时验证 file_hash，检测非法篡改
   ├─ 若检测到篡改，拒绝远程连接并提示检查
   └─ Token 泄露时应立即重新生成

4. 重新生成 token:
   命令: remote-claude regenerate-token <session>
   效果: 生成新 token 并覆盖配置文件，旧 token 立即失效

5. Client 连接时验证
   ├─ 读取 URL 参数中的 token
   ├─ 与配置文件中的 token 比较
   └─ 匹配则允许连接
```

### URL 格式

```
ws://<host>:<port>/ws?session=<session_name>&token=<token>
```

### Token 生成算法

```python
import secrets
import base64

def generate_token() -> str:
    """生成 32 字节随机 token"""
    random_bytes = secrets.token_bytes(32)
    return base64.b64encode(random_bytes).decode('ascii')
```

## 消息协议

### WebSocket 消息格式

复用现有 `utils/protocol.py` 的消息类型，JSON 格式通过 WebSocket 传输：

```json
// INPUT 消息 (Client → Server)
{"type": "input", "data": "<base64>", "client_id": "<id>"}

// OUTPUT 消息 (Server → Client)
{"type": "output", "data": "<base64>"}

// HISTORY 消息 (Server → Client，重连时)
{"type": "history", "data": "<base64>"}

// RESIZE 消息 (Client → Server)
{"type": "resize", "rows": 24, "cols": 80, "client_id": "<id>"}

// ERROR 消息 (Server → Client)
{"type": "error", "message": "错误描述", "code": "INVALID_TOKEN"}

// CONTROL 消息 (Client → Server，控制命令)
{"type": "control", "action": "shutdown|restart|update", "client_id": "<id>"}

// CONTROL_RESPONSE 消息 (Server → Client)
{"type": "control_response", "success": true, "message": "操作结果"}
```

### 控制命令

| action | 说明 | 权限要求 |
|--------|------|---------|
| shutdown | 关闭 Server 和 Claude 进程 | Token 认证 |
| restart | 重启 Claude 进程（保持会话） | Token 认证 |
| update | 更新 remote-claude 到最新版本 | Token 认证 |

### 数据流

```
┌──────────┐                    ┌──────────────────────┐     ┌──────────┐
│ HTTP     │   WebSocket        │      Server          │     │ Claude   │
│ Client   │                    │  ┌──────┐ ┌───────┐  │     │ (PTY)    │
└────┬─────┘                    │  │ WS   │ │ Unix  │  │     └────┬─────┘
     │                          │  │Handler│ │Socket │  │          │
     │  INPUT (WebSocket)       │  └──┬───┘ └───┬───┘  │          │
     │─────────────────────────>│     │         │      │          │
     │                          │     │ ────────┼─────>│ PTY write│
     │                          │     │         │      │─────────>│
     │                          │     │         │      │          │
     │                          │     │         │ PTY read       │
     │  OUTPUT (WebSocket)      │     │ <───────┼──────│<─────────│
     │<─────────────────────────│     │         │      │          │
     │                          │     │         │      │          │
     │  CONTROL (shutdown)      │     │         │      │          │
     │─────────────────────────>│     │ 关闭 PTY      │          │
     │                          │     │ 退出进程      │          │
```

## Server 扩展设计

### 技术选型

使用 `websockets` 库实现 WebSocket Server：

```
依赖:
  websockets>=12.0  # 支持 async/await，ping/pong 心跳

特点:
  ├─ 纯 Python 实现，轻量级
  ├─ 原生支持 asyncio
  ├─ 内置 ping/pong 心跳机制
  └─ 无需额外 HTTP 框架
```

### 核心功能扩展

在现有 `server/server.py` 中新增：

1. **WebSocket Server**：使用 `websockets` 库监听指定端口
2. **认证中间件**：验证 URL 参数中的 token
3. **WebSocket Handler**：处理远程客户端连接、消息转发
4. **心跳检测**：使用 websockets 内置 ping/pong
5. **控制命令处理**：响应 Client 端的 shutdown/restart/update 请求

### 心跳机制

```
配置参数:
  HEARTBEAT_INTERVAL = 30 秒   // ping 发送间隔
  HEARTBEAT_TIMEOUT = 60 秒    // 无响应超时判定

实现方式 (websockets 库):
  ├─ 使用 websockets.serve() 的 ping_interval, ping_timeout 参数
  ├─ ping_interval=30: 每 30 秒发送 ping
  ├─ ping_timeout=60: 60 秒无 pong 响应则关闭连接
  └─ 自动处理，无需手动实现心跳循环

心跳超时后处理:
  ├─ websockets 自动关闭连接
  ├─ 触发 handler 退出
  └─ 不影响其他客户端和 Unix Socket 连接
```

### 接口定义

```python
# server/ws_handler.py

import websockets
from websockets.server import WebSocketServerProtocol

class WebSocketHandler:
    """WebSocket 连接处理器"""

    MAX_WS_CONNECTIONS = 10  # 最大 WebSocket 连接数

    def __init__(self, server: "ProxyServer", session_name: str):
        self.server = server
        self.session_name = session_name
        self.token_manager = TokenManager(session_name)
        self.ws_connections: Set[WebSocketServerProtocol] = set()

    async def handle_connection(self, websocket: WebSocketServerProtocol, path: str):
        """处理 WebSocket 连接"""
        # 1. 解析 URL 参数，获取 session 和 token
        # 2. 验证 token
        # 3. 加入连接集合
        # 4. 循环处理消息（INPUT/RESIZE/CONTROL）
        # 5. 广播 OUTPUT 到所有连接
        # 6. 处理控制命令

    def _parse_url_params(self, path: str) -> Tuple[str, str]:
        """解析 URL 参数 (session, token)"""

    def _authenticate(self, token: str) -> bool:
        """验证 token"""

    async def broadcast_to_ws(self, message: bytes):
        """广播输出到所有 WebSocket 客户端"""

    async def handle_control(self, action: str) -> dict:
        """处理控制命令（shutdown/restart/update）"""


# server/server.py (扩展)

class ProxyServer:
    """PTY 代理服务器（扩展 WebSocket 支持）"""

    def __init__(self, ..., enable_remote: bool = False,
                 remote_host: str = "0.0.0.0",
                 remote_port: int = 8765):
        # ... 现有初始化 ...
        self.enable_remote = enable_remote
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.ws_handler: Optional[WebSocketHandler] = None

    async def start(self):
        """启动服务"""
        # ... 现有逻辑 ...

        # 新增：启动 WebSocket Server
        if self.enable_remote:
            await self._start_websocket_server()

    async def _start_websocket_server(self):
        """启动 WebSocket Server"""
        import websockets
        self.ws_handler = WebSocketHandler(self, self.session_name)

        async with websockets.serve(
            self.ws_handler.handle_connection,
            self.remote_host,
            self.remote_port,
            ping_interval=30,
            ping_timeout=60,
        ):
            # 保持运行直到 server 关闭
            await self._shutdown_event.wait()

    # 修改 _broadcast() 方法，同时广播到 Unix Socket 和 WebSocket
    async def _broadcast(self, data: bytes):
        """广播到所有客户端（Unix Socket + WebSocket）"""
        # 现有逻辑：广播到 Unix Socket 客户端
        for writer in self.clients.values():
            writer.write(encode_message(OutputMessage(data)))
            await writer.drain()

        # 新增：广播到 WebSocket 客户端
        if self.ws_handler:
            await self.ws_handler.broadcast_to_ws(data)
```

### Token 管理

```python
# server/token_manager.py

class TokenManager:
    """会话 Token 管理器"""

    def __init__(self, session_name: str):
        self.session_name = session_name
        self.token_file = USER_DATA_DIR / f"{session_name}_token.json"
        self._token: Optional[str] = None
        self._file_hash: Optional[str] = None

    TOKEN_FILE_MODE = 0o600  # 仅所有者可读写

    def get_or_create_token(self) -> str:
        """获取或创建 token"""

    def regenerate_token(self) -> str:
        """重新生成 token"""

    def verify_token(self, token: str) -> bool:
        """验证 token"""

    def _load_token(self) -> Optional[dict]:
        """从文件加载 token"""

    def _save_token(self, token: str):
        """保存 token 到文件（权限 0600）"""

    def _compute_file_hash(self, content: str) -> str:
        """计算文件内容 hash"""

    def _verify_file_integrity(self) -> bool:
        """验证文件完整性"""
```

## HTTP Client 设计

### 核心功能

1. **WebSocket 连接**：连接 Server，携带认证信息
2. **终端处理**：raw mode、信号处理、终端大小变化
3. **输入转发**：将用户输入发送到远端
4. **输出显示**：接收远端输出并显示到终端
5. **断线处理**：检测断线，恢复终端状态
6. **Server 控制**：发送控制命令（关闭/更新/重启）

### 接口定义

```python
# client/http_client.py

import websockets

class HTTPClient:
    """HTTP/WebSocket 客户端"""

    def __init__(self, host: str, session: str, token: str, port: int = 8765):
        self.host = host
        self.session = session
        self.token = token
        self.port = port
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        self.old_settings = None  # 终端原始设置

    async def connect(self) -> bool:
        """连接到 Server"""

    async def run(self) -> int:
        """运行客户端"""

    async def _read_stdin(self):
        """读取本地输入"""

    async def _read_websocket(self):
        """读取远端输出"""

    async def _send_input(self, data: bytes):
        """发送输入"""

    async def _send_resize(self, rows: int, cols: int):
        """发送终端大小"""

    async def send_control(self, action: str) -> dict:
        """发送控制命令（shutdown/restart/update）"""

    def _setup_terminal(self):
        """设置终端 raw mode"""

    def _restore_terminal(self):
        """恢复终端设置"""

    def _on_disconnect(self, reason: str):
        """断线回调：显示原因，恢复终端"""


# 便捷函数
async def remote_shutdown(host: str, session: str, token: str, port: int = 8765) -> bool:
    """远程关闭 Server"""
    client = HTTPClient(host, session, token, port)
    result = await client.send_control("shutdown")
    return result.get("success", False)

async def remote_restart(host: str, session: str, token: str, port: int = 8765) -> bool:
    """远程重启 Claude 进程"""
    client = HTTPClient(host, session, token, port)
    result = await client.send_control("restart")
    return result.get("success", False)

async def remote_update(host: str, session: str, token: str, port: int = 8765) -> bool:
    """远程更新 remote-claude"""
    client = HTTPClient(host, session, token, port)
    result = await client.send_control("update")
    return result.get("success", False)
```

## 命令行接口

### Server 启动（扩展）

```bash
# 默认启动（不启用远程模式，行为与现在一致）
remote-claude start <session>

# 启动会话并启用远程模式
remote-claude start <session> --remote [--remote-port 8765] [--remote-host 0.0.0.0]

# 示例
remote-claude start mywork                        # 仅本地
remote-claude start mywork --remote               # 启用远程，默认端口 8765
remote-claude start mywork --remote --remote-port 9000  # 指定端口
```

### Token 管理

```bash
# 显示会话 token
remote-claude token <session>

# 重新生成 token
remote-claude regenerate-token <session>
```

### HTTP Client 连接

```bash
# 完整格式
remote-claude connect <host> <session> --token <token> [--port 8765]

# 简写格式
remote-claude connect <host>/<session> --token <token>
remote-claude connect <host>:<port>/<session> --token <token>

# 示例
remote-claude connect 192.168.1.100 mywork --token abc123
remote-claude connect 192.168.1.100:8765/mywork --token abc123
```

### Server 控制（远程）

```bash
# 远程关闭 Server
remote-claude remote shutdown <host> <session> --token <token> [--port 8765]

# 远程重启 Claude 进程
remote-claude remote restart <host> <session> --token <token> [--port 8765]

# 远程更新 remote-claude
remote-claude remote update <host> <session> --token <token> [--port 8765]

# 示例
remote-claude remote shutdown 192.168.1.100 mywork --token abc123
remote-claude remote restart 192.168.1.100 mywork --token abc123
remote-claude remote update 192.168.1.100 mywork --token abc123
```

## 错误处理

| 错误场景 | HTTP 状态码 | 错误码 | Client 提示 |
|---------|------------|--------|-------------|
| Token 无效 | - | INVALID_TOKEN | 认证失败，请检查 token |
| Token 文件被篡改 | - | TOKEN_TAMPERED | Token 文件异常，请联系管理员 |
| Session 不存在 | - | SESSION_NOT_FOUND | 会话不存在，请先启动 |
| 远程模式未启用 | - | REMOTE_DISABLED | 该会话未启用远程模式 |
| 连接数超限 | - | TOO_MANY_CONNECTIONS | 连接数已达上限 |
| Server 未运行 | - | CONNECTION_REFUSED | 无法连接 Server，请确认已启动 |
| 网络超时 | - | TIMEOUT | 连接超时，请检查网络 |
| 心跳超时 | - | HEARTBEAT_TIMEOUT | 连接已断开（心跳超时） |
| 端口被占用 | - | PORT_IN_USE | 端口已被占用，请使用 --remote-port 指定其他端口 |
| 控制命令失败 | - | CONTROL_FAILED | 控制命令执行失败 |

## 配置文件扩展

在 `~/.remote-claude/config.json` 中新增 `remote` 字段：

```json
{
  "version": "1.0",
  "ui_settings": {
    ...
  },
  "remote": {
    "default_host": "",
    "default_port": 8765,
    "saved_connections": [
      {"name": "dev-server", "host": "192.168.1.100", "port": 8765}
    ]
  }
}
```

### 配置迁移

```
旧版本 config.json 读取流程:
1. 检查 version 字段是否存在
2. 若缺少 remote 字段，自动补全默认值
3. 保存更新后的配置文件
4. 不影响现有 ui_settings 等字段
```

## 测试策略

### 单元测试

| 测试项 | 文件 |
|-------|------|
| Token 生成/验证 | `tests/test_token_manager.py` |
| URL 解析 | `tests/test_ws_handler.py` |
| 消息编码 | `tests/test_protocol.py` (现有) |

### 集成测试

| 测试项 | 文件 |
|-------|------|
| WebSocket 连接/断开 | `tests/test_ws_connection.py` |
| 认证流程 | `tests/test_ws_auth.py` |
| 多 Client 并发 | `tests/test_ws_concurrent.py` |
| 心跳检测 | `tests/test_ws_heartbeat.py` |
| Unix Socket + WebSocket 共存 | `tests/test_dual_mode.py` |
| 控制命令 | `tests/test_remote_control.py` |

### 安全测试

| 测试项 | 说明 |
|-------|------|
| Token 爆破攻击 | 连续错误 token 请求应被拒绝 |
| Token 文件篡改 | 文件被修改后应拒绝连接 |
| 连接劫持 | 验证 WebSocket 连接来源 |
| 权限隔离 | 验证文件权限 0600 生效 |

### 端到端测试

手动测试场景：
1. Client → Server (WebSocket) → Claude 完整链路
2. 本地 Unix Socket 和远程 WebSocket 同时连接
3. 网络断开后重连
4. Server 重启后 Client 恢复
5. 远程控制命令（shutdown/restart/update）

## 文件结构

```
remote_claude/
├── client/
│   ├── client.py          # 现有 Unix Socket 客户端
│   └── http_client.py     # 新增：HTTP/WebSocket 客户端
│
├── server/
│   ├── server.py          # PTY 代理服务器（扩展 WebSocket 支持）
│   ├── ws_handler.py      # 新增：WebSocket 处理器
│   └── token_manager.py   # 新增：Token 管理
│
├── utils/
│   ├── protocol.py        # 现有消息协议（复用 + 新增 CONTROL 类型）
│   └── session.py         # 现有会话管理
│
├── tests/
│   ├── test_token_manager.py
│   ├── test_ws_handler.py
│   ├── test_ws_connection.py
│   ├── test_ws_auth.py
│   ├── test_ws_concurrent.py
│   ├── test_ws_heartbeat.py
│   ├── test_dual_mode.py
│   └── test_remote_control.py
│
└── remote_claude.py       # CLI 入口（扩展 --remote/connect 子命令）
```

## 实现优先级

1. **P0 - 核心功能**
   - Token 管理 (`server/token_manager.py`)
   - WebSocket Handler (`server/ws_handler.py`)
   - Server 扩展 (`server/server.py` 修改)
   - HTTP Client (`client/http_client.py`)
   - CLI 子命令 (`remote_claude.py`)
   - 协议扩展：新增 CONTROL 消息类型 (`utils/protocol.py`)

2. **P1 - 增强**
   - 错误处理完善
   - 日志记录
   - 配置文件支持
   - 心跳检测（使用 websockets 内置）
   - 断线时的终端状态恢复
   - 连接数限制（默认最多 10 个 WebSocket 连接）
   - 控制命令实现（shutdown/restart/update）

3. **P2 - 优化**
   - 连接池
   - 自动断线重连
   - TLS 支持

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 网络延迟 | 输入/输出有延迟 | 适合企业内网，公网需谨慎 |
| Token 泄露 | 未授权访问 | 支持 token 重新生成，定期轮换 |
| Token 文件篡改 | 安全隐患 | 文件权限 0600 + hash 校验 |
| 端口冲突 | 启动失败 | 支持 --remote-port 参数配置 |
| 并发连接数过多 | 性能下降 | 最多 10 个 WebSocket 连接 |
| NAT 超时断连 | 连接中断 | 30 秒心跳保持活跃 |
| Server 代码复杂度增加 | 维护成本 | WebSocket 逻辑封装在独立模块 |
| 控制命令滥用 | 安全风险 | Token 认证 + 操作日志 |

## Server 生命周期

### 启动流程

```
remote-claude start <session> --remote:
1. 创建 tmux 会话
2. 启动 Server 进程
   ├─ 初始化 PTY
   ├─ 启动 Unix Socket 监听
   ├─ [仅 --remote] 加载/创建 Token
   └─ [仅 --remote] 启动 WebSocket Server
3. [仅 --remote] 输出 Token 到终端
4. 等待客户端连接
```

### 关闭流程

```
Server 收到 SIGTERM/SIGINT 或 CONTROL(shutdown):
1. 停止接受新连接（Unix Socket + WebSocket）
2. 向所有 WebSocket 客户端发送 SERVER_SHUTTING_DOWN 消息
3. 等待所有连接处理完成（最多 5 秒）
4. 关闭 PTY
5. 退出进程
```

### 重启流程

```
Server 收到 CONTROL(restart):
1. 向所有客户端发送 RESTARTING 消息
2. 关闭当前 Claude PTY 进程
3. 重新启动 Claude PTY
4. 向所有客户端发送 RESTARTED 消息
5. 保持连接，继续服务
```

## 后续扩展

1. **TLS 支持**：生产环境安全传输
2. **会话列表 API**：远程查看可用会话
3. **飞书远程连接**：支持从飞书连接远程 Server
