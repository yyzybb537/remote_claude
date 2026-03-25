# Remote Claude 远程连接设计

## 概述

为 Remote Claude 添加远程连接能力，支持从本地电脑启动 client，连接到远端运行 server 的会话。采用 WebSocket 网关层方案，在现有 Unix Socket 架构之上增加 HTTP/WebSocket 支持。

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
│  ┌─────────────┐     ┌───────────────┐     ┌──────────────┐    │
│  │ Claude CLI  │◄────│ Server (PTY)  │◄────│ Unix Socket  │    │
│  └─────────────┘     └───────────────┘     └──────┬───────┘    │
│                                                    │            │
│                                            ┌──────▼───────┐    │
│                                            │  WebSocket   │    │
│                                            │   Gateway    │    │
│                                            │ (HTTP Server)│    │
│                                            └──────┬───────┘    │
│                                                   │            │
└───────────────────────────────────────────────────┼────────────┘
                                                    │
                                          WebSocket │
                                                    │
┌───────────────────────────────────────────────────┼────────────┐
│                         本地机器                 │            │
│                                          ┌──────▼───────┐    │
│                                          │  HTTP Client │    │
│                                          │ (Terminal)   │    │
│                                          └──────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 组件职责

| 组件 | 职责 | 文件位置 |
|------|------|---------|
| HTTP Client | 本地终端客户端，WebSocket 连接，身份认证 | `client/http_client.py` |
| WebSocket Gateway | HTTP Server，认证、协议转换、连接管理 | `server/gateway.py` |
| Server (PTY) | 现有 PTY 代理服务器（不变） | `server/server.py` |

### 设计原则

1. **最小侵入**：Gateway 作为独立进程，不修改现有 Server 代码
2. **协议复用**：复用现有 `utils/protocol.py` 消息格式
3. **双模式共存**：本地 Unix Socket 和远程 WebSocket 同时支持

## 认证机制

### Token 管理

```
1. Gateway 首次启动
   ├─ 生成 token (32 字节，base64 编码)
   ├─ 持久化到 ~/.remote-claude/gateway_token.json
   └─ 输出到终端: "Gateway token: xxx"

2. Token 配置文件格式:
   {
     "token": "dGhpcyBpcyBhIHJhbmRvbSB0b2tlbg==",
     "created_at": "2026-03-25T10:30:00Z",
     "last_used_at": "2026-03-25T11:00:00Z"
   }

3. 重新生成 token:
   命令: remote-claude gateway --regenerate-token
   效果: 生成新 token 并覆盖配置文件

4. Client 连接时验证
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
// INPUT 消息 (Client → Gateway → Server)
{"type": "input", "data": "<base64>", "client_id": "<id>"}

// OUTPUT 消息 (Server → Gateway → Client)
{"type": "output", "data": "<base64>"}

// HISTORY 消息 (Server → Gateway → Client)
{"type": "history", "data": "<base64>"}

// RESIZE 消息 (Client → Gateway → Server)
{"type": "resize", "rows": 24, "cols": 80, "client_id": "<id>"}

// ERROR 消息 (Gateway → Client)
{"type": "error", "message": "错误描述", "code": "SESSION_NOT_FOUND"}
```

### 数据流

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ Client   │     │ Gateway  │     │ Server   │     │ Claude   │
│ (HTTP)   │     │(WebSocket│     │(Unix Sock│     │ (PTY)    │
└────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                │                │
     │  INPUT (WS)    │                │                │
     │───────────────>│  INPUT (Unix)  │                │
     │                │───────────────>│  PTY write     │
     │                │                │───────────────>│
     │                │                │                │
     │                │                │  PTY read      │
     │                │  OUTPUT (Unix) │<───────────────│
     │  OUTPUT (WS)   │<───────────────│                │
     │<───────────────│                │                │
```

## Gateway 设计

### 核心功能

1. **HTTP Server**：监听指定端口，处理 WebSocket 升级请求
2. **认证中间件**：验证 URL 参数中的 token
3. **会话路由**：根据 `session` 参数连接对应 Unix Socket
4. **双向转发**：WebSocket ↔ Unix Socket 消息转发
5. **连接管理**：维护活跃连接，支持多 Client 并发

### 接口定义

```python
# server/gateway.py

class WebSocketGateway:
    """WebSocket 网关"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.token_manager = TokenManager()
        self.connections: Dict[str, List[WebSocketConnection]] = {}

    async def start(self):
        """启动 HTTP Server"""

    async def stop(self):
        """停止 Server，关闭所有连接"""

    async def handle_websocket(self, websocket, path):
        """处理 WebSocket 连接"""

    async def _authenticate(self, session: str, token: str) -> bool:
        """验证 token"""

    async def _connect_unix_socket(self, session: str):
        """连接到 Server 的 Unix Socket"""

    async def _forward_to_unix(self, ws_conn, unix_conn):
        """WebSocket → Unix Socket 转发"""

    async def _forward_to_ws(self, ws_conn, unix_conn):
        """Unix Socket → WebSocket 转发"""
```

### Token 管理

```python
# server/token_manager.py

class TokenManager:
    """Token 管理器"""

    TOKEN_FILE = "~/.remote-claude/gateway_token.json"

    def __init__(self):
        self._token: Optional[str] = None
        self._created_at: Optional[str] = None

    def get_or_create_token(self) -> str:
        """获取或创建 token"""

    def regenerate_token(self) -> str:
        """重新生成 token"""

    def verify_token(self, token: str) -> bool:
        """验证 token"""

    def _load_token(self) -> Optional[dict]:
        """从文件加载 token"""

    def _save_token(self, token: str):
        """保存 token 到文件"""
```

## HTTP Client 设计

### 核心功能

1. **WebSocket 连接**：连接 Gateway，携带认证信息
2. **终端处理**：raw mode、信号处理、终端大小变化
3. **输入转发**：将用户输入发送到远端
4. **输出显示**：接收远端输出并显示到终端

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

    async def connect(self) -> bool:
        """连接到 Gateway"""

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
```

## 命令行接口

### Gateway 管理

```bash
# 启动 Gateway
remote-claude gateway start [--port 8765] [--host 0.0.0.0]

# 停止 Gateway
remote-claude gateway stop

# 查看状态
remote-claude gateway status

# 显示当前 token
remote-claude gateway token

# 重新生成 token
remote-claude gateway regenerate-token
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
| Session 不存在 | 404 | SESSION_NOT_FOUND | 会话不存在，请先启动 |
| Gateway 未运行 | - | CONNECTION_REFUSED | 无法连接 Gateway，请确认已启动 |
| Unix Socket 断开 | - | SESSION_DISCONNECTED | 会话已断开 |
| 网络超时 | - | TIMEOUT | 连接超时，请检查网络 |
| 端口被占用 | - | PORT_IN_USE | 端口已被占用，请使用 --port 指定其他端口 |

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

## 测试策略

### 单元测试

| 测试项 | 文件 |
|-------|------|
| Token 生成/验证 | `tests/test_token_manager.py` |
| URL 解析 | `tests/test_gateway_utils.py` |
| 消息编码 | `tests/test_protocol.py` (现有) |

### 集成测试

| 测试项 | 文件 |
|-------|------|
| Gateway ↔ Unix Socket 转发 | `tests/test_gateway_forward.py` |
| 认证流程 | `tests/test_gateway_auth.py` |
| 多 Client 并发 | `tests/test_gateway_concurrent.py` |

### 端到端测试

手动测试场景：
1. Client → Gateway → Server → Claude 完整链路
2. 网络断开后重连
3. Gateway 重启后 Client 恢复

## 文件结构

```
remote_claude/
├── client/
│   ├── client.py          # 现有 Unix Socket 客户端
│   └── http_client.py     # 新增：HTTP/WebSocket 客户端
│
├── server/
│   ├── server.py          # 现有 PTY 代理服务器
│   ├── gateway.py         # 新增：WebSocket 网关
│   └── token_manager.py   # 新增：Token 管理
│
├── utils/
│   ├── protocol.py        # 现有消息协议（复用）
│   └── session.py         # 现有会话管理
│
├── tests/
│   ├── test_token_manager.py
│   ├── test_gateway_utils.py
│   ├── test_gateway_forward.py
│   └── test_gateway_auth.py
│
└── remote_claude.py       # CLI 入口（扩展 gateway/connect 子命令）
```

## 实现优先级

1. **P0 - 核心功能**
   - Token 管理 (`server/token_manager.py`)
   - WebSocket Gateway (`server/gateway.py`)
   - HTTP Client (`client/http_client.py`)
   - CLI 子命令 (`remote_claude.py`)

2. **P1 - 增强**
   - 错误处理完善
   - 日志记录
   - 配置文件支持

3. **P2 - 优化**
   - 连接池
   - 心跳检测
   - 断线重连

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 网络延迟 | 输入/输出有延迟 | 适合企业内网，公网需谨慎 |
| Token 泄露 | 未授权访问 | 支持 token 重新生成，定期轮换 |
| 端口冲突 | 启动失败 | 支持 --port 参数配置 |
| 并发连接数过多 | 性能下降 | 设置最大连接数限制 |

## 后续扩展

1. **TLS 支持**：生产环境安全传输
2. **负载均衡**：多 Gateway 实例
3. **会话列表 API**：远程查看可用会话
4. **飞书远程连接**：支持从飞书连接远程 Gateway
