# Remote Claude

**在电脑终端上打开的 Claude Code 进程，也可以在飞书中共享操作。电脑端、手机端无缝来回切换**

电脑上用终端跑 Claude Code 写代码，同时在手机飞书上看进度、发指令、点按钮 — 不用守在电脑前，随时随地掌控 AI 编程。

## 为什么需要它？

Claude Code 只能在启动它的那个终端窗口里操作。一旦离开电脑，就只能干等。Remote Claude 让你：

- **飞书里直接操作** — 手机/平板打开飞书，就能看到 Claude 的实时输出，发消息、选选项、批准权限
- **多端无缝切换** — 电脑上打开的 Claude 进程，手机上继续操作；手机上启动的工作，电脑上 `attach` 继续
- **机制安全** — 完全不侵入 Claude 进程，通过 PTY + Unix Socket 实现共享

## 飞书端体验

- 彩色代码输出，ANSI 着色完整还原
- 交互式按钮：选项选择、权限确认，一键点击
- 流式卡片更新：Claude 边想边输出，飞书端实时滚动显示
- 后台 agent 状态面板：查看并管理正在运行的子任务

## 快速开始

### 安装

以下方式任选其一，安装后重启 shell 生效：

```bash
# 方式一：npm 安装（推荐）
npm install -g remote-claude

# 方式二：pnpm 安装
pnpm add -g remote-claude

# 方式三：零依赖安装（无需预装 Python）
curl -fsSL https://raw.githubusercontent.com/yyzybb537/remote_claude/main/scripts/install.sh | bash
```

> 说明：pnpm 可能因 lifecycle script 安全策略而不执行 `postinstall`。Remote Claude 不依赖安装阶段 hook 成功；通过已安装到 PATH 的入口命令（如 `cla`、`cl`、`cx`、`cdx`、`remote-claude`）首次运行时，会自动准备 Python 环境。

首次运行时会自动完成：uv 包管理器安装、Python 虚拟环境创建、依赖安装。
如自动初始化失败，先重新打开 shell 后重试；若仍失败，再按安装输出或全局包路径定位安装目录并手动执行：`sh <安装目录>/scripts/setup.sh --npm --lazy`

### 启动

安装完成后，日常直接使用这些 shell 命令即可：

| 快捷命令 | 说明 |
|------|------|
| `cla` | 启动 Claude（会话名：当前目录路径+时间戳） |
| `cl` | 同 `cla`，跳过权限确认 |
| `cx` | 启动 Codex（跳过权限确认） |
| `cdx` | 同 `cx`，需确认权限 |

```bash
cla        # 在当前目录启动 Claude 会话
cl         # 启动 Claude，并跳过权限确认
cx         # 在当前目录启动 Codex，会跳过权限
cdx        # 在当前目录启动 Codex，并保留权限确认
```

首次运行这些命令时，会自动检查并准备所需运行环境；无需手动执行 Python 启动命令。

### 从其他终端连接

```bash
remote-claude list              # 查看所有会话
remote-claude attach <会话名>   # 连接现有会话
```

### 配置飞书机器人

1. 登录[飞书开放平台](https://open.feishu.cn/)，创建企业自建应用
2. 获取 **App ID** 和 **App Secret**
3. 启动 Claude/Codex 一次，按提示填入凭证
4. 在飞书开放平台配置：
   - 添加应用能力（机器人）
   - 配置事件回调：`接收消息 v2.0`、`卡片回传交互`
   - 配置权限：[点击查看权限列表](./docs/feishu-permissions.json)
   - 发布到线上

5. 在飞书中搜索机器人，发送 `/menu` 开始使用

### 故障恢复

如果首次运行自动初始化失败，先重新打开 shell 后重试；若仍失败，再按安装输出或全局包路径定位安装目录，并执行：
```bash
sh <安装目录>/scripts/setup.sh --npm --lazy
```

### 卸载

```bash
npm uninstall -g remote-claude
```

通过 npm/pnpm 的卸载 hook 卸载时，会自动清理当前用户的 `~/.remote-claude` 配置目录；手动执行卸载脚本时仍会保留交互确认。

如仅需手动清理配置，可执行：
```bash
remote-claude config reset --all
```

## 管理命令

```bash
remote-claude start <会话名>     # 启动新会话
remote-claude attach <会话名>    # 连接现有会话
remote-claude list               # 查看所有会话
remote-claude kill <会话名>      # 终止会话
remote-claude status <会话名>    # 查看会话状态
remote-claude stats              # 查看使用统计
remote-claude update             # 更新到最新版本
remote-claude log [会话名]       # 查看会话日志（不指定则查看最近会话）
remote-claude config reset       # 重置配置
remote-claude token <会话名>     # 显示会话 token
remote-claude regenerate-token <会话名>  # 重新生成 token
```

### 飞书客户端

```bash
remote-claude lark start         # 启动（后台运行）
remote-claude lark stop          # 停止
remote-claude lark status        # 查看状态
```

飞书中与机器人对话，可用命令：`/menu`、`/attach`、`/detach`、`/list`、`/help`。

## 配置

### 配置文件

| 文件 | 用途 |
|------|------|
| `~/.remote-claude/config.json` | 用户配置（快捷命令、UI 设置） |
| `~/.remote-claude/runtime.json` | 运行时状态（会话映射、群组绑定） |
| `~/.remote-claude/remote_connections.json` | 远程连接配置 |

### 快捷命令配置

```json
{
  "ui_settings": {
    "quick_commands": {
      "enabled": true,
      "commands": [
        {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
        {"label": "压缩上下文", "value": "/consume", "icon": "📦"}
      ]
    }
  }
}
```

### 自动应答配置

```json
{
  "ui_settings": {
    "auto_answer": {
      "default_delay_seconds": 10
    }
  }
}
```

自动应答策略：
1. 优先选择标记为 `(recommended)` 或 `推荐` 的选项
2. 确认类选项回复"继续"
3. 兜底选择第一项

### 卡片过期配置

```json
{
  "ui_settings": {
    "card_expiry": {
      "enabled": true,
      "expiry_seconds": 3600
    }
  }
}
```

卡片过期后自动创建新卡片，避免飞书卡片内容过长。

### 自定义 CLI 命令

```json
{
  "ui_settings": {
    "custom_commands": {
      "enabled": true,
      "commands": [
        {"name": "Claude", "cli_type": "claude", "command": "/usr/local/bin/claude"},
        {"name": "Codex", "cli_type": "codex", "command": "codex"}
      ]
    }
  }
}
```

### 环境变量

在 `~/.remote-claude/.env` 中配置：

| 配置项 | 说明 |
|--------|------|
| `FEISHU_APP_ID` | 飞书应用 ID |
| `FEISHU_APP_SECRET` | 飞书应用密钥 |
| `LARK_LOG_LEVEL` | 日志级别（DEBUG/INFO/WARNING/ERROR） |

**其他配置文件：**

| 文件 | 用途 |
|------|------|
| `~/.remote-claude/runtime.json` | 运行时状态（会话映射、群组绑定） |
| `~/.remote-claude/remote_connections.json` | 远程连接配置（host、port、token） |
| `~/.remote-claude/tokens/<session>.json` | 会话 Token（远程模式，权限 0600） |

## 远程连接

Remote Claude 支持通过 WebSocket 远程连接会话。

### 启动远程会话

```bash
remote-claude start <session> --remote [--remote-port 8765] [--remote-host 0.0.0.0]
```

启动后会生成一个 Token，用于远程连接认证。

**Token 存储**：
- 存储位置：`~/.remote-claude/tokens/<session>.json`
- 文件权限：0600（仅所有者可读写）
- 支持 SHA-256 完整性验证

### 连接远程会话

```bash
# 标准格式
remote-claude attach <session> --remote --host <host> --token <token>

# 支持 host:port 格式
remote-claude attach <session> --remote --host <host>:<port> --token <token>

# 支持 host:port/session 格式（省略 session 参数）
remote-claude attach --remote --host <host>:<port>/<session> --token <token>
```

### 远程连接排障

远程模式启动失败时，可优先查看启动日志：

- 日志文件：`~/.remote-claude/startup.log`
- 关键追溯字段：
  - `stage=server_spawn`（启动参数摘要）
  - `stage=server_start_failed`（失败阶段与原因）
  - `server_cmd_sanitized=...`（脱敏后的完整 server 启动命令）

其中 `server_cmd_sanitized` 会对敏感信息做脱敏（如 `token/password/secret`），便于排查参数传递问题而不泄露密钥。

建议排查顺序：
1. 先定位 `stage=server_start_failed` 的 `reason`
2. 再对照 `stage=server_spawn` 中的 `remote_host/remote_port`
3. 最后检查 `server_cmd_sanitized` 是否符合预期启动命令

### 保存远程连接配置

避免每次输入 host、port、token：

```bash
# 保存连接配置（默认名称: default）
remote-claude attach <session> --remote --host <host> --token <token> --save

# 保存为自定义名称
remote-claude attach <session> --remote --host <host> --token <token> --save --config-name myserver

# 使用保存的配置连接（自动加载 host/port/token）
remote-claude attach --remote
remote-claude attach --remote --config-name myserver
```

### 管理保存的连接配置

```bash
# 列出所有保存的配置
remote-claude connection list

# 查看配置详情
remote-claude connection show <name>

# 设置默认配置
remote-claude connection set-default <name>

# 删除配置
remote-claude connection delete <name>
```

### 远程管理命令

以下命令支持 `--remote` 参数：

```bash
# 列出会话
remote-claude list --remote --host <host> --token <token>

# 终止会话
remote-claude kill <session> --remote --host <host> --token <token>

# 查看状态
remote-claude status <session> --remote --host <host> --token <token>

# 获取/重新生成 token
remote-claude token <session> --remote --host <host> --token <token>
remote-claude regenerate-token <session> --remote --host <host> --token <token>

# 飞书客户端管理（远程）
remote-claude lark start --remote --host <host> --token <token>
remote-claude lark stop --remote --host <host> --token <token>
remote-claude lark status --remote --host <host> --token <token>
```

### 简化远程连接命令

```bash
# connect 命令 - 简化连接
remote-claude connect <host>:<port>/<session> --token <token>

# remote 命令 - 远程控制
remote-claude remote shutdown <host>:<port>/<session> --token <token>
remote-claude remote restart <host>:<port>/<session> --token <token>
remote-claude remote update <host>:<port>/<session> --token <token>
```

### 远程控制命令

通过 WebSocket 发送的控制命令（`server/ws_handler.py`）：

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

## 系统要求

- **操作系统**: macOS 或 Linux
- **依赖工具**: [uv](https://docs.astral.sh/uv/)、[tmux](https://github.com/tmux/tmux)
- **CLI 工具**: [Claude CLI](https://claude.ai/code) 或 [Codex CLI](https://github.com/openai/codex)
- **可选**: 飞书企业自建应用

## 文档

- [CLAUDE.md](CLAUDE.md) — 项目架构和开发说明
- [lark_client/README.md](lark_client/README.md) — 飞书客户端指南
- [tests/TEST_PLAN.md](tests/TEST_PLAN.md) — 测试计划
- [docker/README.md](docker/README.md) — Docker 测试
