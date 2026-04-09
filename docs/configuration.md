# 配置说明

本文档只覆盖配置文件、环境变量与配置重置。

命令用法请看 [CLI 参考](cli-reference.md)，飞书接入请看 [feishu-setup.md](feishu-setup.md)，飞书客户端运行与排障请看 [feishu-client.md](feishu-client.md)，远程连接请看对应专题文档。

## 配置文件位置

| 文件 | 用途 |
|------|------|
| `~/.remote-claude/settings.json` | 用户设置（启动器、卡片、会话等） |
| `~/.remote-claude/state.json` | 运行时状态（会话映射、飞书绑定） |
| `~/.remote-claude/.env` | 环境变量（飞书凭证等） |
| `~/.remote-claude/remote_connections.json` | 远程连接配置（host、port、token） |
| `~/.remote-claude/tokens/<session>.json` | 会话 Token（远程模式，权限 0600） |

## 配置文件结构

```json
{
  "version": "1.0",
  "launchers": [...],
  "card": { ... },
  "session": { ... },
  "notify": { ... },
  "ui": { ... }
}
```

### launchers - 启动器配置

定义可用的 CLI 启动器：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 启动器名称，用于 `--launcher` 参数 |
| `cli_type` | string | CLI 类型（claude/codex） |
| `command` | string | 实际执行的命令 |
| `desc` | string | 描述（可选） |

```json
{"name": "Claude", "cli_type": "claude", "command": "claude", "desc": "Claude Code CLI"}
```

### card - 卡片展示配置

| 字段 | 类型 | 说明 |
|------|------|------|
| `quick_commands` | array | 快捷命令列表 |
| `expiry_sec` | number | 卡片过期时间（秒），默认 3600 |

快捷命令字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `label` | string | 按钮显示文本 |
| `value` | string | 点击后发送的命令（必须以 `/` 开头） |
| `icon` | string | 按钮图标（emoji） |

卡片过期后自动创建新卡片，避免飞书卡片内容过长。

### session - 会话配置

| 字段 | 类型 | 说明 |
|------|------|------|
| `bypass` | boolean | 是否绕过权限确认（默认 false） |
| `auto_answer_delay_sec` | number | 自动应答延迟时间（秒），默认 5 |
| `auto_answer_vague_patterns` | array | 确认类回复内容池，自动应答时随机选择一个 |
| `auto_answer_vague_prompt` | string | 追加到自动应答后的系统提示 |

**自动应答策略：**
1. 优先选择标记为 `(recommended)` 或 `推荐` 的选项
2. 确认类选项（Yes/OK/继续等）：从 `patterns` 随机选择，追加 `prompt`
3. 兜底选择第一项

### notify - 通知配置

| 字段 | 类型 | 说明 |
|------|------|------|
| `ready` | boolean | 是否启用就绪通知（默认 true） |
| `urgent` | boolean | 是否启用紧急通知（默认 false） |

### ui - UI 配置

| 字段 | 类型 | 说明 |
|------|------|------|
| `show_builtin_keys` | boolean | 是否显示内置快捷键（默认 true） |
| `enabled_keys` | array | 启用的快捷键列表 |
| `enter_to_submit` | boolean | Enter 键是否提交消息（默认 true） |

可用快捷键：`up`, `down`, `ctrl_o`, `shift_tab`, `esc`, `shift_tab_x3`（三击 Shift+Tab）

## 环境变量配置

在 `~/.remote-claude/.env` 中配置：

| 配置项 | 说明 |
|--------|------|
| `FEISHU_APP_ID` | 飞书应用 ID（必填） |
| `FEISHU_APP_SECRET` | 飞书应用密钥（必填） |
| `ENABLE_USER_WHITELIST` | 是否启用用户白名单（true/false） |
| `ALLOWED_USERS` | 用户白名单（逗号分隔） |
| `GROUP_NAME_PREFIX` | 群聊名称前缀 |
| `LARK_LOG_LEVEL` | 飞书客户端日志级别（DEBUG/INFO/WARNING/ERROR） |
| `MAX_CARD_BLOCKS` | 单张卡片最大 block 数 |
| `LARK_NO_PROXY` | 检测到 SOCKS 代理时是否绕过（0/1） |

## 需重启生效的配置项

修改以下配置项后，需执行 `remote-claude lark restart` 重启飞书客户端：

| 配置项 | 来源 |
|--------|------|
| `auto_answer_delay_sec` | settings.json |
| `auto_answer_vague_patterns` | settings.json |
| `auto_answer_vague_prompt` | settings.json |
| `notify.ready` | settings.json |
| `notify.urgent` | settings.json |
| `LARK_LOG_LEVEL` | .env |
| `MAX_CARD_BLOCKS` | .env |

## 配置重置

```bash
remote-claude config reset              # 交互式重置
remote-claude config reset --all        # 重置所有配置（包括运行时状态）
remote-claude config reset --settings   # 仅重置用户配置
remote-claude config reset --state      # 仅重置运行时状态
```

## 完整配置示例

```json
{
  "version": "1.0",
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
    "auto_answer_delay_sec": 5,
    "auto_answer_vague_patterns": [
      "继续执行", "继续", "开始执行", "开始", "执行", "continue", "确认", "OK"
    ],
    "auto_answer_vague_prompt": "[系统提示] 请使用工具执行下一步操作。如果不确定下一步，请明确询问需要做什么。不要只返回状态确认。"
  },
  "notify": {"ready": true, "urgent": false},
  "ui": {
    "show_builtin_keys": true,
    "enabled_keys": ["up", "down", "ctrl_o", "shift_tab", "esc"]
  }
}
```

**最小配置：**

```json
{"version": "1.0", "launchers": [{"name": "Claude", "cli_type": "claude", "command": "claude"}]}
```
