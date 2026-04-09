# 飞书客户端管理指南

本文档只覆盖飞书客户端的启动、停止、状态查看、日志与运维排障。

飞书应用创建、权限配置与接入步骤请看 [feishu-setup.md](feishu-setup.md)；配置项与环境变量请看 [configuration.md](configuration.md)。

## 管理命令

```bash
remote-claude lark start
remote-claude lark stop
remote-claude lark status
remote-claude lark restart
```

说明：
- `start`：启动飞书客户端
- `stop`：停止飞书客户端
- `status`：查看当前状态与最近日志摘要
- `restart`：等价于先 `stop` 再 `start`

## 常见使用方式

### 启动客户端

```bash
remote-claude lark start
```

如果要先创建一个会话再在飞书中接管，可先启动本地会话：

```bash
remote-claude start my-session --launcher Codex
```

### 查看状态

```bash
remote-claude lark status
```

### 停止客户端

```bash
remote-claude lark stop
```

## 运行状态文件

飞书客户端运行时会使用以下状态文件：

| 文件路径 | 说明 |
|---------|------|
| `/tmp/remote-claude/lark.pid` | 飞书客户端进程 PID |
| `/tmp/remote-claude/lark.status` | 启动时间等状态信息 |
| `~/.remote-claude/lark_client.log` | 运行日志 |
| `~/.remote-claude/lark_client.debug.log` | 调试日志（需设置 `LARK_LOG_LEVEL=DEBUG`） |

## 日志排查

### 实时查看日志

```bash
tail -f ~/.remote-claude/lark_client.log
```

### 查看最近日志

```bash
tail -50 ~/.remote-claude/lark_client.log
```

### 搜索错误日志

```bash
grep ERROR ~/.remote-claude/lark_client.log
```

## 常见问题

### 启动失败

先看日志：

```bash
tail -20 lark_client.log
```

常见原因：
- `~/.remote-claude/.env` 缺失或配置错误
- 飞书应用权限未正确配置
- Python 依赖未安装完整

日志文件位置：
```bash
tail -20 ~/.remote-claude/lark_client.log
```

如需核对接入配置，请回到 [feishu-setup.md](feishu-setup.md)。

### 进程启动后立即退出

可以前台直接运行，观察报错：

```bash
uv run python3 lark_client/main.py
```

### `status` 显示未运行，但进程仍在

通常是状态文件残留或损坏。可按顺序处理：

```bash
ps aux | grep "lark_client/main.py"
kill -9 <PID>
rm -f /tmp/remote-claude/lark.pid /tmp/remote-claude/lark.status
remote-claude lark start
```

### 日志过大

```bash
ls -lh ~/.remote-claude/lark_client.log
mv ~/.remote-claude/lark_client.log ~/.remote-claude/lark_client.log.$(date +%Y%m%d_%H%M%S)
remote-claude lark restart
```

## 文档边界

- 飞书应用创建、权限、事件订阅：见 [feishu-setup.md](feishu-setup.md)
- 配置文件与环境变量：见 [configuration.md](configuration.md)
- 完整 CLI 参数：见 [cli-reference.md](cli-reference.md)
