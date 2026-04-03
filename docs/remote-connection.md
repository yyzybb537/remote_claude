# 远程连接说明

Remote Claude 支持通过 WebSocket 远程连接会话，实现跨网络的操作能力。

## 概述

远程连接功能允许你：
- 在远程服务器上运行 Claude/Codex 会话
- 从本地终端连接并操作远程会话
- 通过飞书客户端远程管理会话

## 架构

```
远程服务器                              本地客户端
┌─────────────────┐                   ┌─────────────────┐
│ Claude/Codex    │                   │ 本地终端        │
│ (PTY)           │                   │ (attach)        │
└────────┬────────┘                   └────────┬────────┘
         │                                     │
    ┌────┴────┐                          ┌─────┴─────┐
    │ server  │◄─── WebSocket ──────────►│  client   │
    │ (8765)  │     (Token 认证)          │ (remote)  │
    └─────────┘                          └───────────┘
```

## 启动远程会话

### 基本启动

```bash
remote-claude start <session> --remote
```

启动后会生成一个 Token，用于远程连接认证。

### 自定义端口和地址

```bash
remote-claude start <session> --remote --remote-port 8765 --remote-host 0.0.0.0
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--remote-port` | WebSocket 端口 | 8765 |
| `--remote-host` | 监听地址 | 0.0.0.0 |

### Token 管理

Token 用于远程连接的身份认证：

**存储位置**：
- `~/.remote-claude/tokens/<session>.json`
- 文件权限：0600（仅所有者可读写）

**查看 Token**：
```bash
remote-claude token <session>
```

**重新生成 Token**：
```bash
remote-claude regenerate-token <session>
```

## 连接远程会话

### 标准连接

```bash
remote-claude attach <session> --remote --host <host> --token <token>
```

### 支持 host:port 格式

```bash
remote-claude attach <session> --remote --host <host>:<port> --token <token>
```

### 省略 session 参数

```bash
remote-claude attach --remote --host <host>:<port>/<session> --token <token>
```

### 使用 connect 命令

```bash
remote-claude connect <host>:<port>/<session> --token <token>
```

## 保存连接配置

避免每次输入 host、port、token：

### 保存配置

```bash
# 保存连接配置（默认名称: default）
remote-claude attach <session> --remote --host <host> --token <token> --save

# 保存为自定义名称
remote-claude attach <session> --remote --host <host> --token <token> --save --config-name myserver
```

### 使用保存的配置

```bash
# 使用默认配置连接
remote-claude attach --remote

# 使用指定配置连接
remote-claude attach --remote --config-name myserver
```

### 管理连接配置

```bash
# 列出所有保存的配置
remote-claude connection list

# 查看配置详情
remote-claude connection show <name>

# 设置默认连接配置
remote-claude connection set-default <name>

# 删除配置
remote-claude connection delete <name>
```

## 远程管理命令

### 会话管理

```bash
# 列出会话
remote-claude list --remote --host <host> --token <token>

# 终止会话
remote-claude kill <session> --remote --host <host> --token <token>

# 查看状态
remote-claude status <session> --remote --host <host> --token <token>
```

### Token 管理

```bash
# 获取 token
remote-claude token <session> --remote --host <host> --token <token>

# 重新生成 token
remote-claude regenerate-token <session> --remote --host <host> --token <token>
```

### 飞书客户端管理

```bash
# 远程启动飞书客户端
remote-claude lark start --remote --host <host> --token <token>

# 远程停止飞书客户端
remote-claude lark stop --remote --host <host> --token <token>

# 远程查看飞书客户端状态
remote-claude lark status --remote --host <host> --token <token>
```

### remote 命令

```bash
# 关闭服务器
remote-claude remote shutdown <host>:<port>/<session> --token <token>

# 重启服务器
remote-claude remote restart <host>:<port>/<session> --token <token>

# 更新
remote-claude remote update <host>:<port>/<session> --token <token>
```

## 远程控制命令

通过 WebSocket 发送的控制命令：

| 命令 | 说明 |
|------|------|
| `shutdown` | 关闭服务器 |
| `status` | 获取会话状态 |
| `kill` | 终止会话 |
| `token` | 获取当前 token |
| `regenerate-token` | 重新生成 token |
| `lark-start` | 远程启动飞书客户端 |
| `lark-stop` | 远程停止飞书客户端 |
| `lark-restart` | 远程重启飞书客户端 |
| `lark-status` | 远程查看飞书客户端状态 |

## 排障指南

### 查看启动日志

远程模式启动失败时，查看启动日志：

```bash
cat ~/.remote-claude/startup.log
```

**关键追溯字段**：
- `stage=server_spawn`：启动参数摘要
- `stage=server_start_failed`：失败阶段与原因
- `server_cmd_sanitized=...`：脱敏后的完整 server 启动命令

### 排查顺序

1. 先定位 `stage=server_start_failed` 的 `reason`
2. 再对照 `stage=server_spawn` 中的 `remote_host/remote_port`
3. 最后检查 `server_cmd_sanitized` 是否符合预期启动命令

### 常见问题

#### 连接超时

**可能原因**：
- 防火墙阻止了端口
- 服务未启动
- 网络不通

**解决方案**：
```bash
# 检查端口是否开放
telnet <host> <port>

# 检查服务是否运行
remote-claude status <session>
```

#### Token 认证失败

**可能原因**：
- Token 过期或被重新生成
- Token 文件损坏

**解决方案**：
```bash
# 重新生成 Token
remote-claude regenerate-token <session> --remote --host <host> --token <token>
```

#### 连接断开

**可能原因**：
- 网络不稳定
- 服务器重启
- 会话被终止

**解决方案**：
```bash
# 检查会话状态
remote-claude status <session> --remote --host <host> --token <token>

# 重新连接
remote-claude attach <session> --remote --host <host> --token <token>
```

## 安全建议

1. **Token 保护**：
   - 不要分享 Token
   - 定期重新生成 Token
   - 使用 HTTPS/WSS 加密传输

2. **网络隔离**：
   - 使用防火墙限制访问 IP
   - 通过 VPN 或内网访问
   - 避免公网暴露

3. **权限控制**：
   - 按需分配 Token
   - 及时撤销不再使用的 Token

## 配置文件

远程连接配置存储在 `~/.remote-claude/remote_connections.json`：

```json
{
  "default": {
    "host": "example.com",
    "port": 8765,
    "token": "your_token_here"
  },
  "myserver": {
    "host": "192.168.1.100",
    "port": 8765,
    "token": "another_token"
  }
}
```

**注意事项**：
- 文件权限自动设置为 0600
- 敏感信息（Token）建议定期更新
- 不要将此文件提交到版本控制

## 相关文档

- [CLI 命令参考](./cli-reference.md)
- [配置说明](./configuration.md)
- [飞书客户端管理](./feishu-client.md)
