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
   │  └─ 文件权限: 0600 (仅所有者可读写)
   └─ 输出到终端: "Gateway token: xxx"

2. Token 配置文件格式:
   {
     "token": "dGhpcyBpcyBhIHJhbmRvbSB0b2tlbg==",
     "created_at": "2026-03-25T10:30:00Z",
     "last_used_at": "2026-03-25T11:00:00Z",
     "file_hash": "sha256:abc123..."  // 用于检测文件篡改
   }

3. Token 文件安全措施:
   ├─ 文件权限设置为 0600，防止其他用户读取
   ├─ 每次加载时验证 file_hash，检测非法篡改
   ├─ 若检测到篡改，拒绝启动并提示管理员检查
   └─ Token 泄露时应立即使用 regenerate-token 重新生成

4. 重新生成 token:
   命令: remote-claude gateway regenerate-token
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
6. **心跳检测**：维持长连接活跃，检测僵尸连接

### 心跳机制

```
配置参数:
  HEARTBEAT_INTERVAL = 30 秒   // 心跳发送间隔
  HEARTBEAT_TIMEOUT = 90 秒    // 无响应超时判定

实现方式:
  ├─ 使用 WebSocket ping/pong frame（原生支持，无需自定义消息）
  ├─ Gateway 每 30 秒向 Client 发送 ping
  ├─ Client 收到 ping 后自动回复 pong（浏览器内置）
  └─ 若 90 秒内无 pong 响应，判定连接断开，关闭 WebSocket

NAT 超时处理:
  ├─ 企业内网 NAT 超时通常为 60-300 秒
  ├─ 30 秒心跳间隔可有效保持连接活跃
  └─ 若仍有超时，可配置更短间隔
```

### 接口定义

```python
# server/gateway.py

class WebSocketGateway:
    """WebSocket 网关"""

    # 心跳配置
    HEARTBEAT_INTERVAL = 30  # 秒
    HEARTBEAT_TIMEOUT = 90   # 秒
    MAX_CONNECTIONS_PER_SESSION = 10  # 单会话最大连接数

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

    async def _heartbeat_loop(self, ws_conn):
        """心跳检测循环"""
```

### Token 管理

```python
# server/token_manager.py

class TokenManager:
    """Token 管理器"""

    TOKEN_FILE = "~/.remote-claude/gateway_token.json"
    TOKEN_FILE_MODE = 0o600  # 仅所有者可读写

    def __init__(self):
        self._token: Optional[str] = None
        self._created_at: Optional[str] = None
        self._file_hash: Optional[str] = None

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
        """计算文件内容 hash（用于篡改检测）"""

    def _verify_file_integrity(self) -> bool:
        """验证文件完整性"""
```

## HTTP Client 设计

### 核心功能

1. **WebSocket 连接**：连接 Gateway，携带认证信息
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

    def _setup_terminal(self):
        """设置终端 raw mode"""

    def _restore_terminal(self):
        """恢复终端设置"""

    def _on_disconnect(self, reason: str):
        """断线回调：显示原因，恢复终端"""
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
| Token 文件被篡改 | 500 | TOKEN_TAMPERED | Token 文件异常，请联系管理员 |
| Session 不存在 | 404 | SESSION_NOT_FOUND | 会话不存在，请先启动 |
| Session 连接数超限 | 429 | TOO_MANY_CONNECTIONS | 会话连接数已达上限 |
| Gateway 未运行 | - | CONNECTION_REFUSED | 无法连接 Gateway，请确认已启动 |
| Unix Socket 断开 | - | SESSION_DISCONNECTED | 会话已断开 |
| 网络超时 | - | TIMEOUT | 连接超时，请检查网络 |
| 心跳超时 | - | HEARTBEAT_TIMEOUT | 连接已断开（心跳超时） |
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
| URL 解析 | `tests/test_gateway_utils.py` |
| 消息编码 | `tests/test_protocol.py` (现有) |

### 集成测试

| 测试项 | 文件 |
|-------|------|
| Gateway ↔ Unix Socket 转发 | `tests/test_gateway_forward.py` |
| 认证流程 | `tests/test_gateway_auth.py` |
| 多 Client 并发 | `tests/test_gateway_concurrent.py` |
| 心跳检测 | `tests/test_gateway_heartbeat.py` |

### 安全测试

| 测试项 | 说明 |
|-------|------|
| Token 爆破攻击 | 连续错误 token 请求应被拒绝 |
| Token 文件篡改 | 文件被修改后应拒绝启动 |
| 连接劫持 | 验证 WebSocket 连接来源 |
| 权限隔离 | 验证文件权限 0600 生效 |

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
   - 心跳检测（保持长连接活跃）
   - 断线时的终端状态恢复
   - 并发连接数限制（默认单会话最多 10 个）

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
| 端口冲突 | 启动失败 | 支持 --port 参数配置 |
| 并发连接数过多 | 性能下降 | 单会话最多 10 个连接 |
| NAT 超时断连 | 连接中断 | 30 秒心跳保持活跃 |

## Gateway 与 Server 生命周期

### 启动顺序

```
推荐顺序:
1. 启动 Server (remote-claude start <session>)
2. 启动 Gateway (remote-claude gateway start)

Gateway 可独立于 Server 运行，连接时会检测目标 session 是否存在。
```

### Server 重启时

```
场景: Server 进程重启（如更新、崩溃恢复）

Gateway 处理:
1. Unix Socket 连接断开
2. 关闭对应的 WebSocket 连接
3. 向 Client 发送 SESSION_DISCONNECTED 错误
4. Client 提示用户"会话已断开，请重新连接"
```

### Gateway 重启时

```
场景: Gateway 进程重启

处理流程:
1. 关闭所有 WebSocket 连接
2. Client 检测到连接断开
3. Client 恢复终端设置，提示"Gateway 已断开"
4. 用户可重新执行 connect 命令连接
```

### 优雅关闭

```
Gateway 收到 SIGTERM/SIGINT:
1. 停止接受新连接
2. 向所有 Client 发送 GATEWAY_SHUTTING_DOWN 消息
3. 等待所有连接处理完成（最多 5 秒）
4. 关闭 Server

## 后续扩展

1. **TLS 支持**：生产环境安全传输
2. **负载均衡**：多 Gateway 实例
3. **会话列表 API**：远程查看可用会话
4. **飞书远程连接**：支持从飞书连接远程 Gateway
