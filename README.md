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

以下安装方式 3 选 1，安装后重启 shell 生效

#### 方式一：npm 安装（推荐）

```bash
npm install -g remote-claude
```

安装时会自动：
- 安装 uv 包管理器
- 创建 Python 虚拟环境
- 安装所有 Python 依赖

#### 方式二：pnpm 安装

```bash
pnpm add -g remote-claude
```

与 npm 安装相同，会自动完成 Python 环境初始化。

#### 方式三：零依赖安装

项目自带便携式 Python 环境，无需预装 Python：

```bash
# 方式一：一键安装脚本
curl -fsSL https://raw.githubusercontent.com/yyzybb537/remote_claude/main/scripts/install.sh | bash

# 方式二：克隆后安装
git clone https://github.com/yyzybb537/remote_claude.git
cd remote_claude
./scripts/install.sh
```

安装脚本会自动：
- 安装 uv 包管理器
- 下载并配置 Python（版本由 `.python-version` 文件指定，便携式，不影响系统）
- 创建虚拟环境并安装依赖

### 1.2 传统安装（需要预装 Python）

```bash
git clone https://github.com/yyzybb537/remote_claude.git
cd remote_claude
./init.sh
```

`init.sh` 会自动安装 uv、tmux 等依赖，配置飞书环境（可选），并写入 `cla` / `cl` / `cx` / `cdx` 快捷命令。执行完成后重启终端生效。

### 1.3 Docker 产物安装（免安装环境）

如果你已经运行过 Docker 测试，可以直接使用产物，无需任何安装：

```bash
# 构建 Docker 镜像并运行测试
docker-compose -f docker/docker-compose.test.yml build
docker-compose -f docker/docker-compose.test.yml run npm-test /project/docker/scripts/docker-test.sh

# 测试完成后，产物位于 test-results/npm-install/
cd test-results/npm-install/node_modules/remote-claude

# 直接使用（产物已包含便携式 Python 环境）
./bin/cla                    # 启动 Claude 会话
uv run python3 remote_claude.py --help  # 查看帮助
```

**产物说明**：
- `.venv/` — 便携式 Python 虚拟环境，无需预装 Python
- `bin/cla`, `bin/cl`, `bin/cx`, `bin/cdx` — 快捷启动脚本
- 完整项目代码，可直接使用

> **前置要求**：tmux、git、Claude CLI 或 Codex CLI

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

1. 登录[飞书开放平台](https://open.feishu.cn/)，创建企业自建应用
2. 获取 **App ID** 和 **App Secret**
3. 用`cla`或`cl`启动一次claude(或用cx或cdx启动一次codex), 按照交互提示填入**App ID** 和 **App Secret**
4. [飞书开放平台]的企业自建应用页面`添加应用能力`（机器人能力）
5. 企业自建应用页面配置事件回调（如果第3步没启动成功这里配置不了）：
  - `事件与回调` -> `事件配置` -> `订阅方式`右边的笔图标 -> `选择：使用长连接接收事件` -> `点击保存` -> `下面添加事件: 接收消息 v2.0 (im.message.receive_v1)`
  - `事件与回调` -> `回调配置` -> `订阅方式`右边的笔图标 -> `选择：使用长连接接收回调` -> `点击保存` -> `下面添加回调: 卡片回传交互 (card.action.trigger)`
6. 企业自建应用页面配置权限：
  - `权限管理` -> `批量导入/导出权限` -> 导入以下内容
```json
{
  "scopes": {
    "tenant": [
      "base:app:read",
      "base:field:read",
      "base:form:read",
      "base:record:read",
      "base:record:retrieve",
      "base:table:read",
      "board:whiteboard:node:read",
      "calendar:calendar.free_busy:read",
      "cardkit:card:write",
      "contact:contact.base:readonly",
      "contact:user.employee_id:readonly",
      "contact:user.id:readonly",
      "docs:document.comment:read",
      "docs:document.content:read",
      "docs:document.media:download",
      "docs:document.media:upload",
      "docs:document:import",
      "docs:permission.member:auth",
      "docs:permission.member:create",
      "docs:permission.member:transfer",
      "docx:document.block:convert",
      "docx:document:create",
      "docx:document:readonly",
      "docx:document:write_only",
      "drive:drive.metadata:readonly",
      "drive:drive.search:readonly",
      "drive:drive:version:readonly",
      "drive:file:download",
      "drive:file:upload",
      "im:chat.members:read",
      "im:chat.members:write_only",
      "im:chat.tabs:read",
      "im:chat.tabs:write_only",
      "im:chat.top_notice:write_only",
      "im:chat:create",
      "im:chat:delete",
      "im:chat:operate_as_owner",
      "im:chat:read",
      "im:chat:update",
      "im:message.group_at_msg:readonly",
      "im:message.group_msg",
      "im:message.p2p_msg:readonly",
      "im:message.reactions:read",
      "im:message.reactions:write_only",
      "im:message.urgent",
      "im:message.urgent.status:write",
      "im:message:readonly",
      "im:message:recall",
      "im:message:send_as_bot",
      "im:message:update",
      "im:resource",
      "sheets:spreadsheet.meta:read",
      "sheets:spreadsheet.meta:write_only",
      "sheets:spreadsheet:create",
      "sheets:spreadsheet:read",
      "sheets:spreadsheet:write_only",
      "space:document:delete",
      "space:document:retrieve",
      "wiki:wiki:readonly"
    ],
    "user": [
      "base:app:read",
      "base:field:read",
      "base:record:read",
      "base:record:retrieve",
      "base:table:read",
      "calendar:calendar.event:create",
      "calendar:calendar.event:delete",
      "calendar:calendar.event:read",
      "calendar:calendar.event:reply",
      "calendar:calendar.event:update",
      "calendar:calendar.free_busy:read",
      "calendar:calendar:read",
      "cardkit:card:write",
      "contact:user.base:readonly",
      "contact:user.employee_id:readonly",
      "contact:user.id:readonly",
      "docs:document.comment:read",
      "docs:document.content:read",
      "docs:document.media:download",
      "docs:document.media:upload",
      "docx:document.block:convert",
      "docx:document:create",
      "docx:document:readonly",
      "docx:document:write_only",
      "im:chat.managers:write_only",
      "im:chat.members:read",
      "im:chat.members:write_only",
      "im:chat.tabs:read",
      "im:chat.tabs:write_only",
      "im:chat.top_notice:write_only",
      "im:chat:delete",
      "im:chat:read",
      "im:chat:update",
      "im:message.reactions:read",
      "im:message.reactions:write_only",
      "im:message:readonly",
      "im:message:recall",
      "im:message:update",
      "search:docs:read",
      "sheets:spreadsheet.meta:read",
      "sheets:spreadsheet.meta:write_only",
      "sheets:spreadsheet:create",
      "sheets:spreadsheet:read",
      "sheets:spreadsheet:write_only",
      "space:document:retrieve",
      "task:task:read",
      "task:task:readonly",
      "task:task:write",
      "task:task:writeonly",
      "task:tasklist:read",
      "wiki:wiki:readonly"
    ]
  }
}
```
7. 企业自建应用页面: `创建版本` -> `发布到线上`
8. 至此，完成飞书机器人配置

#### 4.2 通过飞书机器人操作claude/codex

1. 从飞书搜索刚刚创建的飞书机器人（第一次搜比较慢，如果搜不到可能是忘记发布了）
2. 飞书中与机器人对话，可用命令:
  - `/menu` 展示菜单卡片，后续操作都操作这个卡片上的按钮即可

### 卸载

```bash
npm uninstall -g remote-claude
# 或
pnpm uninstall -g remote-claude
```

卸载时会：
- 删除快捷命令符号链接
- 停止飞书客户端
- 清理虚拟环境
- 询问是否保留配置文件

如需完全清理（包括 uv 缓存），运行：
```bash
remote-claude config reset --all
```

## 使用指南

### 快捷命令

| 命令 | 说明 |
|------|------|
| `cla` | 启动飞书客户端 + 以当前目录路径为会话名启动 Claude |
| `cl` | 同 `cla`，但跳过权限确认 |
| `cx` | 启动飞书客户端 + 以当前目录路径为会话名启动 Codex（跳过权限确认）|
| `cdx` | 同 `cx`，但需要确认权限 |

### 管理命令

```bash
remote-claude start <会话名>     # 启动新会话
remote-claude attach <会话名>    # 连接现有会话
remote-claude list               # 查看所有会话
remote-claude kill <会话名>      # 终止会话
remote-claude status <会话名>    # 查看会话状态
remote-claude stats              # 查看使用统计
remote-claude update             # 更新到最新版本
```

### 飞书客户端

```bash
remote-claude lark start         # 启动（后台运行）
remote-claude lark stop          # 停止
remote-claude lark restart       # 重启
remote-claude lark status        # 查看状态
```

飞书中与机器人对话，可用命令：`/menu`、`/attach`、`/detach`、`/list`、`/help` 等。

### 配置重置

如果配置文件损坏或需要恢复默认设置：

```bash
remote-claude config reset          # 交互式选择重置范围
remote-claude config reset --all    # 重置全部配置文件
remote-claude config reset --config # 仅重置用户配置（config.json）
remote-claude config reset --runtime # 仅重置运行时配置（runtime.json）
```

### 使用统计

查看使用统计数据：

```bash
remote-claude stats                 # 查看今日统计
remote-claude stats --range 7d      # 查看近 7 天统计
remote-claude stats --range 30d     # 查看近 30 天统计
remote-claude stats --detail        # 显示详细分类
remote-claude stats --session <name> # 按会话名筛选
```

## 高级配置

### 配置文件

Remote Claude 使用两个配置文件：

| 文件 | 用途 | 说明 |
|------|------|------|
| `~/.remote-claude/config.json` | 用户配置 | 存储用户可编辑的 UI 设置（如快捷命令配置） |
| `~/.remote-claude/runtime.json` | 运行时状态 | 存储程序自动管理的状态（会话映射、飞书群组绑定） |

**config.json 结构示例**：
```json
{
  "version": "1.0",
  "ui_settings": {
    "quick_commands": {
      "enabled": false,
      "commands": [
        {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
        {"label": "压缩上下文", "value": "/consume", "icon": "📦"},
        {"label": "退出会话", "value": "/exit", "icon": "🚪"},
        {"label": "帮助", "value": "/help", "icon": "❓"}
      ]
    }
  }
}
```

**快捷命令配置说明**：
- `enabled`: 是否启用快捷命令选择器（默认 `false`）
- `commands`: 快捷命令列表，最多 20 条
- `label`: 显示名称，最长 20 字符
- `value`: 命令值，必须以 `/` 开头，最长 32 字符，不能包含空格
- `icon`: 图标 emoji（可选，为空时使用空白占位）

### 环境变量配置

在 `~/.remote-claude/.env` 中可配置以下选项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `FEISHU_APP_ID` | — | 飞书应用 ID |
| `FEISHU_APP_SECRET` | — | 飞书应用密钥 |
| `ENABLE_USER_WHITELIST` | `false` | 是否启用用户白名单 |
| `ALLOWED_USERS` | — | 白名单用户 ID，逗号分隔 |
| `LARK_LOG_LEVEL` | `WARNING` | 飞书客户端日志级别（DEBUG/INFO/WARNING/ERROR） |

### 自定义 CLI 命令

可通过 `~/.remote-claude/config.json` 中的 `custom_commands` 配置自定义 CLI 命令：

```json
{
  "ui_settings": {
    "custom_commands": {
      "enabled": true,
      "commands": [
        {"name": "claude", "command": "/usr/local/bin/claude", "description": "Claude Code CLI"},
        {"name": "codex", "command": "codex", "description": "OpenAI Codex CLI"}
      ]
    }
  }
}
```

配置后，启动会话时会使用配置中的命令路径。

### 安装 uv

init.sh 会自动检测并安装 uv，支持以下方式（按优先级）：

1. **官方脚本**（推荐）— 无需预装 Python
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **pip + PyPI** — GitHub 访问受限时
   ```bash
   pip3 install uv
   ```

3. **pip + 清华镜像** — 国内网络环境
   ```bash
   pip3 install uv -i https://pypi.tuna.tsinghua.edu.cn/simple/
   ```

4. **conda/mamba** — 已有 Anaconda 环境
   ```bash
   conda install -c conda-forge uv
   ```

5. **brew** — macOS 用户
   ```bash
   brew install uv
   ```

安装成功后，uv 路径会自动记录到 `~/.remote-claude/runtime.json`。

## 系统要求

- **操作系统**: macOS 或 Linux
- **依赖工具**: [uv](https://docs.astral.sh/uv/)、[tmux](https://github.com/tmux/tmux)
- **CLI 工具**: [Claude CLI](https://claude.ai/code) 或 [Codex CLI](https://github.com/openai/codex)
- **可选**: 飞书企业自建应用

## 文档

- [CLAUDE.md](CLAUDE.md) — 项目架构和开发说明
- [lark_client/GUIDE.md](lark_client/README.md) — 飞书客户端完整指南
- [tests/TEST_PLAN.md](tests/TEST_PLAN.md) — 测试计划
- [docker/README.md](docker/README.md) — Docker 测试（npm 包发布前验证）
