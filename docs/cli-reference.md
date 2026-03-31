# CLI 命令参考

Remote Claude 提供完整的命令行工具，用于管理 Claude/Codex 会话。

## 快捷命令

安装后可直接使用的快捷命令：

| 命令 | 说明 | 权限确认 |
|------|------|---------|
| `cla` | 启动 Claude 会话 | 需要 |
| `cl` | 启动 Claude 会话 | 跳过 |
| `cx` | 启动 Codex 会话 | 跳过 |
| `cdx` | 启动 Codex 会话 | 需要 |

```bash
cla        # 在当前目录启动 Claude 会话（会话名：当前目录路径+时间戳）
cl         # 启动 Claude，并跳过权限确认
cx         # 在当前目录启动 Codex，会跳过权限确认
cdx        # 在当前目录启动 Codex，并保留权限确认
```

## 主命令

### start - 启动会话

```bash
remote-claude start <会话名> [选项]
```

**选项**：
| 选项 | 说明 |
|------|------|
| `--cli-type <type>` | CLI 类型（claude/codex），默认自动检测 |
| `--remote` | 启用远程模式 |
| `--remote-port <port>` | 远程端口，默认 8765 |
| `--remote-host <host>` | 远程监听地址，默认 0.0.0.0 |

**示例**：
```bash
# 启动本地会话
remote-claude start my-session

# 启动远程会话
remote-claude start my-session --remote --remote-port 8765

# 指定 CLI 类型
remote-claude start my-session --cli-type codex
```

### attach - 连接会话

```bash
remote-claude attach <会话名> [选项]
```

**选项**：
| 选项 | 说明 |
|------|------|
| `--remote` | 远程连接模式 |
| `--host <host>` | 远程主机地址（支持 host:port 格式） |
| `--token <token>` | 连接 Token |
| `--save` | 保存连接配置 |
| `--config-name <name>` | 配置名称 |

**示例**：
```bash
# 本地连接
remote-claude attach my-session

# 远程连接
remote-claude attach my-session --remote --host example.com:8765 --token xxx

# 保存配置
remote-claude attach my-session --remote --host example.com:8765 --token xxx --save
```

### list - 列出会话

```bash
remote-claude list [选项]
```

**选项**：
| 选项 | 说明 |
|------|------|
| `--remote` | 远程模式 |
| `--host <host>` | 远程主机 |
| `--token <token>` | 连接 Token |

**示例**：
```bash
# 列出本地会话
remote-claude list

# 列出远程会话
remote-claude list --remote --host example.com:8765 --token xxx
```

### kill - 终止会话

```bash
remote-claude kill <会话名> [选项]
```

**选项**：
| 选项 | 说明 |
|------|------|
| `--remote` | 远程模式 |
| `--host <host>` | 远程主机 |
| `--token <token>` | 连接 Token |

**示例**：
```bash
# 终止本地会话
remote-claude kill my-session

# 终止远程会话
remote-claude kill my-session --remote --host example.com:8765 --token xxx
```

### status - 查看状态

```bash
remote-claude status <会话名> [选项]
```

**选项**：
| 选项 | 说明 |
|------|------|
| `--remote` | 远程模式 |
| `--host <host>` | 远程主机 |
| `--token <token>` | 连接 Token |

**示例**：
```bash
remote-claude status my-session
```

### log - 查看日志

```bash
remote-claude log [会话名]
```

不指定会话名时查看最近会话的日志。

**示例**：
```bash
# 查看指定会话日志
remote-claude log my-session

# 查看最近会话日志
remote-claude log
```

### stats - 使用统计

```bash
remote-claude stats
```

显示使用统计信息。

### update - 更新版本

```bash
remote-claude update
```

更新到最新版本。

### config - 配置管理

```bash
remote-claude config <子命令>
```

**子命令**：
| 子命令 | 说明 |
|--------|------|
| `reset` | 重置配置 |
| `reset --all` | 重置所有配置（包括运行时状态） |

**示例**：
```bash
# 重置用户配置
remote-claude config reset

# 重置所有配置
remote-claude config reset --all
```

## Token 管理

### token - 显示 Token

```bash
remote-claude token <会话名> [选项]
```

**选项**：
| 选项 | 说明 |
|------|------|
| `--remote` | 远程模式 |
| `--host <host>` | 远程主机 |
| `--token <token>` | 连接 Token |

### regenerate-token - 重新生成 Token

```bash
remote-claude regenerate-token <会话名> [选项]
```

**选项**：
| 选项 | 说明 |
|------|------|
| `--remote` | 远程模式 |
| `--host <host>` | 远程主机 |
| `--token <token>` | 连接 Token |

## 远程连接管理

### connect - 简化连接

```bash
remote-claude connect <host>:<port>/<session> --token <token>
```

**示例**：
```bash
remote-claude connect example.com:8765/my-session --token xxx
```

### remote - 远程控制

```bash
remote-claude remote <子命令> <host>:<port>/<session> --token <token>
```

**子命令**：
| 子命令 | 说明 |
|--------|------|
| `shutdown` | 关闭服务器 |
| `restart` | 重启服务器 |
| `update` | 更新版本 |

**示例**：
```bash
remote-claude remote shutdown example.com:8765/my-session --token xxx
```

### connection - 连接配置管理

```bash
remote-claude connection <子命令>
```

**子命令**：
| 子命令 | 说明 |
|--------|------|
| `list` | 列出所有保存的配置 |
| `show <name>` | 查看配置详情 |
| `set-default <name>` | 设置默认配置 |
| `delete <name>` | 删除配置 |

**示例**：
```bash
# 列出配置
remote-claude connection list

# 查看配置详情
remote-claude connection show default

# 设置默认配置
remote-claude connection set-default myserver

# 删除配置
remote-claude connection delete oldserver
```

## 飞书客户端管理

### lark - 飞书客户端命令

```bash
remote-claude lark <子命令> [选项]
```

**子命令**：
| 子命令 | 说明 |
|--------|------|
| `start` | 启动飞书客户端 |
| `stop` | 停止飞书客户端 |
| `status` | 查看飞书客户端状态 |
| `restart` | 重启飞书客户端 |

**选项**（远程模式）：
| 选项 | 说明 |
|------|------|
| `--remote` | 远程模式 |
| `--host <host>` | 远程主机 |
| `--token <token>` | 连接 Token |

**示例**：
```bash
# 本地管理
remote-claude lark start
remote-claude lark status
remote-claude lark stop

# 远程管理
remote-claude lark start --remote --host example.com:8765 --token xxx
```

## 飞书机器人命令

在飞书中与机器人对话时可用：

| 命令 | 说明 |
|------|------|
| `/menu` | 显示功能菜单 |
| `/attach <会话名>` | 连接到会话 |
| `/detach` | 断开会话连接 |
| `/list` | 列出所有会话 |
| `/help` | 显示帮助信息 |

## 选项总览

### 全局选项

| 选项 | 说明 |
|------|------|
| `--help` | 显示帮助信息 |
| `--version` | 显示版本号 |

### 远程选项

| 选项 | 说明 |
|------|------|
| `--remote` | 启用远程模式 |
| `--host <host>` | 远程主机地址 |
| `--token <token>` | 连接 Token |
| `--remote-port <port>` | 远程端口（仅 start） |
| `--remote-host <host>` | 监听地址（仅 start） |

## 退出码

| 退出码 | 说明 |
|--------|------|
| 0 | 成功 |
| 1 | 一般错误 |
| 2 | 参数错误 |
| 130 | 用户中断（Ctrl+C） |

## 相关文档

- [配置说明](./configuration.md)
- [远程连接说明](./remote-connection.md)
- [飞书客户端管理](./feishu-client.md)
