# Remote Claude

**在电脑终端上打开的 Claude Code 进程，也可以在飞书中共享操作。电脑端、手机端无缝来回切换**

电脑上用终端跑 Claude Code 写代码，同时在手机飞书上看进度、发指令、点按钮 — 不用守在电脑前，随时随地掌控 AI 编程。

## 为什么需要它？

Claude Code 只能在启动它的那个终端窗口里操作。一旦离开电脑，就只能干等。Remote Claude 让你：

- **飞书里直接操作** — 手机/平板打开飞书，就能看到 Claude 的实时输出，发消息、选选项、批准权限，和终端里一模一样。
- **用手机无缝延续电脑上做的工作** — 电脑上打开的Claude进程，也可以用飞书共享操作，开会、午休、通勤、上厕所时，都可以用手机延续之前在电脑上的工作。
- **在电脑上也可以无缝延续手机上的工作** - 在lark端也可以打开新的Claude进程启动新的工作，回到电脑前还可以`attach`共享操作同一个Claude进程，延续手机端的工作。
- **多端共享操作** — 多个终端 + 飞书可以共享操作同一个claude/codex进程，回到家里ssh登录到服务器上也可以通过`attach`继续操作在公司ssh登录到服务器上打开的claude/codex进程操作。
- **机制安全** - 完全不侵入 Claude 进程，remote 功能完全通过终端交互来实现，不必担心 Claude 进程意外崩溃导致工作进展丢失。

## 飞书端体验

- 彩色代码输出，ANSI 着色完整还原
- 交互式按钮：选项选择、权限确认，一键点击
- 流式卡片更新：Claude 边想边输出，飞书端实时滚动显示
- 后台 agent 状态面板：查看并管理正在运行的子任务

## 快速开始

### 1. 安装

以下安装方式2选1, 安装后重启shell生效

#### 1.1 npm安装

```bash
npm install remote-claude
```

需要安装uv、tmux等依赖，第一次可能有点慢.

#### 1.2 或 源码安装

```bash
git clone https://github.com/yyzybb537/remote_claude.git
cd remote_claude
./init.sh
```

`init.sh` 会自动安装 uv、tmux 等依赖，配置飞书环境（可选），并写入 `cla` / `cl` / `cx` / `cdx` 快捷命令。执行完成后重启终端生效。

### 2. 启动

| 快捷命令 | 说明 |
|------|------|
| `cla` | 启动 Claude (以当前目录路径为会话名) |
| `cl` | 同 `cla`，但跳过权限确认 |
| `cx` | 启动 Codex (以当前目录路径为会话名，跳过权限确认) |
| `cdx` | 同 `cx`，但需要确认权限 |
| `remote-claude` | 管理工具（一般不用）|

### 3. 从其他终端连接(比较少用)

```bash
remote-claude list
remote-claude attach <会话名>
```

### 4. 从飞书端连接

#### 4.1 配置飞书机器人

运行向导，按提示操作即可（约 5 分钟）：

```bash
remote-claude lark init
```

向导会自动完成：扫码创建企业自建应用、开通所需权限、配置事件回调、写入本地配置。

> **⚠ 向导最后一步会自动弹出发布页面**，按提示创建版本并发布后才能生效。
> 未发布的应用在飞书中无法被搜索到。

#### 4.2 通过飞书机器人操作 claude/codex

1. 从飞书搜索刚创建的机器人（应用发布后才能搜到，发布约需 1 分钟生效）
2. 飞书中与机器人对话，发送 `/menu` 展示菜单卡片，后续操作点卡片上的按钮即可

## 使用指南

### 快捷命令

| 命令 | 说明 |
|------|------|
| `cla` | 启动飞书客户端 + 以当前目录路径为会话名启动 Claude |
| `cl` | 同 `cla`，但跳过权限确认 |
| `cx` | 启动飞书客户端 + 以当前目录路径为会话名启动 Codex（跳过权限确认）|
| `cdx` | 同 `cx`，但需要确认权限 |

### 管理命令 (一般不需要)

```bash
remote-claude start <会话名>     # 启动新会话
remote-claude attach <会话名>    # 连接现有会话
remote-claude list               # 查看所有会话
remote-claude kill <会话名>      # 终止会话
```

### 飞书客户端

```bash
remote-claude lark start         # 启动（后台运行）
remote-claude lark stop          # 停止
remote-claude lark restart       # 重启
remote-claude lark status        # 查看状态
```

飞书中与机器人对话，可用命令：`/menu`、`/attach`、`/detach`、`/list`、`/help` 等。

## 高级配置

在 `~/.remote-claude/.env` 中可配置以下选项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CLAUDE_COMMAND` | `claude` | 启动 Claude CLI 的命令 |
| `FEISHU_APP_ID` | — | 飞书应用 ID |
| `FEISHU_APP_SECRET` | — | 飞书应用密钥 |
| `ENABLE_USER_WHITELIST` | `false` | 是否启用用户白名单 |
| `ALLOWED_USERS` | — | 白名单用户 ID，逗号分隔 |

### 自定义 Claude CLI 命令

若你的 Claude CLI 安装方式不同，启动命令不是 `claude`，可通过 `CLAUDE_COMMAND` 指定：

```bash
# ~/.remote-claude/.env

# 使用两段式命令（如 ccr code）
CLAUDE_COMMAND=ccr code

# 使用绝对路径
CLAUDE_COMMAND=/usr/local/bin/claude
```

## 系统要求

- **操作系统**: macOS 或 Linux
- **依赖工具**: [uv](https://docs.astral.sh/uv/)、[tmux](https://github.com/tmux/tmux)
- **CLI 工具**: [Claude CLI](https://claude.ai/code) 或 [Codex CLI](https://github.com/openai/codex)
- **可选**: 飞书企业自建应用

## 文档

- [CLAUDE.md](./CLAUDE.md) — 项目架构和开发说明
- [LARK_CLIENT_GUIDE.md](./LARK_CLIENT_GUIDE.md) — 飞书客户端完整指南
- [docker/README.md](./docker/README.md) — Docker 测试（npm 包发布前验证）
