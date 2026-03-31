# 配置说明

Remote Claude 使用 JSON 格式的配置文件，支持灵活的会话管理、卡片展示和行为定制。

## 配置文件位置

| 文件 | 用途 |
|------|------|
| `~/.remote-claude/config.json` | 用户配置（快捷命令、UI 设置、行为配置） |
| `~/.remote-claude/runtime.json` | 运行时状态（会话映射、群组绑定） |
| `~/.remote-claude/remote_connections.json` | 远程连接配置（host、port、token） |
| `~/.remote-claude/tokens/<session>.json` | 会话 Token（远程模式，权限 0600） |
| `~/.remote-claude/.env` | 环境变量（飞书凭证等） |

## 配置文件结构（v2.0）

配置采用扁平化结构，分为三大模块：

```json
{
  "version": "2.0",
  "card": { ... },
  "session": { ... },
  "behavior": { ... }
}
```

### card 模块 - 卡片展示配置

控制飞书卡片的展示行为。

#### 快捷命令配置

```json
{
  "card": {
    "quick_commands": {
      "enabled": true,
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

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | boolean | 是否启用快捷命令按钮 |
| `commands` | array | 命令列表 |
| `commands[].label` | string | 按钮显示文本 |
| `commands[].value` | string | 点击后发送的命令 |
| `commands[].icon` | string | 按钮图标（emoji） |

#### 卡片过期配置

```json
{
  "card": {
    "expiry": {
      "enabled": true,
      "expiry_seconds": 3600
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | boolean | 是否启用卡片过期 |
| `expiry_seconds` | number | 过期时间（秒），默认 3600（1小时） |

卡片过期后自动创建新卡片，避免飞书卡片内容过长。

### session 模块 - 会话配置

控制会话启动和行为。

#### 权限绕过配置

```json
{
  "session": {
    "bypass": false
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `bypass` | boolean | 是否绕过权限确认（默认 false） |

#### 自定义 CLI 命令

```json
{
  "session": {
    "custom_commands": {
      "enabled": true,
      "commands": [
        {"name": "Claude", "cli_type": "claude", "command": "claude", "description": "Claude Code CLI"},
        {"name": "Codex", "cli_type": "codex", "command": "codex", "description": "OpenAI Codex CLI"}
      ]
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | boolean | 是否启用自定义命令 |
| `commands` | array | 自定义命令列表 |
| `commands[].name` | string | 命令显示名称 |
| `commands[].cli_type` | string | CLI 类型（claude/codex） |
| `commands[].command` | string | 实际执行的命令 |
| `commands[].description` | string | 命令描述 |

### behavior 模块 - 行为配置

控制自动应答、通知等行为。

#### 自动应答配置

```json
{
  "behavior": {
    "auto_answer": {
      "default_delay_seconds": 10,
      "vague_commands": [
        "继续执行", "继续", "开始执行", "开始", "执行",
        "continue", "确认", "OK"
      ],
      "vague_command_prompt": "[系统提示] 请使用工具执行下一步操作。如果不确定下一步，请明确询问需要做什么。不要只返回状态确认。"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `default_delay_seconds` | number | 自动应答延迟时间（秒） |
| `vague_commands` | array | 模糊指令列表，触发时使用 vague_command_prompt |
| `vague_command_prompt` | string | 模糊指令的系统提示 |

**自动应答策略：**
1. 优先选择标记为 `(recommended)` 或 `推荐` 的选项
2. 确认类选项回复"继续"
3. 兜底选择第一项

#### 通知配置

```json
{
  "behavior": {
    "notify": {
      "ready_enabled": true,
      "urgent_enabled": false
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `ready_enabled` | boolean | 是否启用就绪通知 |
| `urgent_enabled` | boolean | 是否启用紧急通知 |

#### 操作面板配置

```json
{
  "behavior": {
    "operation_panel": {
      "show_builtin_keys": true,
      "show_custom_commands": true,
      "enabled_keys": ["up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"],
      "random": false
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `show_builtin_keys` | boolean | 是否显示内置快捷键 |
| `show_custom_commands` | boolean | 是否显示自定义命令 |
| `enabled_keys` | array | 启用的快捷键列表 |
| `random` | boolean | 是否随机排序（调试用） |

## 环境变量配置

在 `~/.remote-claude/.env` 中配置：

```bash
# 飞书应用凭证
FEISHU_APP_ID=your_app_id
FEISHU_APP_SECRET=your_app_secret

# 日志级别（DEBUG/INFO/WARNING/ERROR）
LARK_LOG_LEVEL=INFO
```

| 配置项 | 说明 |
|--------|------|
| `FEISHU_APP_ID` | 飞书应用 ID |
| `FEISHU_APP_SECRET` | 飞书应用密钥 |
| `LARK_LOG_LEVEL` | 日志级别（DEBUG/INFO/WARNING/ERROR） |

## 配置重置

```bash
# 交互式重置
remote-claude config reset

# 重置所有配置（包括运行时状态）
remote-claude config reset --all
```

## 配置迁移

Remote Claude 支持从旧版配置格式自动迁移。首次启动新版本时，会自动将 `ui_settings` 结构转换为新的扁平化结构。

### 旧版格式（v1.x）

```json
{
  "ui_settings": {
    "quick_commands": { ... },
    "auto_answer": { ... },
    "card_expiry": { ... }
  }
}
```

### 新版格式（v2.0）

```json
{
  "version": "2.0",
  "card": {
    "quick_commands": { ... },
    "expiry": { ... }
  },
  "session": { ... },
  "behavior": {
    "auto_answer": { ... }
  }
}
```

## 配置示例

### 完整配置示例

```json
{
  "version": "2.0",
  "card": {
    "quick_commands": {
      "enabled": true,
      "commands": [
        {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
        {"label": "压缩上下文", "value": "/consume", "icon": "📦"},
        {"label": "退出会话", "value": "/exit", "icon": "🚪"},
        {"label": "帮助", "value": "/help", "icon": "❓"}
      ]
    },
    "expiry": {
      "enabled": true,
      "expiry_seconds": 3600
    }
  },
  "session": {
    "bypass": false,
    "custom_commands": {
      "enabled": true,
      "commands": [
        {"name": "Claude", "cli_type": "claude", "command": "claude", "description": "Claude Code CLI"},
        {"name": "Codex", "cli_type": "codex", "command": "codex", "description": "OpenAI Codex CLI"}
      ]
    }
  },
  "behavior": {
    "auto_answer": {
      "default_delay_seconds": 10,
      "vague_commands": [
        "继续执行", "继续", "开始执行", "开始", "执行",
        "continue", "确认", "OK"
      ],
      "vague_command_prompt": "[系统提示] 请使用工具执行下一步操作。"
    },
    "notify": {
      "ready_enabled": true,
      "urgent_enabled": false
    },
    "operation_panel": {
      "show_builtin_keys": true,
      "show_custom_commands": true,
      "enabled_keys": ["up", "down", "ctrl_o", "shift_tab", "esc"]
    }
  }
}
```

### 最小配置示例

```json
{
  "version": "2.0",
  "card": {
    "quick_commands": { "enabled": false },
    "expiry": { "enabled": false }
  },
  "session": {
    "bypass": false,
    "custom_commands": { "enabled": false }
  },
  "behavior": {
    "auto_answer": { "default_delay_seconds": 10 }
  }
}
```
