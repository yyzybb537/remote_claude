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

| 命令 | CLI | 权限模式 | 用途 |
|------|-----|---------|------|
| `cla` | Claude | 正常 | 启动 Claude 会话 |
| `cl` | Claude | 跳过确认 | 快速启动 Claude |
| `cx` | Codex | 跳过确认 | 快速启动 Codex |
| `cdx` | Codex | 正常 | 启动 Codex 会话 |

```bash
cla        # 在当前目录启动 Claude 会话
cl         # 启动 Claude，跳过权限确认
cx         # 启动 Codex，跳过权限确认
cdx        # 启动 Codex，需确认权限
```

### 从其他终端连接

```bash
remote-claude list              # 查看所有会话
remote-claude attach <会话名>   # 连接现有会话
```

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

## 系统要求

- **操作系统**: macOS 或 Linux
- **依赖工具**: [uv](https://docs.astral.sh/uv/)、[tmux](https://github.com/tmux/tmux)
- **CLI 工具**: [Claude CLI](https://claude.ai/code) 或 [Codex CLI](https://github.com/openai/codex)
- **可选**: 飞书企业自建应用
