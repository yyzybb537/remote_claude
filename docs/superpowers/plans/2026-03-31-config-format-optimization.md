# 配置文件优化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构配置文件格式，统一命名、优化层级结构、新增 EnvConfig 类，提升可维护性。

**Architecture:**
- 重命名配置文件：`config.default.json` → `settings.json.example`，`runtime.default.json` → `state.json.example`，`.env.example` → `env.example`
- 重构代码类：`UserConfig` → `Settings`，`RuntimeConfig` → `State`，新增 `EnvConfig`
- 扁平化配置层级，确保层级不大于 2
- CLI 参数变更：`--cli` → `--launcher`

**Tech Stack:** Python 3.12, dataclasses, pytest

---

## 文件结构

| 文件 | 操作 | 说明 |
|------|------|------|
| `resources/defaults/settings.json.example` | 创建 | 新的用户配置模板 |
| `resources/defaults/state.json.example` | 创建 | 新的运行时状态模板 |
| `resources/defaults/env.example` | 创建 | 新的环境变量模板 |
| `resources/defaults/config.default.json` | 删除 | 旧的用户配置模板 |
| `resources/defaults/runtime.default.json` | 删除 | 旧的运行时状态模板 |
| `resources/defaults/.env.example` | 删除 | 旧的环境变量模板 |
| `utils/runtime_config.py` | 重构 | 重命名类、重构数据结构 |
| `utils/env_config.py` | 创建 | 新增 EnvConfig 类 |
| `remote_claude.py` | 修改 | CLI 参数变更 |
| `lark_client/card_builder.py` | 修改 | 适配新配置结构 |
| `lark_client/config.py` | 修改 | 适配 EnvConfig |
| `server/server.py` | 修改 | 适配新配置结构 |
| `docs/configuration.md` | 更新 | 更新配置文档 |
| `tests/test_runtime_config.py` | 重构 | 适配新测试 |
| `tests/test_env_config.py` | 创建 | EnvConfig 单元测试 |

---

## Task 1: 创建新配置模板文件

**Files:**
- Create: `resources/defaults/settings.json.example`
- Create: `resources/defaults/state.json.example`
- Create: `resources/defaults/env.example`

- [ ] **Step 1: 创建 settings.json.example**

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

- [ ] **Step 2: 创建 state.json.example**

```json
{
  "version": "1.1",
  "uv_path": null,
  "sessions": {},
  "ready_notify_count": 0
}
```

- [ ] **Step 3: 创建 env.example**

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

- [ ] **Step 4: 提交新配置模板**

```bash
git add resources/defaults/settings.json.example resources/defaults/state.json.example resources/defaults/env.example
git commit -m "feat(config): 添加新配置模板文件

- settings.json.example: 用户配置模板
- state.json.example: 运行时状态模板
- env.example: 环境变量模板

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: 重构数据类定义

**Files:**
- Modify: `utils/runtime_config.py:270-800`（数据类定义区域）

- [ ] **Step 1: 添加新的数据类定义**

在 `utils/runtime_config.py` 中添加新的数据类（保留旧类以支持迁移）：

```python
# ============== 新版数据类（v1.1）==============

SETTINGS_CURRENT_VERSION = "1.1"
STATE_CURRENT_VERSION = "1.1"


@dataclass
class Launcher:
    """启动器配置"""
    name: str           # 名称，用于 CLI 参数映射
    cli_type: str       # CLI 类型（claude/codex）
    command: str        # 执行命令
    desc: str = ""      # 描述

    def __post_init__(self):
        """验证启动器配置"""
        if not self.name:
            raise ValueError("启动器名称不能为空")
        if not self.command:
            raise ValueError("启动器命令不能为空")
        if not self.cli_type:
            raise ValueError("CLI 类型不能为空")
        try:
            CliType(self.cli_type)
        except ValueError:
            raise ValueError(f"CLI 类型必须是 {list(CliType)} 之一: {self.cli_type}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "cli_type": self.cli_type,
            "command": self.command,
            "desc": self.desc,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Launcher":
        return cls(
            name=data.get("name", ""),
            cli_type=data.get("cli_type", ""),
            command=data.get("command", ""),
            desc=data.get("desc", ""),
        )


@dataclass
class CardSettings:
    """卡片设置"""
    quick_commands: List[QuickCommand] = field(default_factory=list)
    expiry_sec: int = 3600

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quick_commands": [cmd.to_dict() for cmd in self.quick_commands],
            "expiry_sec": self.expiry_sec,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CardSettings":
        commands_data = data.get("quick_commands", [])
        commands = []
        for cmd_data in commands_data:
            try:
                commands.append(QuickCommand.from_dict(cmd_data))
            except ValueError as e:
                logger.warning(f"跳过无效快捷命令: {e}")
        return cls(
            quick_commands=commands,
            expiry_sec=data.get("expiry_sec", 3600),
        )


@dataclass
class SessionSettings:
    """会话设置"""
    bypass: bool = False
    auto_answer_delay_sec: int = 10
    auto_answer_vague_patterns: List[str] = field(default_factory=list)
    auto_answer_vague_prompt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bypass": self.bypass,
            "auto_answer_delay_sec": self.auto_answer_delay_sec,
            "auto_answer_vague_patterns": self.auto_answer_vague_patterns,
            "auto_answer_vague_prompt": self.auto_answer_vague_prompt,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionSettings":
        default_patterns = [
            "继续执行", "继续", "开始执行", "开始", "执行", "continue", "确认", "OK"
        ]
        default_prompt = (
            "[系统提示] 请使用工具执行下一步操作。"
            "如果不确定下一步，请明确询问需要做什么。"
            "不要只返回状态确认。"
        )
        return cls(
            bypass=data.get("bypass", False),
            auto_answer_delay_sec=data.get("auto_answer_delay_sec", 10),
            auto_answer_vague_patterns=data.get("auto_answer_vague_patterns", default_patterns),
            auto_answer_vague_prompt=data.get("auto_answer_vague_prompt", default_prompt),
        )


@dataclass
class NotifySettings:
    """通知设置"""
    ready: bool = True
    urgent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ready": self.ready,
            "urgent": self.urgent,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NotifySettings":
        return cls(
            ready=data.get("ready", True),
            urgent=data.get("urgent", False),
        )


@dataclass
class UiSettings:
    """UI 设置"""
    show_builtin_keys: bool = True
    show_launchers: List[str] = field(default_factory=list)
    enabled_keys: List[str] = field(default_factory=lambda: OPERATION_PANEL_DEFAULT_KEYS.copy())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "show_builtin_keys": self.show_builtin_keys,
            "show_launchers": self.show_launchers,
            "enabled_keys": self.enabled_keys,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UiSettings":
        return cls(
            show_builtin_keys=data.get("show_builtin_keys", True),
            show_launchers=data.get("show_launchers", []),
            enabled_keys=_normalize_enabled_keys(data.get("enabled_keys", OPERATION_PANEL_DEFAULT_KEYS)),
        )


@dataclass
class Settings:
    """用户设置"""
    version: str = SETTINGS_CURRENT_VERSION
    launchers: List[Launcher] = field(default_factory=list)
    card: CardSettings = field(default_factory=lambda: CardSettings())
    session: SessionSettings = field(default_factory=lambda: SessionSettings())
    notify: NotifySettings = field(default_factory=lambda: NotifySettings())
    ui: UiSettings = field(default_factory=lambda: UiSettings())

    def get_launcher(self, name: str) -> Optional[Launcher]:
        """根据名称获取启动器"""
        for launcher in self.launchers:
            if launcher.name == name:
                return launcher
        return None

    def get_default_launcher(self) -> Optional[Launcher]:
        """获取默认启动器（第一个）"""
        return self.launchers[0] if self.launchers else None

    def is_quick_commands_visible(self) -> bool:
        """判断快捷命令选择器是否应该显示"""
        return len(self.card.quick_commands) > 0

    def get_quick_commands(self) -> List[QuickCommand]:
        """获取快捷命令列表"""
        return self.card.quick_commands

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "launchers": [l.to_dict() for l in self.launchers],
            "card": self.card.to_dict(),
            "session": self.session.to_dict(),
            "notify": self.notify.to_dict(),
            "ui": self.ui.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Settings":
        launchers_data = data.get("launchers", [])
        launchers = []
        for l_data in launchers_data:
            try:
                launchers.append(Launcher.from_dict(l_data))
            except ValueError as e:
                logger.warning(f"跳过无效启动器: {e}")

        return cls(
            version=data.get("version", SETTINGS_CURRENT_VERSION),
            launchers=launchers,
            card=CardSettings.from_dict(data.get("card", {})),
            session=SessionSettings.from_dict(data.get("session", {})),
            notify=NotifySettings.from_dict(data.get("notify", {})),
            ui=UiSettings.from_dict(data.get("ui", {})),
        )


@dataclass
class SessionState:
    """会话状态"""
    path: str
    lark_chat_id: Optional[str] = None
    auto_answer_enabled: bool = False
    auto_answer_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "lark_chat_id": self.lark_chat_id,
            "auto_answer_enabled": self.auto_answer_enabled,
            "auto_answer_count": self.auto_answer_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        return cls(
            path=data.get("path", ""),
            lark_chat_id=data.get("lark_chat_id"),
            auto_answer_enabled=data.get("auto_answer_enabled", False),
            auto_answer_count=data.get("auto_answer_count", 0),
        )


@dataclass
class State:
    """运行时状态"""
    version: str = STATE_CURRENT_VERSION
    uv_path: Optional[str] = None
    sessions: Dict[str, SessionState] = field(default_factory=dict)
    ready_notify_count: int = 0

    def get_session_path(self, session_name: str) -> Optional[str]:
        """获取会话路径"""
        state = self.sessions.get(session_name)
        return state.path if state else None

    def set_session_path(self, session_name: str, path: str) -> None:
        """设置会话路径"""
        if session_name not in self.sessions:
            self.sessions[session_name] = SessionState(path=path)
        else:
            self.sessions[session_name].path = path

    def remove_session(self, session_name: str) -> bool:
        """删除会话状态"""
        if session_name in self.sessions:
            del self.sessions[session_name]
            return True
        return False

    def get_lark_chat_id(self, session_name: str) -> Optional[str]:
        """获取会话绑定的飞书群 ID"""
        state = self.sessions.get(session_name)
        return state.lark_chat_id if state else None

    def set_lark_chat_id(self, session_name: str, chat_id: str) -> None:
        """设置会话绑定的飞书群 ID"""
        if session_name not in self.sessions:
            self.sessions[session_name] = SessionState(path="")
        self.sessions[session_name].lark_chat_id = chat_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "uv_path": self.uv_path,
            "sessions": {k: v.to_dict() for k, v in self.sessions.items()},
            "ready_notify_count": self.ready_notify_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "State":
        sessions_data = data.get("sessions", {})
        sessions = {k: SessionState.from_dict(v) for k, v in sessions_data.items()}
        return cls(
            version=data.get("version", STATE_CURRENT_VERSION),
            uv_path=data.get("uv_path"),
            sessions=sessions,
            ready_notify_count=data.get("ready_notify_count", 0),
        )
```

- [ ] **Step 2: 添加辅助函数 _normalize_enabled_keys**

```python
def _normalize_enabled_keys(keys: Any) -> List[str]:
    """规范化 enabled_keys 列表"""
    if not isinstance(keys, list):
        return OPERATION_PANEL_DEFAULT_KEYS.copy()

    filtered: List[str] = []
    invalid: List[Any] = []
    for key in keys:
        if not isinstance(key, str):
            invalid.append(key)
            continue
        if key in OPERATION_PANEL_ALLOWED_KEYS and key not in filtered:
            filtered.append(key)
        elif key not in OPERATION_PANEL_ALLOWED_KEYS:
            invalid.append(key)

    if invalid:
        logger.warning(f"ui.enabled_keys 包含非法键，已忽略: {invalid}")

    if not filtered:
        return OPERATION_PANEL_DEFAULT_KEYS.copy()
    return filtered
```

- [ ] **Step 3: 运行测试验证数据类定义**

```bash
uv run python3 -c "
from utils.runtime_config import Settings, State, Launcher, SessionState
# 测试 Launcher
l = Launcher(name='Test', cli_type='claude', command='test')
assert l.name == 'Test'
# 测试 Settings
s = Settings()
assert s.version == '1.1'
print('数据类定义验证通过')
"
```

- [ ] **Step 4: 提交数据类重构**

```bash
git add utils/runtime_config.py
git commit -m "feat(config): 添加新版数据类定义

- Launcher: 启动器配置
- CardSettings/SessionSettings/NotifySettings/UiSettings: 模块设置
- Settings: 用户设置（原 UserConfig）
- SessionState/State: 运行时状态（原 RuntimeConfig）

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: 添加配置迁移逻辑

**Files:**
- Modify: `utils/runtime_config.py`（迁移函数区域）

- [ ] **Step 1: 添加旧配置到新配置的迁移函数**

```python
def migrate_settings_from_v1(user_config: "UserConfig") -> Settings:
    """从旧版 UserConfig 迁移到新版 Settings"""
    # 迁移 launchers（从 custom_commands）
    launchers = []
    if user_config.session.custom_commands.enabled:
        for cmd in user_config.session.custom_commands.commands:
            launchers.append(Launcher(
                name=cmd.name,
                cli_type=cmd.cli_type,
                command=cmd.command,
                desc=cmd.description,
            ))

    # 迁移 quick_commands（去掉中间层）
    quick_commands = user_config.card.quick_commands.commands if user_config.card.quick_commands.enabled else []

    # 迁移 session settings（扁平化 auto_answer）
    session = SessionSettings(
        bypass=user_config.session.bypass,
        auto_answer_delay_sec=user_config.behavior.auto_answer.default_delay_seconds,
        auto_answer_vague_patterns=user_config.behavior.auto_answer.vague_commands,
        auto_answer_vague_prompt=user_config.behavior.auto_answer.vague_command_prompt,
    )

    # 迁移 notify
    notify = NotifySettings(
        ready=user_config.behavior.notify.ready_enabled,
        urgent=user_config.behavior.notify.urgent_enabled,
    )

    # 迁移 ui
    ui = UiSettings(
        show_builtin_keys=user_config.behavior.operation_panel.show_builtin_keys,
        show_launchers=[cmd.name for cmd in user_config.session.custom_commands.commands]
                        if user_config.behavior.operation_panel.show_custom_commands else [],
        enabled_keys=user_config.behavior.operation_panel.enabled_keys,
    )

    return Settings(
        version=SETTINGS_CURRENT_VERSION,
        launchers=launchers,
        card=CardSettings(
            quick_commands=quick_commands,
            expiry_sec=user_config.card.expiry.expiry_seconds,
        ),
        session=session,
        notify=notify,
        ui=ui,
    )


def migrate_state_from_v1(runtime_config: "RuntimeConfig") -> State:
    """从旧版 RuntimeConfig 迁移到新版 State"""
    sessions: Dict[str, SessionState] = {}

    # 迁移 session_mappings
    for name, path in runtime_config.session_mappings.items():
        sessions[name] = SessionState(path=path)

    # 迁移 lark_group_mappings
    for chat_id, session_name in runtime_config.lark_group_mappings.items():
        if session_name in sessions:
            sessions[session_name].lark_chat_id = chat_id
        else:
            sessions[session_name] = SessionState(path="", lark_chat_id=chat_id)

    # 迁移 session_auto_answer
    for session_name, aa_data in runtime_config.session_auto_answer.items():
        if session_name in sessions:
            sessions[session_name].auto_answer_enabled = aa_data.get("enabled", False)
            sessions[session_name].auto_answer_count = aa_data.get("count", 0)
        else:
            sessions[session_name] = SessionState(
                path="",
                auto_answer_enabled=aa_data.get("enabled", False),
                auto_answer_count=aa_data.get("count", 0),
            )

    return State(
        version=STATE_CURRENT_VERSION,
        uv_path=runtime_config.uv_path,
        sessions=sessions,
        ready_notify_count=runtime_config.ready_notify_count,
    )
```

- [ ] **Step 2: 添加新版加载/保存函数**

```python
# 新版文件路径
SETTINGS_FILE = USER_DATA_DIR / "settings.json"
STATE_FILE = USER_DATA_DIR / "state.json"
SETTINGS_LOCK_FILE = USER_DATA_DIR / "settings.json.lock"
STATE_LOCK_FILE = USER_DATA_DIR / "state.json.lock"


def load_settings() -> Settings:
    """加载用户设置"""
    _ensure_filesystem_checked()

    # 优先加载新版配置
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Settings.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"settings.json 损坏: {e}")
            _backup_corrupted_file(SETTINGS_FILE, SETTINGS_LOCK_FILE)

    # 尝试从旧版迁移
    if USER_CONFIG_FILE.exists():
        try:
            old_config = load_user_config()
            new_settings = migrate_settings_from_v1(old_config)
            save_settings(new_settings)
            logger.info("已从旧版 config.json 迁移到 settings.json")
            return new_settings
        except Exception as e:
            logger.warning(f"旧版配置迁移失败: {e}")

    # 返回默认配置
    return Settings()


def save_settings(settings: Settings) -> None:
    """保存用户设置"""
    _update_config_with_lock(
        SETTINGS_FILE,
        SETTINGS_LOCK_FILE,
        settings.to_dict(),
        "settings"
    )


def load_state() -> State:
    """加载运行时状态"""
    _ensure_filesystem_checked()

    # 优先加载新版状态
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return State.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"state.json 损坏: {e}")
            _backup_corrupted_file(STATE_FILE, STATE_LOCK_FILE)

    # 尝试从旧版迁移
    if RUNTIME_CONFIG_FILE.exists():
        try:
            old_state = load_runtime_config()
            new_state = migrate_state_from_v1(old_state)
            save_state(new_state)
            logger.info("已从旧版 runtime.json 迁移到 state.json")
            return new_state
        except Exception as e:
            logger.warning(f"旧版状态迁移失败: {e}")

    # 返回默认状态
    return State()


def save_state(state: State) -> None:
    """保存运行时状态"""
    _update_config_with_lock(
        STATE_FILE,
        STATE_LOCK_FILE,
        state.to_dict(),
        "state"
    )
```

- [ ] **Step 3: 运行迁移测试**

```bash
uv run python3 -c "
from utils.runtime_config import (
    load_settings, load_state, Settings, State,
    load_user_config, load_runtime_config
)
# 测试迁移逻辑（如果存在旧配置）
s = load_settings()
assert isinstance(s, Settings)
st = load_state()
assert isinstance(st, State)
print('配置迁移逻辑验证通过')
"
```

- [ ] **Step 4: 提交迁移逻辑**

```bash
git add utils/runtime_config.py
git commit -m "feat(config): 添加配置迁移逻辑

- migrate_settings_from_v1: 旧版 UserConfig → Settings
- migrate_state_from_v1: 旧版 RuntimeConfig → State
- load_settings/save_settings: 新版用户设置读写
- load_state/save_state: 新版运行时状态读写

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: 创建 EnvConfig 类

**Files:**
- Create: `utils/env_config.py`

- [ ] **Step 1: 创建 env_config.py**

```python
"""
环境变量配置管理模块

提供统一的环境变量配置读写，支持：
- 从 .env 文件加载配置
- 保存配置到 .env 文件
- 默认值处理

配置文件位置: ~/.remote-claude/.env
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger('EnvConfig')

from utils.session import USER_DATA_DIR, ensure_user_data_dir

ENV_FILE = USER_DATA_DIR / ".env"


@dataclass
class EnvConfig:
    """环境变量配置"""
    # 必填
    feishu_app_id: str = ""
    feishu_app_secret: str = ""

    # 可选
    user_whitelist: List[str] = field(default_factory=list)
    group_prefix: str = "Remote-Claude"
    log_level: str = "INFO"
    startup_timeout: int = 5
    max_card_blocks: int = 50
    no_proxy: bool = False

    def is_valid(self) -> bool:
        """检查必填字段是否已配置"""
        return bool(self.feishu_app_id and self.feishu_app_secret)

    def to_env_content(self) -> str:
        """生成 .env 文件内容"""
        lines = [
            "# Remote Claude 环境变量配置",
            "",
            "# === 必填 ===",
            f"FEISHU_APP_ID={self.feishu_app_id}",
            f"FEISHU_APP_SECRET={self.feishu_app_secret}",
            "",
            "# === 可选 ===",
            f"USER_WHITELIST={','.join(self.user_whitelist)}",
            f"GROUP_PREFIX={self.group_prefix}",
            f"LOG_LEVEL={self.log_level}",
            f"STARTUP_TIMEOUT={self.startup_timeout}",
            f"MAX_CARD_BLOCKS={self.max_card_blocks}",
            f"NO_PROXY={'1' if self.no_proxy else '0'}",
        ]
        return "\n".join(lines) + "\n"

    @classmethod
    def from_env_file(cls, path: Path = ENV_FILE) -> "EnvConfig":
        """从 .env 文件加载配置"""
        if not path.exists():
            return cls()

        env_vars: dict = {}
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()

        return cls(
            feishu_app_id=env_vars.get('FEISHU_APP_ID', ''),
            feishu_app_secret=env_vars.get('FEISHU_APP_SECRET', ''),
            user_whitelist=_parse_list(env_vars.get('USER_WHITELIST', '')),
            group_prefix=env_vars.get('GROUP_PREFIX', 'Remote-Claude'),
            log_level=env_vars.get('LOG_LEVEL', 'INFO'),
            startup_timeout=int(env_vars.get('STARTUP_TIMEOUT', '5')),
            max_card_blocks=int(env_vars.get('MAX_CARD_BLOCKS', '50')),
            no_proxy=env_vars.get('NO_PROXY', '0') == '1',
        )

    def save(self, path: Path = ENV_FILE) -> None:
        """保存配置到 .env 文件"""
        ensure_user_data_dir()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.to_env_content())
        logger.info(f"环境变量配置已保存到 {path}")


def _parse_list(value: str) -> List[str]:
    """解析逗号分隔的列表"""
    if not value:
        return []
    return [item.strip() for item in value.split(',') if item.strip()]


def load_env_config() -> EnvConfig:
    """加载环境变量配置"""
    return EnvConfig.from_env_file()


def save_env_config(config: EnvConfig) -> None:
    """保存环境变量配置"""
    config.save()
```

- [ ] **Step 2: 运行 EnvConfig 验证**

```bash
uv run python3 -c "
from utils.env_config import EnvConfig, load_env_config
c = EnvConfig(feishu_app_id='test', feishu_app_secret='secret')
assert c.is_valid()
assert 'FEISHU_APP_ID=test' in c.to_env_content()
print('EnvConfig 验证通过')
"
```

- [ ] **Step 3: 提交 EnvConfig**

```bash
git add utils/env_config.py
git commit -m "feat(config): 添加 EnvConfig 环境变量配置类

- 支持从 .env 文件加载配置
- 支持保存配置到 .env 文件
- 合并 ENABLE_USER_WHITELIST + ALLOWED_USERS → USER_WHITELIST
- 合并 LARK_LOG_LEVEL + SERVER_LOG_LEVEL → LOG_LEVEL

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: 更新 CLI 参数

**Files:**
- Modify: `remote_claude.py:1344-1349`（start 命令参数定义）
- Modify: `remote_claude.py:280-350`（cmd_start 函数）

- [ ] **Step 1: 修改 start 命令参数定义**

将 `--cli` 参数改为 `--launcher`：

```python
    start_parser.add_argument(
        "--launcher", "-l",
        default=None,
        help="启动器名称（对应 settings.launchers[].name），不指定则使用第一个"
    )
```

- [ ] **Step 2: 修改 cmd_start 函数**

更新启动逻辑以使用新配置：

```python
def cmd_start(args):
    """启动新会话"""
    # 加载配置
    from utils.runtime_config import load_settings
    settings = load_settings()

    # 解析 launcher
    launcher_name = args.launcher
    if launcher_name:
        launcher = settings.get_launcher(launcher_name)
        if not launcher:
            print(f"错误: 未找到启动器 '{launcher_name}'")
            print(f"可用的启动器: {[l.name for l in settings.launchers]}")
            sys.exit(1)
    else:
        launcher = settings.get_default_launcher()
        if not launcher:
            print("错误: 未配置启动器，请在 settings.json 中配置 launchers")
            sys.exit(1)

    cli_type = launcher.cli_type
    command = launcher.command

    # ... 后续逻辑保持不变，使用 cli_type 和 command
```

- [ ] **Step 3: 更新帮助文档**

```python
    epilog="""
示例:
  %(prog)s start mywork                    启动名为 mywork 的会话（使用默认启动器）
  %(prog)s start mywork --launcher Codex   使用 Codex 启动器启动会话
  %(prog)s start mywork -l Codex           同上（简写）
  %(prog)s attach mywork                   连接到 mywork 会话
  ...
"""
```

- [ ] **Step 4: 运行 CLI 测试**

```bash
uv run python3 remote_claude.py start --help
# 验证 --launcher 参数显示正确
```

- [ ] **Step 5: 提交 CLI 更新**

```bash
git add remote_claude.py
git commit -m "feat(cli): 将 --cli 参数改为 --launcher

- 移除 --cli 参数
- 添加 --launcher/-l 参数，映射到 settings.launchers[].name
- 不指定时使用第一个启动器
- 更新帮助文档

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 6: 更新 lark_client/card_builder.py

**Files:**
- Modify: `lark_client/card_builder.py:40-70, 280-340, 1605-1620`

- [ ] **Step 1: 更新 _get_available_commands 函数**

```python
def _get_available_commands(settings: Optional["Settings"]) -> List[Dict[str, str]]:
    """获取可用的启动器命令列表

    Returns:
        命令列表，每个元素包含 name 和 command。
        如果未配置启动器，返回默认命令列表。
    """
    if not settings or not settings.launchers:
        # 未配置启动器，返回默认命令列表（Claude 和 Codex）
        return [
            {"name": "Claude", "command": str(CliType.CLAUDE)},
            {"name": "Codex", "command": str(CliType.CODEX)},
        ]

    return [
        {"name": launcher.name, "command": launcher.command}
        for launcher in settings.launchers
    ]
```

- [ ] **Step 2: 更新 _build_operation_selector 函数**

```python
def _build_operation_selector(settings: Optional["Settings"]) -> Optional[Dict[str, Any]]:
    """构建会话页操作下拉（快捷键 + 启动器）"""
    options: List[Dict[str, Any]] = []

    show_builtin_keys = True
    show_launchers: List[str] = []
    enabled_keys = set()

    if settings:
        show_builtin_keys = settings.ui.show_builtin_keys
        show_launchers = settings.ui.show_launchers
        enabled_keys = set(settings.ui.enabled_keys)

    if show_builtin_keys:
        key_map = [
            ("↑", "up"),
            ("↓", "down"),
            ("Ctrl+O", "ctrl_o"),
            ("Shift+Tab", "shift_tab"),
            ("ESC", "esc"),
            ("(↹)×3", "shift_tab_x3"),
        ]
        for label, key_name in key_map:
            if key_name in enabled_keys:
                options.append({
                    "text": {"tag": "plain_text", "content": label},
                    "value": f"key:{key_name}",
                })

    if show_launchers and settings:
        for launcher in settings.launchers:
            if launcher.name in show_launchers:
                options.append({
                    "text": {"tag": "plain_text", "content": f"{launcher.name}: {launcher.command}"},
                    "value": f"cmd:{launcher.command}",
                })

    if not options:
        return None

    if len(options) > 20:
        _cb_logger.warning(f"操作下拉选项数量 {len(options)} 超过 20，已截断")
        options = options[:20]

    return {
        "tag": "action",
        "actions": [{
            "tag": "select_static",
            "placeholder": {"tag": "plain_text", "content": "操作"},
            "options": options,
        }]
    }
```

- [ ] **Step 3: 更新配置显示卡片**

```python
    # 启动器配置显示
    elements.append({"tag": "hr"})
    elements.append({"tag": "markdown", "content": "**启动器**"})

    if settings and settings.launchers:
        for launcher in settings.launchers:
            desc = f" _{launcher.desc}_" if launcher.desc else ""
            elements.append({
                "tag": "markdown",
                "content": f"- **{launcher.name}** → `{launcher.command}` ({launcher.cli_type}){desc}",
            })
    else:
        elements.append({"tag": "markdown", "content": "_未配置_"})
```

- [ ] **Step 4: 提交 card_builder 更新**

```bash
git add lark_client/card_builder.py
git commit -m "feat(lark): 适配新版配置结构

- _get_available_commands: 使用 settings.launchers
- _build_operation_selector: 使用 settings.ui.show_launchers
- 配置显示卡片: 展示启动器配置

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 7: 更新其他依赖文件

**Files:**
- Modify: `server/server.py`
- Modify: `lark_client/config.py`
- Modify: `lark_client/lark_handler.py`
- Modify: `lark_client/session_bridge.py`

- [ ] **Step 1: 搜索所有使用旧配置的地方**

```bash
grep -r "UserConfig\|RuntimeConfig\|load_user_config\|load_runtime_config" \
  --include="*.py" \
  remote_claude/ server/ lark_client/ client/ utils/ \
  | grep -v "__pycache__" \
  | grep -v "runtime_config.py"
```

- [ ] **Step 2: 批量替换导入和使用**

在需要使用新配置的文件中：
- `from utils.runtime_config import UserConfig` → `from utils.runtime_config import Settings`
- `from utils.runtime_config import RuntimeConfig` → `from utils.runtime_config import State`
- `load_user_config()` → `load_settings()`
- `load_runtime_config()` → `load_state()`

- [ ] **Step 3: 更新 lark_client/config.py**

```python
from utils.env_config import load_env_config, EnvConfig

def get_lark_config() -> tuple:
    """获取飞书配置"""
    env_config = load_env_config()
    return env_config.feishu_app_id, env_config.feishu_app_secret
```

- [ ] **Step 4: 运行完整测试**

```bash
uv run python3 -m pytest tests/test_runtime_config.py -v
uv run python3 -m pytest tests/test_custom_commands.py -v
```

- [ ] **Step 5: 提交依赖更新**

```bash
git add server/server.py lark_client/config.py lark_client/lark_handler.py lark_client/session_bridge.py
git commit -m "refactor: 适配新版配置结构

- UserConfig → Settings
- RuntimeConfig → State
- load_user_config → load_settings
- load_runtime_config → load_state
- 使用 EnvConfig 管理环境变量

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 8: 更新测试文件

**Files:**
- Modify: `tests/test_runtime_config.py`
- Create: `tests/test_env_config.py`

- [ ] **Step 1: 更新 test_runtime_config.py**

更新导入和测试用例以适配新版配置类：

```python
from utils.runtime_config import (
    Settings, State, Launcher, SessionState,
    CardSettings, SessionSettings, NotifySettings, UiSettings,
    load_settings, save_settings, load_state, save_state,
    # 保留旧类导入以测试迁移
    UserConfig, RuntimeConfig,
    migrate_settings_from_v1, migrate_state_from_v1,
)
```

- [ ] **Step 2: 创建 test_env_config.py**

```python
#!/usr/bin/env python3
"""EnvConfig 测试"""

import tempfile
from pathlib import Path

from utils.env_config import EnvConfig, load_env_config, save_env_config


def test_env_config_default():
    """测试默认配置"""
    config = EnvConfig()
    assert config.feishu_app_id == ""
    assert config.feishu_app_secret == ""
    assert config.group_prefix == "Remote-Claude"
    assert config.log_level == "INFO"
    assert config.is_valid() == False


def test_env_config_valid():
    """测试有效配置"""
    config = EnvConfig(feishu_app_id="test_id", feishu_app_secret="test_secret")
    assert config.is_valid() == True


def test_env_config_save_and_load():
    """测试保存和加载"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / ".env"

        # 保存
        config = EnvConfig(
            feishu_app_id="id123",
            feishu_app_secret="secret456",
            user_whitelist=["user1", "user2"],
            group_prefix="TestPrefix",
            log_level="DEBUG",
        )
        config.save(path)

        # 加载
        loaded = EnvConfig.from_env_file(path)
        assert loaded.feishu_app_id == "id123"
        assert loaded.feishu_app_secret == "secret456"
        assert loaded.user_whitelist == ["user1", "user2"]
        assert loaded.group_prefix == "TestPrefix"
        assert loaded.log_level == "DEBUG"


def test_env_config_to_env_content():
    """测试生成 .env 内容"""
    config = EnvConfig(feishu_app_id="test_id", feishu_app_secret="test_secret")
    content = config.to_env_content()

    assert "FEISHU_APP_ID=test_id" in content
    assert "FEISHU_APP_SECRET=test_secret" in content
    assert "GROUP_PREFIX=Remote-Claude" in content


if __name__ == "__main__":
    test_env_config_default()
    test_env_config_valid()
    test_env_config_save_and_load()
    test_env_config_to_env_content()
    print("所有测试通过")
```

- [ ] **Step 3: 运行测试**

```bash
uv run python3 -m pytest tests/test_runtime_config.py tests/test_env_config.py -v
```

- [ ] **Step 4: 提交测试更新**

```bash
git add tests/test_runtime_config.py tests/test_env_config.py
git commit -m "test(config): 更新配置测试

- 更新 test_runtime_config.py 适配新版配置类
- 新增 test_env_config.py 测试 EnvConfig

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 9: 删除旧配置模板

**Files:**
- Delete: `resources/defaults/config.default.json`
- Delete: `resources/defaults/runtime.default.json`
- Delete: `resources/defaults/.env.example`

- [ ] **Step 1: 删除旧模板文件**

```bash
rm resources/defaults/config.default.json
rm resources/defaults/runtime.default.json
rm resources/defaults/.env.example
```

- [ ] **Step 2: 验证新模板存在**

```bash
ls -la resources/defaults/
# 应该显示:
# settings.json.example
# state.json.example
# env.example
```

- [ ] **Step 3: 提交删除**

```bash
git add -A resources/defaults/
git commit -m "chore(config): 删除旧版配置模板

- 删除 config.default.json
- 删除 runtime.default.json
- 删除 .env.example

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 10: 更新文档

**Files:**
- Modify: `docs/configuration.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: 更新 docs/configuration.md**

根据设计文档更新配置说明文档，反映新的配置结构和命名。

- [ ] **Step 2: 更新 CLAUDE.md**

更新配置文件说明部分：

```markdown
### 配置文件

| 文件 | 用途 |
|------|------|
| `~/.remote-claude/settings.json` | 用户设置（启动器、卡片、会话等） |
| `~/.remote-claude/state.json` | 运行时状态（会话映射、飞书绑定） |
| `~/.remote-claude/.env` | 环境变量（飞书凭证等） |
```

- [ ] **Step 3: 提交文档更新**

```bash
git add docs/configuration.md CLAUDE.md
git commit -m "docs: 更新配置文档

- 更新配置文件说明
- 反映新版配置结构和命名
- 添加迁移说明

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 11: 最终集成测试

**Files:**
- Test: 整体功能验证

- [ ] **Step 1: 运行完整测试套件**

```bash
uv run python3 -m pytest tests/ -v --tb=short
```

- [ ] **Step 2: 手动验证 CLI**

```bash
# 测试帮助信息
uv run python3 remote_claude.py start --help

# 测试配置加载
uv run python3 -c "
from utils.runtime_config import load_settings, load_state
from utils.env_config import load_env_config
s = load_settings()
st = load_state()
e = load_env_config()
print(f'Settings version: {s.version}')
print(f'State version: {st.version}')
print(f'EnvConfig valid: {e.is_valid()}')
"
```

- [ ] **Step 3: 提交最终版本**

```bash
git add -A
git commit -m "chore: 配置优化最终集成

- 验证所有测试通过
- 确认 CLI 功能正常
- 确认配置迁移正常

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Spec Coverage Check

| Spec 需求 | Task |
|-----------|------|
| 文件命名：`settings.json.example` | Task 1 |
| 文件命名：`state.json.example` | Task 1 |
| 文件命名：`env.example` | Task 1 |
| `UserConfig` → `Settings` | Task 2 |
| `RuntimeConfig` → `State` | Task 2 |
| 新增 `EnvConfig` 类 | Task 4 |
| 层级不大于 2 | Task 2（数据类设计） |
| `launchers` 移到顶层 | Task 2 |
| `auto_answer` 扁平化 | Task 2 |
| CLI `--cli` → `--launcher` | Task 5 |
| 配置迁移逻辑 | Task 3 |
| 删除旧模板 | Task 9 |
| 更新文档 | Task 10 |
