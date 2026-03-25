# Remote Claude 远程连接设计

## 概述

为 Remote Claude 添加远程连接能力，支持从本地电脑启动 client，连接到远端运行 server 的会话。采用 Server 内置 WebSocket 支持方案，在现有 Server 进程中直接添加 HTTP/WebSocket 监听能力。

## 需求背景

- **场景**：企业内网协作，Server 运行在远程开发机上，本地 client 通过内网连接
- **通信协议**：HTTP/WebSocket
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
│  │  │   (本地)    │     │  HTTP Server (认证/转发)    │    │   │
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
| HTTP Client | 远程终端客户端，WebSocket 连接，身份认证 | `client/http_client.py` |
| Server (PTY) | PTY 代理 + 内置 WebSocket Server | `server/server.py` (扩展) |
| WebSocket Handler | 认证、协议转换、连接管理 | `server/ws_handler.py` (新增) |

### 设计原则

1. **单进程部署**：Server 内置 WebSocket 支持，无需额外 Gateway 进程
2. **协议复用**：复用现有 `utils/protocol.py` 消息格式
3. **双模式共存**：本地 Unix Socket 和远程 WebSocket 同时支持

### 与 Gateway 方案对比

| 对比项 | Server 内置方案 | Gateway 方案 |
|--------|----------------|--------------|
| 进程数 | 1 个（Server） | 2 个（Server + Gateway） |
| 转发层数 | 0 层（直连） | 1 层（Gateway 转发） |
| 部署复杂度 | 低 | 中（需管理两个进程） |
| 代码侵入性 | 高（需修改 Server） | 低（独立模块） |
| 扩展性 | 中 | 高（可独立扩缩容） |

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
```

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
```

## Server 扩展设计

### 核心功能扩展

在现有 `server/server.py` 中新增：

1. **HTTP Server 线程**：监听指定端口，处理 WebSocket 升级请求
2. **认证中间件**：验证 URL 参数中的 token
3. **WebSocket Handler**：处理远程客户端连接、消息转发
4. **心跳检测**：维持长连接活跃，检测僵尸连接

### 心跳机制

```
配置参数:
  HEARTBEAT_INTERVAL = 30 秒   // 心跳发送间隔
  HEARTBEAT_TIMEOUT = 90 秒    // 无响应超时判定

实现方式:
  ├─ 使用 WebSocket ping/pong frame（原生支持）
  ├─ Server 每 30 秒向 Client 发送 ping
  ├─ Client 收到 ping 后自动回复 pong
  └─ 若 90 秒内无 pong 响应，判定连接断开

心跳超时后处理:
  ├─ 关闭 WebSocket 连接
  ├─ 记录日志
  └─ 不影响其他客户端和 Unix Socket 连接
```

### 接口定义

```python
# server/ws_handler.py

class WebSocketHandler:
    """WebSocket 连接处理器"""

    # 心跳配置
    HEARTBEAT_INTERVAL = 30  # 秒
    HEARTBEAT_TIMEOUT = 90   # 秒
    MAX_WS_CONNECTIONS = 10  # 最大 WebSocket 连接数

    def __init__(self, server: "ProxyServer", session_name: str):
        self.server = server
        self.session_name = session_name
        self.token_manager = TokenManager(session_name)
        self.ws_connections: Set[WebSocket] = set()

    async def handle_connection(self, websocket, path):
        """处理 WebSocket 连接"""

    def _parse_url_params(self, path: str) -> Tuple[str, str]:
        """解析 URL 参数 (session, token)"""

    def _authenticate(self, token: str) -> bool:
        """验证 token"""

    def broadcast_to_ws(self, message: bytes):
        """广播输出到所有 WebSocket 客户端"""

    async def _heartbeat_loop(self, websocket):
        """心跳检测循环"""


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
        self._http_server = None

    async def start_remote_server(self):
        """启动 WebSocket Server"""

    async def stop_remote_server(self):
        """停止 WebSocket Server"""

    # 修改 _broadcast() 方法，同时广播到 Unix Socket 和 WebSocket
    async def _broadcast(self, data: bytes):
        """广播到所有客户端（Unix Socket + WebSocket）"""
        # 现有逻辑：广播到 Unix Socket 客户端
        for writer in self.clients.values():
            writer.write(encode_message(OutputMessage(data)))
            await writer.drain()

        # 新增：广播到 WebSocket 客户端
        if self.ws_handler:
            self.ws_handler.broadcast_to_ws(data)
```

### Token 管理

```python
# server/token_manager.py

class TokenManager:
    """会话 Token 管理器"""

    def __init__(self, session_name: str):
        self.session_name = session_name
        self.token_file = Path(f"~/.remote-claude/{session_name}_token.json")
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

### 接口定义

```python
# client/http_client.py

class HTTPClient:
    """HTTP/WebSocket 客户端"""

    def __init__(self, host: str, session: str, token: str, port: int = 8765):
        self.host = host
        self.session = session
        self.token = token
        self.port = port
        self.ws = None
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

    def _setup_terminal(self):
        """设置终端 raw mode"""

    def _restore_terminal(self):
        """恢复终端设置"""

    def _on_disconnect(self, reason: str):
        """断线回调：显示原因，恢复终端"""
```

## 命令行接口

### Server 启动（扩展）

```bash
# 启动会话并启用远程模式
remote-claude start <session> --remote [--remote-port 8765] [--remote-host 0.0.0.0]

# 示例
remote-claude start mywork --remote                    # 启用远程，默认端口 8765
remote-claude start mywork --remote --remote-port 9000 # 指定端口
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

## 错误处理

| 错误场景 | HTTP 状态码 | 错误码 | Client 提示 |
|---------|------------|--------|-------------|
| Token 无效 | 401 | INVALID_TOKEN | 认证失败，请检查 token |
| Token 文件被篡改 | 500 | TOKEN_TAMPERED | Token 文件异常，请联系管理员 |
| Session 不存在 | 404 | SESSION_NOT_FOUND | 会话不存在，请先启动 |
| 远程模式未启用 | 403 | REMOTE_DISABLED | 该会话未启用远程模式 |
| 连接数超限 | 429 | TOO_MANY_CONNECTIONS | 连接数已达上限 |
| Server 未运行 | - | CONNECTION_REFUSED | 无法连接 Server，请确认已启动 |
| 网络超时 | - | TIMEOUT | 连接超时，请检查网络 |
| 心跳超时 | - | HEARTBEAT_TIMEOUT | 连接已断开（心跳超时） |
| 端口被占用 | - | PORT_IN_USE | 端口已被占用，请使用 --remote-port 指定其他端口 |

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
│   ├── protocol.py        # 现有消息协议（复用）
│   └── session.py         # 现有会话管理
│
├── tests/
│   ├── test_token_manager.py
│   ├── test_ws_handler.py
│   ├── test_ws_connection.py
│   ├── test_ws_auth.py
│   ├── test_ws_concurrent.py
│   ├── test_ws_heartbeat.py
│   └── test_dual_mode.py
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

2. **P1 - 增强**
   - 错误处理完善
   - 日志记录
   - 配置文件支持
   - 心跳检测（保持长连接活跃）
   - 断线时的终端状态恢复
   - 连接数限制（默认最多 10 个 WebSocket 连接）

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

## Server 生命周期

### 启动流程

```
remote-claude start <session> --remote:
1. 创建 tmux 会话
2. 启动 Server 进程
   ├─ 初始化 PTY
   ├─ 启动 Unix Socket 监听
   ├─ 加载/创建 Token
   └─ 启动 WebSocket Server（在独立线程/协程）
3. 输出 Token 到终端
4. 等待客户端连接
```

### 关闭流程

```
Server 收到 SIGTERM/SIGINT:
1. 停止接受新连接（Unix Socket + WebSocket）
2. 向所有 WebSocket 客户端发送 SERVER_SHUTTING_DOWN 消息
3. 等待所有连接处理完成（最多 5 秒）
4. 关闭 PTY
5. 退出进程
```

## 后续扩展

1. **TLS 支持**：生产环境安全传输
2. **会话列表 API**：远程查看可用会话
3. **飞书远程连接**：支持从飞书连接远程 Server
4. **独立 Gateway**：需要负载均衡时可拆分为独立 Gateway 服务
