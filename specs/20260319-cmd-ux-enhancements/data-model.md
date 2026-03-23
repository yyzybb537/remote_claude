# Data Model: 命令行与飞书用户体验增强

**Feature**: `20260319-cmd-ux-enhancements`
**Date**: 2026-03-19

## 概述

本文档定义本功能涉及的数据实体、字段、关系和验证规则。

**⚠️ 重要变更（2026-03-19 澄清会话）**：
- 配置文件拆分为 `config.json`（用户可编辑配置）和 `runtime.json`（程序自动管理状态）
- 锁文件命名为 `runtime.json.lock`，包含详细注释
- 会话退出时自动删除 `session_mappings` 映射条目

---

## 1. UserConfig（用户配置）

**描述**: 用户可编辑的配置，存储 UI 设置等用户自定义选项。

**存储位置**: `~/.remote-claude/config.json`

### 字段定义

| 字段名 | 类型 | 必填 | 默认值 | 描述 |
|--------|------|------|--------|------|
| version | string | 否 | "1.0" | 配置文件版本，便于后续迁移 |
| ui_settings | UISettings | 否 | {} | UI 相关设置 |

### 数据结构

```python
@dataclass
class UserConfig:
    version: str = "1.0"
    ui_settings: "UISettings" = field(default_factory=lambda: UISettings())
```

### JSON 示例

```json
{
  "version": "1.0",
  "ui_settings": {
    "quick_commands": {
      "enabled": false,
      "commands": [
        {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
        {"label": "压缩上下文", "value": "/consume", "icon": "📦"}
      ]
    }
  }
}
```

---

## 2. RuntimeConfig（运行时配置）

**描述**: 程序自动管理的运行时状态，用户不应手动编辑。

**存储位置**: `~/.remote-claude/runtime.json`

### 字段定义

| 字段名 | 类型 | 必填 | 默认值 | 描述 |
|--------|------|------|--------|------|
| version | string | 否 | "1.0" | 配置文件版本，便于后续迁移 |
| session_mappings | dict | 否 | {} | 截断名称 → 原始路径映射（会话退出时删除） |
| lark_group_mappings | dict | 否 | {} | 群组 ID → 会话名映射（持久保留） |

### 数据结构

```python
@dataclass
class RuntimeConfig:
    version: str = "1.0"
    session_mappings: Dict[str, str] = field(default_factory=dict)
    lark_group_mappings: Dict[str, str] = field(default_factory=dict)
```

### JSON 示例

```json
{
  "version": "1.0",
  "session_mappings": {
    "myapp_src_comp": "/Users/dev/projects/myapp/src/components"
  },
  "lark_group_mappings": {
    "oc_xxx": "my-session"
  }
}
```

---

## 3. LockFile（文件锁）

**描述**: 配置文件锁，用于并发写入保护，包含详细注释便于用户理解。

**存储位置**: `~/.remote-claude/runtime.json.lock`

### 字段定义

| 字段名 | 类型 | 描述 |
|--------|------|------|
| purpose | string | 用途说明 |
| pid | int | 创建锁的进程 PID |
| created_at | string | 创建时间（ISO 8601 格式） |

### 锁文件内容示例

```
# Remote Claude 配置文件锁
# 用途: 防止并发写入导致配置损坏
# 创建进程 PID: 12345
# 创建时间: 2026-03-19T14:30:00+08:00
# 说明: 此文件在配置写入时自动创建，写入完成后自动删除
#       如果程序异常退出，此文件可能残留，可安全删除
```

---

## 2. UISettings（UI 设置）

**描述**: 用户界面相关配置，控制飞书卡片展示行为。

### 字段定义

| 字段名 | 类型 | 必填 | 默认值 | 描述 |
|--------|------|------|--------|------|
| quick_commands | QuickCommandsConfig | 否 | 默认配置 | 快捷命令配置 |

### 数据结构

```python
@dataclass
class UISettings:
    quick_commands: "QuickCommandsConfig" = field(default_factory=lambda: QuickCommandsConfig())
```

---

## 3. QuickCommandsConfig（快捷命令配置）

**描述**: 控制快捷命令选择器的显示和行为。

### 字段定义

| 字段名 | 类型 | 必填 | 默认值 | 描述 |
|--------|------|------|--------|------|
| enabled | bool | 否 | false | 是否启用快捷命令选择器 |
| commands | List[QuickCommand] | 否 | [] | 快捷命令列表 |

### 验证规则

1. `enabled=true` 且 `commands` 为空时，不显示选择器
2. `commands` 最多支持 20 个命令
3. 单个命令 `value` 不支持参数（如 `/attach <session>`）

### RuntimeConfig 映射数量限制

- `session_mappings` 建议最多 500 条映射
- 超出限制时输出警告日志，但允许继续添加（软限制）
- 并发写入使用文件锁（fcntl.flock）保护

### 备份保留策略

- 配置文件损坏时自动备份为 `.json.bak`
- 保留最近 2 个备份文件，自动清理更早的备份

### 配置迁移 bak 文件清理策略

**原则**：保证正常运行时无 `.bak` 文件残留

> **注意**：config.json 和 runtime.json 均为全新配置文件，无需迁移逻辑。bak 文件清理仅适用于 `lark_group_mapping.json` → `runtime.json` 的迁移场景。

| 场景 | 处理方式 |
|------|----------|
| 迁移/修改成功 | 立即删除 `.bak` 文件 |
| 启动时检测残留 bak | 提示用户选择：① 覆盖（从 bak 重新迁移）② 跳过（删除 bak 继续） |
| 程序异常退出 | bak 文件残留，下次启动时处理 |

**实现逻辑**：

```python
def check_stale_backup() -> Optional[Path]:
    """检查残留的 bak 文件"""
    config_dir = USER_DATA_DIR
    bak_files = list(config_dir.glob("*.json.bak*"))
    return bak_files[0] if bak_files else None

def prompt_backup_action(bak_path: Path) -> str:
    """提示用户处理残留 bak 文件"""
    print(f"检测到残留的备份文件: {bak_path}")
    print("1. 覆盖当前配置并重新迁移")
    print("2. 跳过（删除备份文件继续）")
    choice = input("请选择 [1/2]: ").strip()
    return choice

def cleanup_backup_after_migration():
    """迁移成功后清理 bak 文件"""
    for bak_file in USER_DATA_DIR.glob("*.json.bak*"):
        bak_file.unlink()
        logger.info(f"已删除备份文件: {bak_file}")
```

### 数据结构

```python
@dataclass
class QuickCommandsConfig:
    enabled: bool = False
    commands: List["QuickCommand"] = field(default_factory=list)

    def is_visible(self) -> bool:
        """判断是否显示快捷命令选择器"""
        return self.enabled and len(self.commands) > 0
```

---

## 4. QuickCommand（快捷命令）

**描述**: 单个快捷命令项，对应飞书卡片下拉选项。

### 字段定义

| 字段名 | 类型 | 必填 | 默认值 | 描述 |
|--------|------|------|--------|------|
| label | string | 是 | - | 显示名称（如"清空对话"） |
| value | string | 是 | - | 命令值（如"/clear"） |
| icon | string | 否 | "" | 图标 emoji（如"🗑️"） |

### 验证规则

1. `value` 必须以 `/` 开头
2. `value` 不能包含空格（不支持参数）
3. `value` 最大长度 32 字符（2026-03-19 澄清：原 16 字符调整为 32 字符）
4. `label` 最大长度 20 字符
5. `icon` 无格式限制，可为空，空时使用空白占位 emoji（2026-03-19 澄清）
6. `commands` 最多 20 条，超过时静默截断（2026-03-19 澄清）

### 数据结构

```python
@dataclass
class QuickCommand:
    label: str
    value: str
    icon: str = ""

    def __post_init__(self):
        # 验证 value 格式
        if not self.value.startswith('/'):
            raise ValueError(f"命令值必须以 / 开头: {self.value}")
        if ' ' in self.value:
            raise ValueError(f"命令值不能包含空格: {self.value}")
```

### JSON 示例

```json
{
  "label": "清空对话",
  "value": "/clear",
  "icon": "🗑️"
}
```

---

## 5. SessionMapping（会话映射）

**描述**: 截断名称与原始路径的映射关系。

### 字段定义

| 字段名 | 类型 | 描述 |
|--------|------|------|
| truncated_name | string | 截断后的会话名（作为 dict key） |
| original_path | string | 原始完整路径 |

### 验证规则

1. `truncated_name` 不能为空字符串（2026-03-19 澄清）
2. 连续下划线必须合并为单下划线（2026-03-19 澄清）
3. 会话退出时自动删除映射条目

### 使用场景

1. 会话启动时写入映射
2. 用户查询历史时反查原始路径
3. 冲突检测时比较原始路径

---

## 6. CardUpdateMode（卡片更新模式）

**描述**: 定义飞书卡片的更新方式。

### 枚举值

| 值 | 描述 | 适用场景 |
|----|------|----------|
| UPDATE | 就地更新现有卡片 | 按钮点击、文本提交、选项选择 |
| REPLACE | 发送新卡片替换旧卡片 | 流式输出内容变化、会话状态变更 |

### 使用规则

1. **交互操作**（按钮点击、文本提交）使用 `UPDATE`
2. **流式输出**使用 `REPLACE`（由 SharedMemoryPoller 驱动）
3. `UPDATE` 失败时降级为 `REPLACE`

---

## 7. TextInputBox（文本输入框）

**描述**: 飞书卡片中的文本输入组件，支持回车自动提交。

### 字段定义

| 字段名 | 类型 | 必填 | 默认值 | 描述 |
|--------|------|------|--------|------|
| element_id | string | 是 | - | 元素唯一标识 |
| placeholder | string | 否 | "" | 占位提示文本 |
| is_multiline | bool | 否 | false | 是否多行输入 |
| max_length | int | 否 | 500 | 最大输入长度 |
| enter_action | string | 否 | "submit" | 回车行为：submit（提交）/ newline（换行） |

### 验证规则

1. `is_multiline=true` 时，`enter_action` 应为 "newline"
2. `is_multiline=false` 时，`enter_action` 应为 "submit"
3. 空输入不触发提交

### 数据结构

```python
@dataclass
class TextInputBox:
    element_id: str
    placeholder: str = ""
    is_multiline: bool = False
    max_length: int = 500
    enter_action: str = "submit"  # "submit" or "newline"

    def __post_init__(self):
        # 多行输入框强制换行行为
        if self.is_multiline:
            self.enter_action = "newline"
```

### 飞书卡片 JSON 示例

**单行输入框（回车提交）**：
```json
{
  "tag": "input",
  "placeholder": {"tag": "plain_text", "content": "输入消息..."},
  "element_id": "message_input",
  "enter_key_action": {
    "tag": "action",
    "actions": [{
      "tag": "button",
      "text": {"tag": "plain_text", "content": "发送"},
      "type": "primary",
      "value": "{\"action\": \"send_message\"}"
    }]
  }
}
```

**多行输入框（回车换行）**：
```json
{
  "tag": "textarea",
  "placeholder": {"tag": "plain_text", "content": "输入详细描述..."},
  "element_id": "description_input",
  "max_length": 1000
}
```

---

## 实体关系图

```
UserConfig (1)                    RuntimeConfig (1)
    │                                 │
    └── ui_settings (1:1)             ├── session_mappings (1:N) → SessionMapping
              │                       │                              (会话退出时删除)
              └── quick_commands      │
                        (1:1)         └── lark_group_mappings (1:N) → {chat_id: session_name}
                          │                                          (持久保留)
                          └── commands (1:N) → QuickCommand


CardUpdateMode (enum)
    │
    └── UPDATE → 就地更新卡片
    └── REPLACE → 推送新卡片

TextInputBox (N)
    │
    ├── is_multiline: false → enter_action: "submit"
    └── is_multiline: true → enter_action: "newline"
```

---

## 状态转换

### QuickCommandsConfig 状态

```
[disabled, commands=empty] ──配置 commands──→ [disabled, commands=non-empty]
        │                                            │
        │                                            │ 设置 enabled=true
        │                                            ↓
        │                                    [enabled, commands=non-empty] → 显示选择器
        │
        └──设置 enabled=true（无 commands）──→ [enabled, commands=empty] → 不显示选择器
```

---

## 文件操作

### 读取用户配置

```python
def load_user_config() -> UserConfig:
    path = USER_DATA_DIR / "config.json"
    if not path.exists():
        return UserConfig()

    try:
        data = json.loads(path.read_text())
        return UserConfig(
            version=data.get("version", "1.0"),
            ui_settings=parse_ui_settings(data.get("ui_settings", {}))
        )
    except (json.JSONDecodeError, KeyError) as e:
        # 备份损坏文件
        backup = path.with_suffix(".json.bak")
        path.rename(backup)
        logger.warning(f"用户配置文件损坏，已备份到 {backup}")
        return UserConfig()
```

### 保存用户配置

```python
def save_user_config(config: UserConfig) -> None:
    path = USER_DATA_DIR / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False))
```

### 读取运行时配置

```python
def load_runtime_config() -> RuntimeConfig:
    path = USER_DATA_DIR / "runtime.json"
    if not path.exists():
        return RuntimeConfig()

    try:
        data = json.loads(path.read_text())
        return RuntimeConfig(
            version=data.get("version", "1.0"),
            session_mappings=data.get("session_mappings", {}),
            lark_group_mappings=data.get("lark_group_mappings", {})
        )
    except (json.JSONDecodeError, KeyError) as e:
        # 备份损坏文件
        backup = path.with_suffix(".json.bak")
        path.rename(backup)
        logger.warning(f"运行时配置文件损坏，已备份到 {backup}")
        return RuntimeConfig()
```

### 保存运行时配置（带文件锁）

```python
import fcntl
from datetime import datetime

def save_runtime_config(config: RuntimeConfig) -> None:
    path = USER_DATA_DIR / "runtime.json"
    lock_path = USER_DATA_DIR / "runtime.json.lock"
    path.parent.mkdir(parents=True, exist_ok=True)

    # 创建锁文件（带注释）
    lock_content = f"""# Remote Claude 配置文件锁
# 用途: 防止并发写入导致配置损坏
# 创建进程 PID: {os.getpid()}
# 创建时间: {datetime.now().isoformat()}
# 说明: 此文件在配置写入时自动创建，写入完成后自动删除
#       如果程序异常退出，此文件可能残留，可安全删除
"""
    lock_path.write_text(lock_content)

    try:
        with open(path, 'w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(asdict(config), indent=2, ensure_ascii=False))
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        # 删除锁文件
        if lock_path.exists():
            lock_path.unlink()
```

### 删除会话映射（会话退出时调用）

```python
def remove_session_mapping(truncated_name: str) -> None:
    """会话退出时删除对应的映射条目"""
    config = load_runtime_config()
    if truncated_name in config.session_mappings:
        del config.session_mappings[truncated_name]
        save_runtime_config(config)
        logger.info(f"已删除会话映射: {truncated_name}")
```

### 备份损坏文件

**命名规则**：备份文件采用 `<原文件名>.json.bak.<timestamp>` 格式
- `<原文件名>`：原配置文件名（如 `runtime` 或 `config`）
- `<timestamp>`：时间戳格式 `%Y%m%d_%H%M%S`（如 `20260319_143000`）
- **示例**：`runtime.json.bak.20260319_143000`

```python
def _backup_corrupted_file(path: Path) -> None:
    """备份损坏的配置文件，保留最近 2 个备份"""
    import glob
    from datetime import datetime

    # 生成带时间戳的备份文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(f".json.bak.{timestamp}")
    path.rename(backup)

    # 清理旧备份，只保留最近 2 个
    backups = sorted(glob.glob(str(path.with_suffix(".json.bak.*"))))
    for old_backup in backups[:-2]:
        Path(old_backup).unlink()
```
