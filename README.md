# Remote Claude

在电脑终端运行 Claude Code / Codex CLI 的同时，也能在飞书中共享查看、继续操作同一个会话。

## 为什么需要它

Claude Code / Codex CLI 原本只能在启动它的那个终端里继续操作。离开电脑后，进度能看，交互却会中断。Remote Claude 把同一个会话共享到飞书和其他终端，让你在不同设备之间无缝续上：

- 电脑上开好的 Claude / Codex，会后、通勤中、离开工位时，仍可在飞书里继续操作
- 飞书里发出的消息、选项点击、权限确认，会直接作用在同一个 CLI 会话上
- 回到电脑前，可以再用 `attach` 接回同一个会话，不需要重新开始
- 多个终端与飞书可以共享同一个会话，适合本机、SSH、移动端来回切换

## 飞书端体验

飞书端不是简单转发消息，而是针对 CLI 交互做了完整映射：

- 实时流式输出，Claude 边生成边更新卡片
- ANSI 颜色尽量保留，代码和状态更容易看清
- 选项选择、权限确认可直接点按钮完成
- 后台 agent 状态可在飞书里查看和管理

## Quickstart

### 1. 安装

二选一，安装完成后重启 shell：

#### npm 安装

```bash
# 若使用 pnpm，需允许 hook 执行以初始化环境
npm install remote-claude
```

#### 源码安装

```bash
git clone https://github.com/yyzybb537/remote_claude.git
cd remote_claude
./scripts/install.sh
```

### 2. 启动会话

| 命令              | 说明                                       |
|-------------------|--------------------------------------------|
| `cla`             | 启动 Claude（需确认权限）                  |
| `cl`              | 启动 Claude（跳过权限确认）                |
| `cx`              | 启动 Codex（跳过权限确认）                 |
| `cdx`             | 启动 Codex（需确认权限）                   |
| `remote-claude`   | 管理命令，详见 -h                          |

### 3. 从其他终端继续操作

```bash
remote-claude list
remote-claude attach <会话名>
```

### 4. 配置并连接飞书

飞书机器人配置与使用说明见：

- [docs/feishu-setup.md](./docs/feishu-setup.md) — 飞书应用与机器人配置
- [docs/feishu-client.md](./docs/feishu-client.md) — 飞书客户端使用说明

## 文档

- [docs/configuration.md](./docs/configuration.md) — 配置说明与环境变量
- [docs/remote-connection.md](./docs/remote-connection.md) — 远程连接与共享会话说明
- [docs/cli-reference.md](./docs/cli-reference.md) — CLI 命令参考
- [docs/developer.md](./docs/developer.md) — 开发者总览
- [docker/README.md](./docker/README.md) — Docker 测试与镜像验证
- [tests/README.md](./tests/README.md) — 测试入口与说明
