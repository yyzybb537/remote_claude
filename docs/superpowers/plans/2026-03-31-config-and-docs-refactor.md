# 配置与文档重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构配置结构为功能域分组、添加快捷命令帮助概览、精简 README 并重组文档

**Architecture:** 配置从 `ui_settings` 嵌套结构改为 `card`/`session`/`behavior` 扁平化分组；bin 脚本添加共享帮助函数；README 精简并迁移详细内容到 docs/

**Tech Stack:** Python dataclasses, POSIX shell, Markdown

---

## 文件结构

### 创建文件
- `scripts/_help.sh` — 快捷命令帮助输出函数
- `docs/configuration.md` — 完整配置说明
- `docs/feishu-setup.md` — 飞书机器人配置教程
- `docs/remote-connection.md` — 远程连接详细说明
- `docs/cli-reference.md` — 完整 CLI 命令参考
- `docs/feishu-client.md` — 飞书客户端管理指南
- `docs/docker-test.md` — Docker 测试说明

### 修改文件
- `utils/runtime_config.py` — 配置数据类重构
- `resources/defaults/config.default.json` — 新配置结构
- `bin/cla`, `bin/cl`, `bin/cx`, `bin/cdx` — 帮助输出
- `README.md` — 精简内容
- `lark_client/card_builder.py` — 配置路径更新
- `lark_client/lark_handler.py` — 配置路径更新
- `lark_client/main.py` — 配置路径更新
- `lark_client/shared_memory_poller.py` — 配置路径更新
- `tests/test_runtime_config.py` — 测试更新
- `tests/test_custom_commands.py` — 测试更新

### 删除文件
- `lark_client/README.md` → 移至 `docs/feishu-client.md`
- `docker/README.md` → 移至 `docs/docker-test.md`

---

## Task 1: 重构配置数据类

**Files:**
- Modify: `utils/runtime_config.py:1-1400`

- [ ] **Step 1: 添加新的配置数据类**

在 `utils/runtime_config.py` 中，在 `UISettings` 类定义之前（约第 575 行），添加新的顶层配置类：

```python
@dataclass
class CardConfig:
    """飞书卡片相关配置"""
    quick_commands: QuickCommandsConfig = field(default_factory=lambda: QuickCommandsConfig())
    expiry: CardExpirySettings = field(default_factory=lambda: CardExpirySettings())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quick_commands": self.quick_commands.to_dict(),
            "expiry": self.expiry.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CardConfig":
        return cls(
            quick_commands=QuickCommandsConfig.from_dict(data.get("quick_commands", {})),
            expiry=CardExpirySettings.from_dict(data.get("expiry", {})),
        )


@dataclass
class SessionConfig:
    """会话相关配置"""
    bypass: bool = False
    custom_commands: CustomCommandsConfig = field(default_factory=lambda: CustomCommandsConfig())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bypass": self.bypass,
            "custom_commands": self.custom_commands.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionConfig":
        return cls(
            bypass=data.get("bypass", False),
            custom_commands=CustomCommandsConfig.from_dict(data.get("custom_commands", {})),
        )


@dataclass
class BehaviorConfig:
    """运行时行为配置"""
    auto_answer: AutoAnswerSettings = field(default_factory=lambda: AutoAnswerSettings())
    notify: NotifySettings = field(default_factory=lambda: NotifySettings())
    operation_panel: OperationPanelSettings = field(default_factory=lambda: OperationPanelSettings())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "auto_answer": self.auto_answer.to_dict(),
            "notify": self.notify.to_dict(),
            "operation_panel": self.operation_panel.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BehaviorConfig":
        return cls(
            auto_answer=AutoAnswerSettings.from_dict(data.get("auto_answer", {})),
            notify=NotifySettings.from_dict(data.get("notify", {})),
            operation_panel=OperationPanelSettings.from_dict(data.get("operation_panel", {})),
        )
```

- [ ] **Step 2: 修改 UserConfig 类**

将 `UserConfig` 类（约第 731-764 行）替换为：

```python
@dataclass
class UserConfig:
    """用户配置对象（存储于 config.json，用户可编辑）

    配置按功能域分组：
    - card: 飞书卡片相关配置
    - session: 会话相关配置
    - behavior: 运行时行为配置
    """
    version: str = "2.0"
    card: CardConfig = field(default_factory=lambda: CardConfig())
    session: SessionConfig = field(default_factory=lambda: SessionConfig())
    behavior: BehaviorConfig = field(default_factory=lambda: BehaviorConfig())

    def is_quick_commands_visible(self) -> bool:
        """判断快捷命令选择器是否应该显示"""
        return self.card.quick_commands.is_visible()

    def get_quick_commands(self) -> List[QuickCommand]:
        """获取快捷命令列表"""
        if self.card.quick_commands.enabled:
            return self.card.quick_commands.commands
        return []

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version": self.version,
            "card": self.card.to_dict(),
            "session": self.session.to_dict(),
            "behavior": self.behavior.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserConfig":
        """从字典创建"""
        # 检测旧版本配置并输出警告
        if data.get("version") == "1.0" or "ui_settings" in data:
            logger.warning(
                "检测到旧版本配置格式 (v1.0)，请删除 ~/.remote-claude/config.json 后重新启动，"
                "将自动生成新格式配置。"
            )
            return cls()  # 返回默认配置

        return cls(
            version=data.get("version", "2.0"),
            card=CardConfig.from_dict(data.get("card", {})),
            session=SessionConfig.from_dict(data.get("session", {})),
            behavior=BehaviorConfig.from_dict(data.get("behavior", {})),
        )
```

- [ ] **Step 3: 删除 UISettings 类**

删除 `UISettings` 类定义（约第 575-615 行）。

- [ ] **Step 4: 更新版本号常量**

将 `USER_CONFIG_VERSION` 从 `"1.0"` 改为 `"2.0"`（约第 30 行）：

```python
USER_CONFIG_VERSION = "2.0"
```

- [ ] **Step 5: 更新配置访问函数**

更新所有配置访问函数，将 `ui_settings` 路径改为新的扁平化路径：

```python
# 通知设置访问函数
def get_notify_ready_enabled() -> bool:
    """获取就绪通知开关状态"""
    config = load_user_config()
    return config.behavior.notify.ready_enabled


def set_notify_ready_enabled(enabled: bool) -> None:
    """设置就绪通知开关状态（原子更新）"""

    def mutator(config: UserConfig):
        config.behavior.notify.ready_enabled = enabled
        logger.info(f"就绪通知开关已{'开启' if enabled else '关闭'}")
        return None

    _update_config_with_lock(
        USER_CONFIG_FILE,
        USER_CONFIG_LOCK_FILE,
        load_user_config,
        UserConfig,
        mutator,
    )


def get_notify_urgent_enabled() -> bool:
    """获取加急通知开关状态"""
    config = load_user_config()
    return config.behavior.notify.urgent_enabled


def set_notify_urgent_enabled(enabled: bool) -> None:
    """设置加急通知开关状态（原子更新）"""

    def mutator(config: UserConfig):
        config.behavior.notify.urgent_enabled = enabled
        logger.info(f"加急通知开关已{'开启' if enabled else '关闭'}")
        return None

    _update_config_with_lock(
        USER_CONFIG_FILE,
        USER_CONFIG_LOCK_FILE,
        load_user_config,
        UserConfig,
        mutator,
    )


def get_bypass_enabled() -> bool:
    """获取新会话 bypass 开关状态"""
    config = load_user_config()
    return config.session.bypass


def set_bypass_enabled(enabled: bool) -> None:
    """设置新会话 bypass 开关状态（原子更新）"""

    def mutator(config: UserConfig):
        config.session.bypass = enabled
        logger.info(f"新会话 bypass 开关已{'开启' if enabled else '关闭'}")
        return None

    _update_config_with_lock(
        USER_CONFIG_FILE,
        USER_CONFIG_LOCK_FILE,
        load_user_config,
        UserConfig,
        mutator,
    )


# 自动应答配置访问函数
def get_auto_answer_delay() -> int:
    """获取自动应答延迟时间（秒）"""
    config = load_user_config()
    return config.behavior.auto_answer.default_delay_seconds


def get_card_expiry_enabled() -> bool:
    """获取卡片过期功能是否启用"""
    config = load_user_config()
    return config.card.expiry.enabled


def get_card_expiry_seconds() -> int:
    """获取卡片过期时间（秒）"""
    config = load_user_config()
    return config.card.expiry.expiry_seconds


# 自定义命令配置访问函数
def get_custom_commands() -> List[CustomCommand]:
    """获取自定义命令列表"""
    config = load_user_config()
    return config.session.custom_commands.commands


def get_custom_command(name: str) -> Optional[str]:
    """根据名称获取自定义命令"""
    config = load_user_config()
    return config.session.custom_commands.get_command(name)


def get_cli_command(cli_type: str) -> str:
    """获取 CLI 命令（优先自定义命令，回退到默认值）"""
    cli_type_str = str(cli_type) if isinstance(cli_type, CliType) else cli_type
    config = load_user_config()
    custom_cmd = config.session.custom_commands.get_command_by_cli_type(cli_type_str)
    if custom_cmd:
        logger.debug(f"使用自定义命令: {cli_type_str} -> {custom_cmd}")
        return custom_cmd
    default_commands = {
        str(CliType.CLAUDE): str(CliType.CLAUDE),
        str(CliType.CODEX): str(CliType.CODEX),
    }
    return default_commands.get(cli_type_str, cli_type_str)


def set_custom_commands(commands: List[CustomCommand]) -> None:
    """设置自定义命令列表（原子更新）"""

    def mutator(config: UserConfig):
        config.session.custom_commands.commands = commands
        logger.info(f"已保存 {len(commands)} 个自定义命令")
        return None

    _update_config_with_lock(
        USER_CONFIG_FILE,
        USER_CONFIG_LOCK_FILE,
        load_user_config,
        UserConfig,
        mutator,
    )


def is_custom_commands_enabled() -> bool:
    """检查自定义命令功能是否启用"""
    config = load_user_config()
    return config.session.custom_commands.is_visible()


# 模糊指令配置
def get_vague_commands_config() -> tuple:
    """获取模糊指令配置"""
    config = load_user_config()
    auto_answer = config.behavior.auto_answer
    return auto_answer.vague_commands, auto_answer.vague_command_prompt
```

- [ ] **Step 6: 更新迁移函数中的配置路径**

更新 `migrate_legacy_notify_settings` 函数中的路径（约第 1028-1099 行）：

```python
    if LEGACY_NOTIFY_ENABLED_FILE.exists():
        try:
            val = LEGACY_NOTIFY_ENABLED_FILE.read_text().strip()
            user_config.behavior.notify.ready_enabled = (val == "1")
            LEGACY_NOTIFY_ENABLED_FILE.unlink()
            logger.info("[迁移] ready_notify_enabled -> config.json")
        except Exception as e:
            logger.warning(f"[迁移] ready_notify_enabled 迁移失败: {e}")
            LEGACY_NOTIFY_ENABLED_FILE.unlink()

    if LEGACY_URGENT_ENABLED_FILE.exists():
        try:
            val = LEGACY_URGENT_ENABLED_FILE.read_text().strip()
            user_config.behavior.notify.urgent_enabled = (val == "1")
            LEGACY_URGENT_ENABLED_FILE.unlink()
            logger.info("[迁移] urgent_notify_enabled -> config.json")
        except Exception as e:
            logger.warning(f"[迁移] urgent_notify_enabled 迁移失败: {e}")
            LEGACY_URGENT_ENABLED_FILE.unlink()

    if LEGACY_BYPASS_ENABLED_FILE.exists():
        try:
            val = LEGACY_BYPASS_ENABLED_FILE.read_text().strip()
            user_config.session.bypass = (val == "1")
            LEGACY_BYPASS_ENABLED_FILE.unlink()
            logger.info("[迁移] bypass_enabled -> config.json")
        except Exception as e:
            logger.warning(f"[迁移] bypass_enabled 迁移失败: {e}")
            LEGACY_BYPASS_ENABLED_FILE.unlink()
```

- [ ] **Step 7: 运行测试验证**

Run: `uv run python3 -m pytest tests/test_runtime_config.py -v`
Expected: 所有测试通过

- [ ] **Step 8: 提交配置重构**

```bash
git add utils/runtime_config.py
git commit -m "refactor(config): 按功能域扁平化配置结构

- 新增 CardConfig、SessionConfig、BehaviorConfig 数据类
- UserConfig 从 ui_settings 嵌套改为 card/session/behavior 扁平化
- 更新所有配置访问函数路径
- 旧版本配置检测时输出警告并返回默认配置

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: 更新默认配置文件

**Files:**
- Modify: `resources/defaults/config.default.json`

- [ ] **Step 1: 更新配置文件为新结构**

将 `resources/defaults/config.default.json` 内容替换为：

```json
{
  "version": "2.0",
  "card": {
    "quick_commands": {
      "enabled": false,
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
        "继续执行", "继续", "开始执行", "开始", "执行", "continue", "确认", "OK"
      ],
      "vague_command_prompt": "[系统提示] 请使用工具执行下一步操作。如果不确定下一步，请明确询问需要做什么。不要只返回状态确认。"
    },
    "notify": {
      "ready_enabled": true,
      "urgent_enabled": false
    },
    "operation_panel": {
      "show_builtin_keys": true,
      "show_custom_commands": true,
      "enabled_keys": ["up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"]
    }
  }
}
```

- [ ] **Step 2: 提交默认配置更新**

```bash
git add resources/defaults/config.default.json
git commit -m "refactor(config): 更新默认配置为扁平化结构

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: 更新 lark_client 配置引用

**Files:**
- Modify: `lark_client/card_builder.py`
- Modify: `lark_client/lark_handler.py`
- Modify: `lark_client/main.py`
- Modify: `lark_client/shared_memory_poller.py`

- [ ] **Step 1: 更新 card_builder.py**

将所有 `ui_settings` 路径改为新路径：

- `user_config.ui_settings.custom_commands` → `user_config.session.custom_commands`
- `user_config.ui_settings.operation_panel` → `user_config.behavior.operation_panel`

- [ ] **Step 2: 更新 lark_handler.py**

导入路径无需更改（使用顶层函数），确认函数调用正确。

- [ ] **Step 3: 更新 main.py**

将 `user_config.ui_settings.operation_panel` 改为 `user_config.behavior.operation_panel`。

- [ ] **Step 4: 更新 shared_memory_poller.py**

导入路径无需更改（使用顶层函数）。

- [ ] **Step 5: 运行测试验证**

Run: `uv run python3 -m pytest tests/test_runtime_config.py tests/test_custom_commands.py -v`
Expected: 所有测试通过

- [ ] **Step 6: 提交 lark_client 更新**

```bash
git add lark_client/
git commit -m "refactor(lark): 更新配置路径为扁平化结构

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: 创建快捷命令帮助脚本

**Files:**
- Create: `scripts/_help.sh`

- [ ] **Step 1: 创建 _help.sh 脚本**

```shell
#!/bin/sh
# _help.sh - 快捷命令帮助输出
# 用法: . "$PROJECT_DIR/scripts/_help.sh"

# 打印快捷命令概览表格
_print_quick_help() {
    printf '\n'
    printf '%b\n' "${GREEN}Remote Claude 快捷命令${NC}"
    printf '%b\n' "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    printf '%b\n' "命令   CLI      权限模式          用途"
    printf '%b\n' "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    printf '%b\n' "cla    Claude   正常（需确认）    启动 Claude 会话"
    printf '%b\n' "cl     Claude   跳过权限确认      快速启动 Claude 会话"
    printf '%b\n' "cx     Codex    跳过权限确认      快速启动 Codex 会话"
    printf '%b\n' "cdx    Codex    正常（需确认）    启动 Codex 会话"
    printf '%b\n' "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    printf '\n'
    printf '%b\n' "会话命名：当前目录路径 + 时间戳"
    printf '%b\n' "示例：/Users/foo/project_0331_142500"
    printf '\n'
    printf '%b\n' "更多信息: ${BLUE}remote-claude --help${NC}"
    printf '\n'
}
```

- [ ] **Step 2: 提交帮助脚本**

```bash
git add scripts/_help.sh
git commit -m "feat(scripts): 添加快捷命令帮助输出函数

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: 更新 bin 脚本帮助输出

**Files:**
- Modify: `bin/cla`
- Modify: `bin/cl`
- Modify: `bin/cx`
- Modify: `bin/cdx`

- [ ] **Step 1: 更新 bin/cla**

将 `-h/--help` 分支从：

```shell
case "${1:-}" in
    -h|--help)
        exec "$PROJECT_DIR/bin/remote-claude" start --help
        ;;
esac
```

改为：

```shell
case "${1:-}" in
    -h|--help)
        . "$PROJECT_DIR/scripts/_help.sh"
        _print_quick_help
        exit 0
        ;;
esac
```

- [ ] **Step 2: 更新 bin/cl**

同 Step 1，将帮助分支改为调用 `_print_quick_help`。

- [ ] **Step 3: 更新 bin/cx**

同 Step 1，将帮助分支改为调用 `_print_quick_help`。

- [ ] **Step 4: 更新 bin/cdx**

同 Step 1，将帮助分支改为调用 `_print_quick_help`。

- [ ] **Step 5: 提交 bin 脚本更新**

```bash
git add bin/cla bin/cl bin/cx bin/cdx
git commit -m "feat(bin): 快捷命令 -h 显示统一概览表格

cla/cl/cx/cdx -h 现在显示所有快捷命令的功能对比表格，
而非重定向到 remote-claude start --help

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 6: 创建 docs 文档

**Files:**
- Create: `docs/configuration.md`
- Create: `docs/feishu-setup.md`
- Create: `docs/remote-connection.md`
- Create: `docs/cli-reference.md`
- Create: `docs/feishu-client.md`
- Create: `docs/docker-test.md`

- [ ] **Step 1: 创建 docs/configuration.md**

从 README.md 提取配置章节内容，包含：
- 配置文件说明
- 新的扁平化配置结构示例
- 各配置项详细说明

- [ ] **Step 2: 创建 docs/feishu-setup.md**

从 README.md 提取飞书机器人配置章节内容。

- [ ] **Step 3: 创建 docs/remote-connection.md**

从 README.md 提取远程连接章节内容。

- [ ] **Step 4: 创建 docs/cli-reference.md**

从 README.md 提取管理命令章节内容。

- [ ] **Step 5: 移动 lark_client/README.md 到 docs/feishu-client.md**

```bash
mv lark_client/README.md docs/feishu-client.md
```

- [ ] **Step 6: 移动 docker/README.md 到 docs/docker-test.md**

```bash
mv docker/README.md docs/docker-test.md
```

- [ ] **Step 7: 提交文档重组**

```bash
git add docs/ lark_client/README.md docker/README.md
git commit -m "docs: 重组文档结构，详细内容移至 docs/

- 创建 docs/configuration.md 配置说明
- 创建 docs/feishu-setup.md 飞书配置教程
- 创建 docs/remote-connection.md 远程连接说明
- 创建 docs/cli-reference.md CLI 命令参考
- 移动 lark_client/README.md 到 docs/feishu-client.md
- 移动 docker/README.md 到 docs/docker-test.md

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 7: 精简 README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 重写 README.md**

精简到 ~100 行，保留：
- 项目定位和核心价值
- 安装方式
- 快捷命令表格
- 飞书客户端简短说明
- 文档链接

新 README 内容：

```markdown
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
```

- [ ] **Step 2: 提交 README 精简**

```bash
git add README.md
git commit -m "docs: 精简 README 到 ~80 行

保留核心内容：定位、安装、快捷命令、文档链接
详细内容移至 docs/ 目录

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 8: 更新测试用例

**Files:**
- Modify: `tests/test_runtime_config.py`
- Modify: `tests/test_custom_commands.py`

- [ ] **Step 1: 更新 test_runtime_config.py**

更新导入和测试用例以使用新的配置类：

```python
from utils.runtime_config import (
    RuntimeConfig,
    UserConfig,
    QuickCommand,
    QuickCommandsConfig,
    OperationPanelSettings,
    CardConfig,
    SessionConfig,
    BehaviorConfig,
    load_runtime_config,
    save_runtime_config,
    load_user_config,
    save_user_config,
    # ... 其他导入
)
```

添加新配置类的测试：

```python
def test_card_config():
    """测试 CardConfig 数据类"""
    config = CardConfig()
    assert config.quick_commands.enabled == False
    assert config.expiry.enabled == True

    data = config.to_dict()
    assert "quick_commands" in data
    assert "expiry" in data

    restored = CardConfig.from_dict(data)
    assert restored.quick_commands.enabled == config.quick_commands.enabled


def test_session_config():
    """测试 SessionConfig 数据类"""
    config = SessionConfig()
    assert config.bypass == False
    assert config.custom_commands.enabled == False

    data = config.to_dict()
    assert "bypass" in data
    assert "custom_commands" in data


def test_behavior_config():
    """测试 BehaviorConfig 数据类"""
    config = BehaviorConfig()
    assert config.notify.ready_enabled == True
    assert config.auto_answer.default_delay_seconds == 10

    data = config.to_dict()
    assert "notify" in data
    assert "auto_answer" in data
    assert "operation_panel" in data


def test_user_config_v2_structure():
    """测试 UserConfig v2.0 结构"""
    config = UserConfig()
    assert config.version == "2.0"
    assert hasattr(config, "card")
    assert hasattr(config, "session")
    assert hasattr(config, "behavior")
    assert not hasattr(config, "ui_settings")

    data = config.to_dict()
    assert data["version"] == "2.0"
    assert "card" in data
    assert "session" in data
    assert "behavior" in data


def test_user_config_v1_migration_warning():
    """测试旧版本配置检测"""
    old_data = {
        "version": "1.0",
        "ui_settings": {
            "quick_commands": {"enabled": False, "commands": []},
            "notify": {"ready_enabled": True, "urgent_enabled": False},
            "bypass_enabled": False,
        }
    }

    config = UserConfig.from_dict(old_data)
    # 旧版本配置应返回默认配置
    assert config.version == "2.0"
    assert config.card.quick_commands.enabled == False
```

- [ ] **Step 2: 运行测试验证**

Run: `uv run python3 -m pytest tests/test_runtime_config.py tests/test_custom_commands.py -v`
Expected: 所有测试通过

- [ ] **Step 3: 提交测试更新**

```bash
git add tests/
git commit -m "test: 更新测试用例以匹配新配置结构

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 9: 最终验证与提交

- [ ] **Step 1: 运行完整测试套件**

Run: `uv run python3 -m pytest tests/ -v`
Expected: 所有测试通过

- [ ] **Step 2: 验证快捷命令帮助**

Run: `./bin/cla -h`
Expected: 显示快捷命令概览表格

- [ ] **Step 3: 验证 README 行数**

Run: `wc -l README.md`
Expected: ≤ 120 行

- [ ] **Step 4: 创建汇总提交**

```bash
git add -A
git commit -m "feat(config,docs): 配置重构与文档精简

完成内容：
1. 配置结构从 ui_settings 嵌套改为 card/session/behavior 扁平化
2. 快捷命令 -h 显示统一概览表格
3. README 精简到 ~80 行，详细内容移至 docs/

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
