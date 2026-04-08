# Remote Claude

**在电脑终端上打开的 Claude Code 进程，也可以在飞书中共享操作。**

电脑上用终端跑 Claude Code 写代码，同时在手机飞书上看进度、发指令、点按钮 — 不用守在电脑前。

## 为什么需要它？

- **飞书里直接操作** — 手机/平板打开飞书，就能看到 Claude 的实时输出
- **多端无缝切换** — 电脑上打开的 Claude 进程，手机上继续操作
- **机制安全** — 完全不侵入 Claude 进程，通过 PTY + Unix Socket 实现共享

## 快速开始

### 安装

```bash
# npm 安装（推荐）
npm install -g remote-claude

# 或 pnpm 安装
pnpm add -g remote-claude

# 或零依赖安装
curl -fsSL https://raw.githubusercontent.com/yyzybb537/remote_claude/main/scripts/install.sh | bash
```

首次运行时自动完成环境初始化：uv 安装、Python 虚拟环境创建、依赖安装。

### 启动

`remote-claude` 是公开 CLI 主入口，`cla`、`cl`、`cx`、`cdx` 是面向常用场景的快捷启动脚本。

| 命令 | CLI | 权限模式 | 用途 |
|------|-----|---------|------|
| `cla` | Claude | 默认权限模式 | 启动 Claude 会话 |
| `cl` | Claude | 跳过权限确认 | 快速启动 Claude 会话 |
| `cx` | Codex | 跳过权限确认 | 快速启动 Codex 会话 |
| `cdx` | Codex | 默认权限模式 | 启动 Codex 会话 |
| `remote-claude start <name>` | Claude/Codex | 按启动器配置执行 | 启动命名会话 |
| `remote-claude attach <name>` | Claude/Codex | 连接已有会话 | 从另一个终端接入 |

```bash
cla        # 在当前目录启动 Claude 会话
cl         # 启动 Claude，跳过权限确认
cx         # 启动 Codex，跳过权限确认
cdx        # 启动 Codex，使用默认权限模式
remote-claude start demo
remote-claude attach demo
```

### 从其他终端连接与清理

```bash
remote-claude list              # 查看所有会话
remote-claude attach <会话名>   # 连接现有会话
remote-claude uninstall         # 清理本地数据并提示 npm/pnpm 卸载命令
remote-claude uninstall --yes   # 跳过确认，直接执行清理
```

### 远程控制

当服务端已开启远程连接能力后，可通过 `--remote --host --token` 控制目标会话：

```bash
remote-claude list --remote --host 10.0.0.1 --token <token>
remote-claude status demo --remote --host 10.0.0.1 --token <token>
remote-claude kill demo --remote --host 10.0.0.1 --token <token>
remote-claude token demo --remote --host 10.0.0.1 --token <token>
remote-claude regenerate-token demo --remote --host 10.0.0.1 --token <token>
```

说明：
- 远程 `list` 当前返回的是**当前 WebSocket 入口绑定 session 的状态信息**，不是远端机器上所有会话的全局枚举。
- 远程 `status` / `kill` / `token` / `regenerate-token` 仍然要求显式传入目标 session 名称。
- 远程 `token` 返回的是当前 token 的预览值，不会直接回显完整 token。
- 远程 `regenerate-token` 会使旧 token 失效，并返回新 token 的预览值。
- 本地 `token` / `regenerate-token` 会直接输出完整 token，适合在受信任终端中执行。

## 飞书客户端

配置飞书机器人后，可在飞书中远程操作：

```bash
remote-claude lark start   # 启动飞书客户端
remote-claude lark stop    # 停止
remote-claude lark status  # 查看状态
```

飞书机器人配置详见 [docs/feishu-setup.md](docs/feishu-setup.md)。

## 更多文档

- [配置说明](docs/configuration.md) — 完整配置项说明
- [飞书配置](docs/feishu-setup.md) — 飞书机器人配置教程
- [飞书客户端](docs/feishu-client.md) — 飞书客户端管理指南
- [远程连接](docs/remote-connection.md) — 远程连接详细说明
- [CLI 参考](docs/cli-reference.md) — 完整命令参考
- [Docker 测试](docs/docker-test.md) — Docker 测试说明
- [开发者指南](docs/developer.md) — 项目结构、技术栈与开发约定

## 系统要求

- **操作系统**: macOS 或 Linux
- **依赖工具**: [tmux](https://github.com/tmux/tmux)
- **CLI 工具**: [Claude CLI](https://claude.ai/code) 或 [Codex CLI](https://github.com/openai/codex)
- **可选**: 飞书企业自建应用
