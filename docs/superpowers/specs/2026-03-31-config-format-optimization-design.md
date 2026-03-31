# 配置文件优化设计

## 概述

优化 `resources/defaults/` 目录下的配置格式，减少认知成本，提升可维护性。

## 设计原则

1. **层级不大于 2** — 顶层模块 + 配置项，最多一层嵌套（动态 key 的映射表可接受 3 层）
2. **语义分组** — 相关配置放在一起，每个模块职责单一
3. **命名对应** — `Settings` ↔ `settings.json`，`State` ↔ `state.json`，`EnvConfig` ↔ `env`
4. **后缀统一** — 模板文件统一使用 `.json.example` 后缀

## 文件命名

| 原名 | 新名 | 代码类 |
|------|------|--------|
| `config.default.json` | `settings.json.example` | `Settings` |
| `runtime.default.json` | `state.json.example` | `State` |
| `.env.example` | `env.example` | `EnvConfig` |

## settings.json 结构

用户可编辑配置，存储于 `~/.remote-claude/settings.json`。

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
    "auto_answer_vague_patterns": ["继续执行", "继续", "开始执行", "开始", "执行", "continue", "确认", "OK"],
    "auto_answer_vague_prompt": "[系统提示] 请使用工具执行下一步操作。如果不确定下一步，请明确询问需要做什么。不要只返回状态确认。"
  },
  "notify": {
    "ready": true,
    "urgent": false
  },
  "ui": {
    "show_builtin_keys": true,
    "show_launchers": ["Claude", "Codex"],
    "enabled_keys": ["up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"]
  }
}
```

### 字段说明

#### launchers（顶层）

启动器配置，定义可用的 CLI 工具。

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 启动器名称，用于 `--launcher` 参数映射 |
| `cli_type` | string | CLI 类型（claude/codex），用于解析器选择 |
| `command` | string | 实际执行的命令 |
| `desc` | string | 描述信息，显示在操作面板 |

#### card

飞书卡片相关配置。

| 字段 | 类型 | 说明 |
|------|------|------|
| `quick_commands` | array | 快捷命令列表，直接在顶层（无中间层） |
| `expiry_sec` | number | 卡片过期时间（秒），过期后创建新卡片 |

#### session

会话相关配置。

| 字段 | 类型 | 说明 |
|------|------|------|
| `bypass` | boolean | 是否绕过权限确认 |
| `auto_answer_delay_sec` | number | 自动应答延迟时间（秒） |
| `auto_answer_vague_patterns` | array | 模糊指令模式列表 |
| `auto_answer_vague_prompt` | string | 模糊指令的系统提示 |

#### notify

通知配置。

| 字段 | 类型 | 说明 |
|------|------|------|
| `ready` | boolean | 是否启用就绪通知 |
| `urgent` | boolean | 是否启用紧急通知 |

#### ui

UI 展示配置。

| 字段 | 类型 | 说明 |
|------|------|------|
| `show_builtin_keys` | boolean | 是否显示内置快捷键 |
| `show_launchers` | array | 展示的启动器名称列表（值为 `launchers[].name`） |
| `enabled_keys` | array | 启用的快捷键列表 |

## state.json 结构

程序运行时状态，存储于 `~/.remote-claude/state.json`。

```json
{
  "version": "1.1",
  "uv_path": null,
  "sessions": {
    "myapp": {
      "path": "/path/to/myapp",
      "lark_chat_id": "chat_xxx",
      "auto_answer_enabled": true,
      "auto_answer_count": 3
    }
  },
  "ready_notify_count": 0
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `version` | string | 配置版本 |
| `uv_path` | string | uv 可执行文件路径 |
| `sessions` | object | 会话状态映射，key 为会话名 |
| `sessions[].path` | string | 会话原始路径 |
| `sessions[].lark_chat_id` | string | 绑定的飞书群 chat_id |
| `sessions[].auto_answer_enabled` | boolean | 自动应答是否启用 |
| `sessions[].auto_answer_count` | number | 自动应答计数 |
| `ready_notify_count` | number | 全局就绪通知计数 |

## env.example 结构

环境变量配置，存储于 `~/.remote-claude/.env`。

```bash
# Remote Claude 环境变量配置

# === 必填 ===
FEISHU_APP_ID=
FEISHU_APP_SECRET=

# === 可选 ===
USER_WHITELIST=
GROUP_PREFIX=Remote-Claude
LOG_LEVEL=INFO
STARTUP_TIMEOUT=5
MAX_CARD_BLOCKS=50
NO_PROXY=0
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `FEISHU_APP_ID` | string | 是 | 飞书应用 ID |
| `FEISHU_APP_SECRET` | string | 是 | 飞书应用密钥 |
| `USER_WHITELIST` | string | 否 | 用户白名单（逗号分隔） |
| `GROUP_PREFIX` | string | 否 | 群名前缀，默认 `Remote-Claude` |
| `LOG_LEVEL` | string | 否 | 日志级别：DEBUG/INFO/WARNING/ERROR |
| `STARTUP_TIMEOUT` | number | 否 | 启动超时（秒），默认 5 |
| `MAX_CARD_BLOCKS` | number | 否 | 最大卡片 block 数，默认 50 |
| `NO_PROXY` | boolean | 否 | 是否绕过代理，默认 0 |

## 代码类设计

### Settings（settings.json）

```python
@dataclass
class Launcher:
    """启动器配置"""
    name: str           # 名称，用于 CLI 参数映射
    cli_type: str       # CLI 类型（claude/codex）
    command: str        # 执行命令
    desc: str = ""      # 描述

@dataclass
class CardSettings:
    """卡片设置"""
    quick_commands: List[QuickCommand]
    expiry_sec: int

@dataclass
class SessionSettings:
    """会话设置"""
    bypass: bool
    auto_answer_delay_sec: int
    auto_answer_vague_patterns: List[str]
    auto_answer_vague_prompt: str

@dataclass
class NotifySettings:
    """通知设置"""
    ready: bool
    urgent: bool

@dataclass
class UiSettings:
    """UI 设置"""
    show_builtin_keys: bool
    show_launchers: List[str]
    enabled_keys: List[str]

@dataclass
class Settings:
    """用户设置"""
    version: str
    launchers: List[Launcher]
    card: CardSettings
    session: SessionSettings
    notify: NotifySettings
    ui: UiSettings
```

### State（state.json）

```python
@dataclass
class SessionState:
    """会话状态"""
    path: str
    lark_chat_id: Optional[str]
    auto_answer_enabled: bool
    auto_answer_count: int

@dataclass
class State:
    """运行时状态"""
    version: str
    uv_path: Optional[str]
    sessions: Dict[str, SessionState]
    ready_notify_count: int
```

### EnvConfig（env）

```python
@dataclass
class EnvConfig:
    """环境变量配置"""
    # 必填
    feishu_app_id: str
    feishu_app_secret: str
    # 可选
    user_whitelist: List[str]
    group_prefix: str = "Remote-Claude"
    log_level: str = "INFO"
    startup_timeout: int = 5
    max_card_blocks: int = 50
    no_proxy: bool = False
```

## CLI 变更

### start 命令

移除 `--cli` 参数，改用 `--launcher` 参数：

```bash
# 旧方式
remote-claude start mywork --cli codex

# 新方式
remote-claude start mywork --launcher Codex
# 或简写
remote-claude start mywork -l Codex
# 不指定时使用第一个 launcher
remote-claude start mywork
```

## 字段命名对照表

### settings.json

| 原字段 | 新字段 | 说明 |
|--------|--------|------|
| `session.custom_commands` | `launchers`（顶层） | 启动器配置，移到顶层 |
| `quick_commands.commands` | `quick_commands` | 去掉中间层 |
| `expiry_seconds` | `expiry_sec` | 统一简写 |
| `default_delay_seconds` | `auto_answer_delay_sec` | 统一简写，加前缀 |
| `vague_commands` | `auto_answer_vague_patterns` | 更准确语义，加前缀 |
| `vague_command_prompt` | `auto_answer_vague_prompt` | 加前缀 |
| `description` | `desc` | 简化 |
| `ready_enabled` | `ready` | 去掉冗余后缀 |
| `urgent_enabled` | `urgent` | 去掉冗余后缀 |
| `show_custom_commands` | `show_launchers` | 语义更准确，改为列表 |
| `behavior.auto_answer` | `session.auto_answer_*` | 移到 session，扁平化 |
| `behavior.notify` | `notify`（顶层） | 独立模块 |
| `behavior.operation_panel` | `ui`（顶层） | 更准确的语义命名 |

### state.json

| 原字段 | 新字段 | 说明 |
|--------|--------|------|
| `session_mappings` | `sessions.myapp.path` | 归组到 sessions |
| `session_auto_answer` | `sessions.myapp.auto_answer_*` | 归组到 sessions，扁平化 |
| `lark_group_mappings` | `sessions.myapp.lark_chat_id` | 合并到 sessions |

### env.example

| 原字段 | 新字段 | 说明 |
|--------|--------|------|
| `ENABLE_USER_WHITELIST` + `ALLOWED_USERS` | `USER_WHITELIST` | 合并为单一配置 |
| `GROUP_NAME_PREFIX` | `GROUP_PREFIX` | 简化命名 |
| `LARK_LOG_LEVEL` + `SERVER_LOG_LEVEL` | `LOG_LEVEL` | 统一日志级别 |
| `LARK_NO_PROXY` | `NO_PROXY` | 去掉 `LARK_` 前缀 |
