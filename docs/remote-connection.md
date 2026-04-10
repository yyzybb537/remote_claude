# 远程连接说明

本文档只覆盖 Remote Claude 的远程连接模型、连接方式与远程管理语义。完整命令列表请以 [CLI 参考](cli-reference.md) 为准。

## 远程连接模型

Remote Claude 通过 WebSocket 暴露单个会话的远程入口，用于跨网络连接、查看状态和执行有限的远程管理操作。

```text
远程服务器                              本地客户端
┌─────────────────┐                   ┌─────────────────┐
│ Claude/Codex    │                   │ 本地终端        │
│ (PTY in tmux)   │                   │ (attach/connect)│
└────────┬────────┘                   └────────┬────────┘
         │                                     │
    ┌────┴────┐                          ┌─────┴─────┐
    │ server  │◄─── WebSocket ──────────►│  client   │
    │ (8765)  │     (token 认证)          │ (remote)  │
    └─────────┘                          └───────────┘
```

要点：
- 远程入口绑定的是**单个会话**。
- 认证依赖 token。
- 远程终端 attach 与远程管理命令共用同一条远程连接链路。

## 启动远程会话

### 启用远程模式

```bash
remote-claude start <会话名> --remote
```

### 自定义监听地址与端口

```bash
remote-claude start <会话名> --remote --remote-host 0.0.0.0 --remote-port 8765
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--remote-host` | WebSocket 监听地址 | `0.0.0.0` |
| `--remote-port` | WebSocket 监听端口 | `8765` |

## Token 管理

远程模式下，每个会话会有独立 token。

**本地查看 token：**
```bash
remote-claude token <会话名>
```

**本地重新生成 token：**
```bash
remote-claude regenerate-token <会话名>
```

说明：
- 本地 `token` / `regenerate-token` 会输出完整 token，适合在受信任终端执行。
- token 文件位于 `~/.remote-claude/tokens/<session>.json`，权限应为 `0600`。

## 连接远程会话

### 标准 attach

```bash
remote-claude attach <会话名> --remote --host <host>:<port> --token <token>
```

### 通过 host:port/会话名 省略会话名参数

```bash
remote-claude attach --remote --host <host>:<port>/<session> --token <token>
```

### 使用 connect 简化输入

```bash
remote-claude connect <host>:<port>/<session> --token <token>
```

## 保存连接配置

如果需要复用远程连接参数，可以在 attach 时保存配置：

```bash
# 保存为默认配置
remote-claude attach <会话名> --remote --host <host>:<port> --token <token> --save

# 保存为自定义名称
remote-claude attach <会话名> --remote --host <host>:<port> --token <token> --save --config-name myserver
```

之后可直接复用：

```bash
# 使用默认配置
remote-claude attach --remote

# 使用指定配置
remote-claude attach --remote --config-name myserver
```

连接配置管理命令：

```bash
remote-claude connection list
remote-claude connection show <name>
remote-claude connection set-default <name>
remote-claude connection delete <name>
```

## 远程管理语义

Remote Claude 当前存在两类远程操作：

### 1) 基于 `--remote` 的会话管理命令

这是当前日常使用的主要入口。

```bash
remote-claude list --remote --host <host>:<port> --token <token>
remote-claude status <会话名> --remote --host <host>:<port> --token <token>
remote-claude kill <会话名> --remote --host <host>:<port> --token <token>
remote-claude token <会话名> --remote --host <host>:<port> --token <token>
remote-claude regenerate-token <会话名> --remote --host <host>:<port> --token <token>
remote-claude lark start --remote --host <host>:<port> --token <token>
remote-claude lark stop --remote --host <host>:<port> --token <token>
remote-claude lark status --remote --host <host>:<port> --token <token>
```

重要说明：
- 远程 `list` 返回的是**当前 WebSocket 入口绑定会话**的状态信息，不是远端所有会话的全局枚举。
- 远程 `status` / `kill` / `token` / `regenerate-token` 需要显式传入目标会话名称。
- 远程 `token` / `regenerate-token` 返回的是 token 预览值，不会直接回显完整 token。

### 2) `remote` 子命令

`remote` 子命令用于远程服务级控制，不用于远程列出会话。

```bash
remote-claude remote shutdown <host>:<port>/<session> --token <token>
remote-claude remote restart <host>:<port>/<session> --token <token>
remote-claude remote update <host>:<port>/<session> --token <token>
```

说明：
- `remote` 仅支持 `shutdown`、`restart`、`update`。
- 不存在 `remote list`。
- 会话级查看/管理请优先使用带 `--remote` 的标准命令。

## 排障建议

### 查看启动日志

远程模式启动失败时，优先查看：

```bash
cat ~/.remote-claude/startup.log
```

重点关注：
- `stage=server_spawn`
- `stage=server_start_failed`
- `server_cmd_sanitized=...`

### 常见排查顺序

1. 先确认服务端是否已按预期地址与端口启动。
2. 再确认 token 是否匹配当前会话。
3. 最后确认客户端传入的 `host` / `port` / `会话名` 是否一致。

## 相关文档

- [CLI 参考](cli-reference.md)
- [配置说明](configuration.md)
- [开发者指南](developer.md)
