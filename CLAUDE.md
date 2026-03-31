# CLAUDE.md/AGENTS.md

This file provides guidance to Claude-Code/Codex when working with code in this repository.

# **关键语言要求**
你必须完全使用 **简体中文** 进行交互、思考和汇报。

## 项目概述

Remote Claude 是一个双端共享 Claude/Codex CLI 工具。通过 PTY + Unix Socket 架构，支持多个终端客户端和飞书客户端并发连接同一个 Claude 或 Codex 会话，实现协作式 AI 对话。

## 架构

```
Claude/Codex CLI (PTY)
      │
  server.py         ← PTY 代理，管理进程/控制权/历史缓存
      │
  Unix Socket (/tmp/remote-claude/<name>.sock)
      │
  ┌───┴────┬─────────────────────┐
  │        │                     │
local_client.py  SessionBridge   remote_client.py
(终端)      (lark_client/)       (WebSocket 远程)
                │                      │
            飞书机器人              WebSocket
                                   (ws://host:8765/ws)
```

**核心模块：**
- `remote_claude.py` — CLI 入口，子命令：start / attach / list / kill / lark / connect / remote / token
- `server/server.py` — PTY 代理服务器，`pty.fork()` 启动 Claude/Codex，asyncio Unix Socket 广播输出，支持 WebSocket 远程连接
- `server/parsers/claude_parser.py` — Claude CLI 终端输出解析
- `server/parsers/codex_parser.py` — Codex CLI 终端输出解析
- `server/shared_state.py` — 共享内存写入（`.mq` 文件）
- `server/token_manager.py` — Token 管理器，生成/验证/重新生成会话 Token
- `server/ws_handler.py` — WebSocket 连接处理器，支持远程控制命令
- `client/base_client.py` — 终端客户端抽象基类，含 `send_control()` 远程控制方法
- `client/local_client.py` — 本地客户端，Unix Socket 实现
- `client/remote_client.py` — 远程客户端，WebSocket 实现
- `client/connection_config.py` — 远程连接配置管理（含内存缓存）
- `utils/protocol.py` — 消息协议（JSON + `\n` 分隔）
- `utils/session.py` — socket 路径管理、会话生命周期
- `utils/runtime_config.py` — 运行时配置管理，含旧配置迁移函数

**飞书客户端 (`lark_client/`)：**
- `main.py` — WebSocket 入口，事件分发
- `lark_handler.py` — 命令路由
- `session_bridge.py` — Unix Socket 桥接
- `shared_memory_poller.py` — 流式滚动卡片轮询器
- `card_builder.py` — 卡片构建
- `card_service.py` — 飞书卡片 API 服务

**数据流：**
```
PTY data → HistoryScreen → VirtualScreen → ScreenParser → ClaudeWindow 快照
                                                                      ↓
                                                              .mq 共享内存
                                                                      ↓
SharedMemoryPoller → hash diff → CardService → 飞书卡片更新
```

**职责分界（强制约束）：**

| 层 | 职责 | 禁止事项 |
|----|------|---------|
| **server.py** | 保证写入共享内存的输出完整、准确；ANSI 解析、终端状态还原 | — |
| **lark_client/** | 从共享内存到飞书卡片渲染的纯展示流程 | **严禁**对内容做字符串修复、ANSI 清理等处理 |

> **原则：** 飞书客户端拿到的数据应该是已经可以直接渲染的干净内容。

## 文件结构

```
remote_claude/
├── remote_claude.py            # CLI 入口
├── server/                     # PTY 代理服务器
│   ├── server.py
│   ├── parsers/
│   │   ├── base_parser.py
│   │   ├── claude_parser.py
│   │   └── codex_parser.py
│   ├── shared_state.py
│   ├── token_manager.py
│   └── ws_handler.py
├── client/                     # 终端客户端
│   ├── base_client.py
│   ├── local_client.py
│   └── remote_client.py
├── utils/
│   ├── protocol.py
│   ├── session.py
│   └── runtime_config.py
├── lark_client/                # 飞书客户端
│   ├── main.py
│   ├── lark_handler.py
│   ├── shared_memory_poller.py
│   ├── card_builder.py
│   └── card_service.py
├── tests/                      # 测试文件
├── docker/                     # Docker 测试配置
└── resources/defaults/         # 配置模板
```

## 测试

```bash
# 核心单元测试
uv run python3 -m pytest tests/test_runtime_config.py tests/test_token_manager.py -v

# 运行所有 Docker 测试
docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh
```

详细测试计划见 [`tests/TEST_PLAN.md`](./tests/TEST_PLAN.md)。

## 开发须知

- **系统要求：** macOS/Linux，需已安装 `tmux` 和 `claude` CLI
- **Socket 路径：** `/tmp/remote-claude/<name>.sock`
- **tmux 会话前缀：** `rc-`
- **语言：** 代码注释和用户交互均使用中文

### 关键约束

| 约束 | 说明 |
|------|------|
| server.py 职责 | 保证写入共享内存的输出完整、准确；ANSI 解析、终端状态还原 |
| lark_client/ 职责 | 从共享内存到飞书卡片渲染的纯展示流程；**严禁**对内容做字符串修复、ANSI 清理 |
| 配置修改原子性 | `utils/runtime_config.py` 的修改型接口使用持锁读改写，避免多进程竞态 |

### 配置文件

| 文件 | 用途 |
|------|------|
| `~/.remote-claude/config.json` | 用户可编辑配置（快捷命令、UI 设置） |
| `~/.remote-claude/runtime.json` | 程序运行时状态（会话映射、群组绑定） |
| `~/.remote-claude/tokens/<session>.json` | 会话 Token（远程模式，权限 0600） |
| `~/.remote-claude/remote_connections.json` | 远程连接配置 |

### 循环依赖处理

`utils/session.py` 和 `utils/runtime_config.py` 之间存在循环依赖。`session.py` 的 `resolve_session_name()` 使用延迟导入避免循环依赖。

### 飞书卡片 API 参考

https://open.larkoffice.com/document/feishu-cards/card-json-v2-structure
