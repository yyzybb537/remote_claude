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

## 常用命令

```bash
# 启动会话
uv run python3 remote_claude.py start <会话名>

# 连接/管理会话
uv run python3 remote_claude.py attach <会话名>
uv run python3 remote_claude.py list
uv run python3 remote_claude.py kill <会话名>

# 飞书客户端管理
uv run python3 remote_claude.py lark start
uv run python3 remote_claude.py lark stop
uv run python3 remote_claude.py lark status

# 远程连接
remote-claude start <session> --remote [--remote-port 8765]
remote-claude attach <session> --remote --host <host> --token <token>

# 保存远程连接配置
remote-claude attach <session> --remote --host <host> --token <token> --save
remote-claude attach <session> --remote --host <host> --token <token> --save --config-name myserver

# 使用保存的配置连接
remote-claude attach --remote  # 使用默认配置
remote-claude attach --remote --config-name myserver  # 使用指定配置

# 管理保存的连接配置
remote-claude connection list
remote-claude connection show <name>
remote-claude connection set-default <name>
remote-claude connection delete <name>

# 远程控制命令
remote-claude token <session> --remote --host <host> --token <token>
remote-claude regenerate-token <session> --remote --host <host> --token <token>
remote-claude kill <session> --remote --host <host> --token <token>
remote-claude lark start/stop/status --remote --host <host> --token <token>
```

## 测试

```bash
# 核心单元测试
uv run python3 tests/test_session_truncate.py
uv run python3 tests/test_runtime_config.py

# 运行所有 Docker 测试
docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh
```

详细测试计划见 [`tests/TEST_PLAN.md`](./tests/TEST_PLAN.md)。

## 变更同步规则

**每当做事规则或需求发生变更时，必须同步更新：**
- `CLAUDE.md` — 架构说明、开发须知
- `tests/TEST_PLAN.md` — 测试场景

## 开发须知

- **系统要求：** macOS/Linux，需已安装 `tmux` 和 `claude` CLI；npm/pnpm 安装场景下不假设 lifecycle scripts 一定执行成功，也不要求用户预装 `uv`
- **飞书配置：** 复制 `resources/defaults/.env.example` 为 `~/.remote-claude/.env`
- **Socket 路径：** `/tmp/remote-claude/<name>.sock`
- **tmux 会话前缀：** `rc-`
- **语言：** 代码注释和用户交互均使用中文
- **初始化机制：** `cla` / `cl` / `cx` / `cdx` / `remote-claude` 在首次运行时自动检查并初始化 Python 环境，命令可用性不依赖 `postinstall`

### 循环依赖处理

`utils/session.py` 和 `utils/runtime_config.py` 之间存在循环依赖。`session.py` 的 `resolve_session_name()` 使用延迟导入避免循环依赖。

### 配置文件架构

| 文件 | 用途 |
|------|------|
| `~/.remote-claude/config.json` | 用户可编辑配置（快捷命令、UI 设置） |
| `~/.remote-claude/runtime.json` | 程序运行时状态（会话映射、群组绑定） |

**config.json 关键配置：**
- `ui_settings.quick_commands` — 快捷命令配置
- `ui_settings.custom_commands` — 自定义 CLI 命令
- `ui_settings.notify` — 就绪通知配置
- `ui_settings.auto_answer` — 自动应答配置
- `ui_settings.card_expiry` — 卡片过期配置

### 配置迁移

启动时自动迁移旧配置文件：
- `lark_group_mapping.json` → `runtime.json`
- `ready_notify_count`/`ready_notify_enabled`/`urgent_notify_enabled`/`bypass_enabled` → `config.json` + `runtime.json`

迁移函数定义在 `utils/runtime_config.py`：
- `migrate_legacy_config()` — 迁移 lark_group_mapping
- `migrate_legacy_notify_settings()` — 迁移旧开关文件

### 远程连接配置存储

**Token 存储**（服务端）：
- 文件：`~/.remote-claude/<session>_token.json`
- 内容：session、token、created_at、last_used_at、file_hash
- 权限：0600（仅所有者可读写）
- 完整性：SHA-256 hash 验证

**连接配置存储**（客户端）：
- 文件：`~/.remote-claude/remote_connections.json`
- 内容：name、host、port、token、session、description、is_default
- 用途：保存常用远程连接，避免重复输入参数

**自动应答策略：**
1. 推荐选项优先：选择标记为 `(recommended)` 或 `推荐` 的选项
2. 无明确语义时回复"继续"：确认类选项时发送"继续"
3. 兜底选择第一项

### 终端解析规则要点

**组件分类：**
- **累积型 Block**：OutputBlock、UserInput、PlanBlock、SystemBlock（随对话增长，历史保留）
- **状态型组件**：StatusLine、BottomBar、AgentPanelBlock、OptionBlock（全局唯一，每帧覆盖）

**执行状态判断：**
- Block 首行首列字符 **blink=true** → 正在执行（is_streaming=True）
- Block 首行首列字符 **blink=false** → 已完成

**Codex 与 Claude 差异：**
- Codex 用背景色区域识别输入区（无分割线）
- Codex 提示符为 `›` (U+203A)，Claude 为 `❯` (U+276F)
- Codex 用圆点 + blink 区分 StatusLine/OutputBlock，Claude 用不同字符

### 飞书卡片 API 参考

https://open.larkoffice.com/document/feishu-cards/card-json-v2-structure
