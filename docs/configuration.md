# 配置说明

Remote Claude 使用 JSON 格式的配置文件，支持灵活的会话管理、卡片展示和行为定制。

## 配置文件位置

| 文件 | 用途 |
|------|------|
| `~/.remote-claude/settings.json` | 用户设置（启动器、卡片、会话等） |
| `~/.remote-claude/state.json` | 运行时状态（会话映射、飞书绑定） |
| `~/.remote-claude/.env` | 环境变量（飞书凭证等） |
| `~/.remote-claude/remote_connections.json` | 远程连接配置（host、port、token） |
| `~/.remote-claude/tokens/<session>.json` | 会话 Token（远程模式，权限 0600） |

## 配置文件结构（v1.1）

配置采用扁平化结构，层级不大于 2：

```json
{
  "version": "1.1",
  "launchers": [...],
  "card": { ... },
  "session": { ... },
  "notify": { ... },
  "ui": { ... }
}
```

### launchers - 启动器配置

定义可用的 CLI 启动器，用于启动会话。

```json
{
  "launchers": [
    {"name": "Claude", "cli_type": "claude", "command": "claude", "desc": "Claude Code CLI"},
    {"name": "Codex", "cli_type": "codex", "command": "codex", "desc": "OpenAI Codex CLI"}
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 启动器名称，用于 `--launcher` 参数 |
| `cli_type` | string | CLI 类型（claude/codex） |
| `command` | string | 实际执行的命令 |
| `desc` | string | 描述（可选） |

### card - 卡片展示配置

控制飞书卡片的展示行为。

#### 快捷命令配置

```json
{
  "card": {
    "quick_commands": [
      {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
      {"label": "压缩上下文", "value": "/consume", "icon": "📦"},
      {"label": "退出会话", "value": "/exit", "icon": "🚪"},
      {"label": "帮助", "value": "/help", "icon": "❓"}
    ],
    "expiry_sec": 3600
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `quick_commands` | array | 快捷命令列表 |
| `quick_commands[].label` | string | 按钮显示文本 |
| `quick_commands[].value` | string | 点击后发送的命令（必须以 `/` 开头） |
| `quick_commands[].icon` | string | 按钮图标（emoji） |
| `expiry_sec` | number | 卡片过期时间（秒），默认 3600（1小时） |

卡片过期后自动创建新卡片，避免飞书卡片内容过长。

### session - 会话配置

控制会话启动和行为。

```json
{
  "session": {
    "bypass": false,
    "auto_answer_delay_sec": 10,
    "auto_answer_vague_patterns": [
      "继续执行", "继续", "开始执行", "开始", "执行",
      "continue", "确认", "OK"
    ],
    "auto_answer_vague_prompt": "[系统提示] 请使用工具执行下一步操作。"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `bypass` | boolean | 是否绕过权限确认（默认 false） |
| `auto_answer_delay_sec` | number | 自动应答延迟时间（秒） |
| `auto_answer_vague_patterns` | array | 模糊指令列表，触发时使用 vague_prompt |
| `auto_answer_vague_prompt` | string | 模糊指令的系统提示 |

**自动应答策略：**
1. 优先选择标记为 `(recommended)` 或 `推荐` 的选项
2. 确认类选项回复"继续"
3. 兜底选择第一项

### notify - 通知配置

```json
{
  "notify": {
    "ready": true,
    "urgent": false
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `ready` | boolean | 是否启用就绪通知 |
| `urgent` | boolean | 是否启用紧急通知 |

### ui - UI 配置

```json
{
  "ui": {
    "show_builtin_keys": true,
    "show_launchers": ["Claude", "Codex"],
    "enabled_keys": ["up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `show_builtin_keys` | boolean | 是否显示内置快捷键 |
| `show_launchers` | array | 显示在操作面板的启动器名称列表 |
| `enabled_keys` | array | 启用的快捷键列表 |

## 环境变量配置

在 `~/.remote-claude/.env` 中配置：

```bash
# === 必填 ===
FEISHU_APP_ID=your_app_id
FEISHU_APP_SECRET=your_app_secret

# === 可选 ===
USER_WHITELIST=user1,user2
GROUP_PREFIX=Remote-Claude
LOG_LEVEL=INFO
STARTUP_TIMEOUT=5
MAX_CARD_BLOCKS=50
NO_PROXY=0
```

| 配置项 | 说明 |
|--------|------|
| `FEISHU_APP_ID` | 飞书应用 ID（必填） |
| `FEISHU_APP_SECRET` | 飞书应用密钥（必填） |
| `USER_WHITELIST` | 用户白名单（逗号分隔） |
| `GROUP_PREFIX` | 群聊名称前缀 |
| `LOG_LEVEL` | 日志级别（DEBUG/INFO/WARNING/ERROR） |
| `STARTUP_TIMEOUT` | 启动超时时间（秒） |
| `MAX_CARD_BLOCKS` | 卡片最大块数 |
| `NO_PROXY` | 是否禁用代理（0/1） |

## 配置重置

```bash
# 交互式重置
remote-claude config reset

# 重置所有配置（包括运行时状态）
remote-claude config reset --all
```

## 配置示例

### 完整配置示例

```json
{
  "version": "1.1",
  "launchers": [
    {"name": "Claude", "cli_type": "claude", "command": "claude", "desc": "Claude Code CLI"},
    {"name": "Codex", "cli_type": "codex", "command": "codex", "desc": "OpenAI Codex CLI"}
  ],
  "card": {
    "quick_commands": [
      {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
      {"label": "压缩上下文", "value": "/consume", "icon": "📦"},
      {"label": "退出会话", "value": "/exit", "icon": "🚪"},
      {"label": "帮助", "value": "/help", "icon": "❓"}
    ],
    "expiry_sec": 3600
  },
  "session": {
    "bypass": false,
    "auto_answer_delay_sec": 10,
    "auto_answer_vague_patterns": [
      "继续执行", "继续", "开始执行", "开始", "执行",
      "continue", "确认", "OK"
    ],
    "auto_answer_vague_prompt": "[系统提示] 请使用工具执行下一步操作。"
  },
  "notify": {
    "ready": true,
    "urgent": false
  },
  "ui": {
    "show_builtin_keys": true,
    "show_launchers": ["Claude", "Codex"],
    "enabled_keys": ["up", "down", "ctrl_o", "shift_tab", "esc"]
  }
}
```

### 最小配置示例

```json
{
  "version": "1.1",
  "launchers": [
    {"name": "Claude", "cli_type": "claude", "command": "claude"}
  ]
}
```
