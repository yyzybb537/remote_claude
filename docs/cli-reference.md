# CLI 参考

本文档覆盖 `remote-claude` 的命令行接口、参数说明与使用示例。

安装、快速开始与使用场景请看 [`README.md`](../README.md)；配置项、飞书接入、远程连接与开发说明请看对应专题文档。

## 命令概览

```bash
remote-claude <command> [options]
```

| 命令 | 说明 |
|------|------|
| `start` | 启动新会话 |
| `attach` | 连接到已有会话 |
| `list` | 列出所有会话 |
| `kill` | 终止会话 |
| `status` | 显示会话状态 |
| `lark` | 飞书客户端管理 |
| `config` | 配置管理 |
| `connection` | 管理远程连接配置 |
| `stats` | 查看使用统计 |
| `update` | 更新到最新版本 |
| `uninstall` | 清理本地数据 |
| `connect` | 连接到远程会话 |
| `remote` | 远程控制 |
| `token` | 显示会话 token |
| `regenerate-token` | 重新生成 token |

---

## start - 启动新会话

```bash
remote-claude start <会话名> [选项]
```

| 参数 | 说明 |
|------|------|
| `<会话名>` | 会话名称（必填） |
| `--launcher`, `-l` | 启动器名称（Claude/Codex），默认使用第一个 |
| `--remote` | 启用远程连接模式 |
| `--remote-host` | 远程监听地址（默认: 0.0.0.0） |
| `--remote-port` | 远程端口（默认: 8765） |
| `--debug-screen` | 开启屏幕调试日志 |
| `--debug-verbose` | 输出完整诊断信息 |
| `--` 后的参数 | 传递给 CLI 的额外参数 |

**示例：**
```bash
# 启动 Claude 会话
remote-claude start mywork

# 启动 Codex 会话
remote-claude start mywork --launcher Codex

# 启动远程会话
remote-claude start mywork --remote --remote-port 9000

# 传递参数给 CLI
remote-claude start mywork -- --dangerously-skip-permissions
```

---

## attach - 连接会话

```bash
remote-claude attach [会话名] [选项]
```

| 参数 | 说明 |
|------|------|
| `[会话名]` | 会话名称（使用保存的配置时可省略） |
| `--remote` | 远程连接模式 |
| `--host` | 远程服务器地址（支持 `host:port/session` 格式） |
| `--port` | 远程端口（默认: 8765） |
| `--token` | 认证令牌（远程模式必需） |
| `--save` | 保存当前连接配置 |
| `--config-name` | 配置名称（默认: default） |

**示例：**
```bash
# 本地连接
remote-claude attach mywork

# 远程连接
remote-claude attach mywork --remote --host server.com:8765 --token xxx

# 使用 host:port/session 格式
remote-claude attach --remote --host server.com:8765/mywork --token xxx

# 保存连接配置
remote-claude attach mywork --remote --host server.com:8765 --token xxx --save
```

---

## list - 列出会话

```bash
remote-claude list [选项]
```

| 参数 | 说明 |
|------|------|
| `--full` | 显示完整名称（不截断） |
| `--remote` | 远程模式 |
| `--host` | 远程服务器地址 |
| `--port` | 远程端口 |
| `--token` | 认证令牌 |

---

## kill - 终止会话

```bash
remote-claude kill <会话名> [选项]
```

支持 `--remote` 系列参数。

---

## status - 会话状态

```bash
remote-claude status <会话名> [选项]
```

支持 `--remote` 系列参数。

---

## lark - 飞书客户端管理

```bash
remote-claude lark <子命令>
```

| 子命令 | 说明 |
|--------|------|
| `start` | 启动飞书客户端 |
| `stop` | 停止飞书客户端 |
| `restart` | 重启飞书客户端 |
| `status` | 查看状态 |

**示例：**
```bash
remote-claude lark start
remote-claude lark status
remote-claude lark stop
```

---

## config - 配置管理

```bash
remote-claude config <子命令>
```

| 子命令 | 说明 |
|--------|------|
| `reset` | 重置配置文件 |

**reset 选项：**
| 参数 | 说明 |
|------|------|
| `--all` | 重置全部配置 |
| `--settings` | 仅重置用户配置 |
| `--state` | 仅重置运行时状态 |

---

## connection - 远程连接配置管理

```bash
remote-claude connection <子命令>
```

| 子命令 | 说明 |
|--------|------|
| `list` | 列出所有保存的连接配置 |
| `show <name>` | 显示配置详情 |
| `delete <name>` | 删除配置 |
| `set-default <name>` | 设置默认配置 |

别名：`conn`

---

## connect - 连接远程会话

```bash
remote-claude connect <host> [--session <会话名>] --token <token>
```

| 参数 | 说明 |
|------|------|
| `<host>` | 服务器地址（支持 `host:port/session` 格式） |
| `--session` | 会话名称 |
| `--token` | 认证令牌（必填） |
| `--port` | 端口（默认: 8765） |

---

## remote - 远程控制

```bash
remote-claude remote <action> <host> [--session <会话名>] --token <token>
```

| action | 说明 |
|--------|------|
| `shutdown` | 关闭远程会话 |
| `restart` | 重启远程会话 |
| `update` | 更新远程服务 |

---

## token / regenerate-token

```bash
remote-claude token <会话名> [选项]
remote-claude regenerate-token <会话名> [选项]
```

支持 `--remote` 系列参数进行远程操作。

---

## stats - 使用统计

```bash
remote-claude stats [选项]
```

| 参数 | 说明 |
|------|------|
| `--range` | 时间范围：today（默认）、7d、30d、90d |
| `--detail` | 显示详细分类 |
| `--session` | 按会话筛选 |
| `--reset` | 清空统计数据 |
| `--report` | 触发聚合上报 |

---

## update / uninstall

```bash
remote-claude update          # 更新到最新版本
remote-claude uninstall [-y]  # 清理本地数据
```

---

## 相关文档

- 项目介绍、安装方式与快速开始：查看 [`README.md`](../README.md)
- 配置项与环境变量：查看 [`configuration.md`](configuration.md)
- 远程连接与控制链路：查看 [`remote-connection.md`](remote-connection.md)
- 开发维护说明：查看 [`developer.md`](developer.md)
- Docker 回归：查看 [`../docker/README.md`](../docker/README.md)
- 测试矩阵与回归入口：查看 [`../tests/README.md`](../tests/README.md)
