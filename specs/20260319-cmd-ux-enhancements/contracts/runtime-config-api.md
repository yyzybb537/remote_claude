# RuntimeConfig API Contract

**Feature**: `20260319-cmd-ux-enhancements`
**Version**: 1.2
**Date**: 2026-03-19

## Overview

本合约定义 `utils/runtime_config.py` 模块对外提供的 API 接口，用于管理运行时配置和用户配置。

**⚠️ 重要变更（v1.2）**：
- 新增 `check_stale_backup()` 检测残留 bak 文件
- 新增 `prompt_backup_action()` 提示用户处理残留 bak
- 新增 `cleanup_backup_after_migration()` 迁移后清理 bak 文件

**⚠️ 重要变更（v1.1）**：
- 配置文件拆分为 `config.json`（用户配置）和 `runtime.json`（运行时状态）
- 新增 `UserConfig` 类和相关 API
- 锁文件命名为 `runtime.json.lock`，包含详细注释
- 新增 `remove_session_mapping()` 方法用于会话退出时清理

---

## Module: `utils.runtime_config`

### Functions

#### `load_user_config() -> UserConfig`

加载用户配置文件。

**Returns**:
- `UserConfig`: 用户配置对象

**Behavior**:
- 配置文件不存在时返回默认配置
- 配置文件损坏时备份并返回默认配置

**Example**:
```python
from utils.runtime_config import load_user_config

config = load_user_config()
print(config.ui_settings.quick_commands.enabled)
```

---

#### `save_user_config(config: UserConfig) -> None`

保存用户配置到文件。

**Parameters**:
- `config: UserConfig` - 用户配置对象

---

#### `load_runtime_config() -> RuntimeConfig`

加载运行时配置文件。

**Returns**:
- `RuntimeConfig`: 运行时配置对象

**Behavior**:
- 配置文件不存在时返回默认配置
- 配置文件损坏时备份并返回默认配置
- 备份保留策略：保留最近 2 个备份文件
- 自动执行版本迁移

**Example**:
```python
from utils.runtime_config import load_runtime_config

config = load_runtime_config()
print(config.session_mappings)
```

---

#### `save_runtime_config(config: RuntimeConfig) -> None`

保存运行时配置到文件。

**Parameters**:
- `config: RuntimeConfig` - 运行时配置对象

**Behavior**:
- 使用文件锁（fcntl.flock）保护并发写入
- 锁文件命名为 `runtime.json.lock`，包含详细注释（用途、PID、创建时间）

**Raises**:
- `IOError`: 文件写入失败

**Example**:
```python
from utils.runtime_config import load_runtime_config, save_runtime_config

config = load_runtime_config()
config.session_mappings["myapp"] = "/path/to/myapp"
save_runtime_config(config)
```

---

#### `remove_session_mapping(truncated_name: str) -> None`

删除会话映射（会话退出时调用）。

**Parameters**:
- `truncated_name: str` - 截断后的会话名称

**Behavior**:
- 从 `session_mappings` 中删除对应条目
- 保留 `lark_group_mappings`（便于重新连接）
- 自动保存配置

**Example**:
```python
from utils.runtime_config import remove_session_mapping

# 会话退出时调用
remove_session_mapping("myapp_src_comp")
```

---

#### `migrate_legacy_config() -> None`

迁移旧配置文件到新的 runtime.json。

**Behavior**:
- 检查 `lark_group_mapping.json` 是否存在
- 存在时迁移到 `runtime.json` 的 `lark_group_mappings` 字段
- 迁移后删除旧文件
- 输出日志记录迁移过程

**Example**:
```python
from utils.runtime_config import migrate_legacy_config

# 在 lark_client 启动时调用
migrate_legacy_config()
```

---

#### `check_stale_backup() -> Optional[Path]`

检查配置目录中是否存在残留的 `.bak` 备份文件。

**Returns**:
- `Path`: 第一个找到的 bak 文件路径
- `None`: 无残留 bak 文件

**Example**:
```python
from utils.runtime_config import check_stale_backup

bak_file = check_stale_backup()
if bak_file:
    print(f"检测到残留备份: {bak_file}")
```

---

#### `prompt_backup_action(bak_path: Path) -> str`

提示用户处理残留的 bak 文件（交互式命令行）。

**Parameters**:
- `bak_path: Path` - 残留的 bak 文件路径

**Returns**:
- `str`: `'overwrite'`（从 bak 恢复）或 `'skip'`（删除 bak 继续）

**Behavior**:
- 显示选项菜单
- 等待用户输入 1 或 2
- 返回对应的选择结果

**Example**:
```python
from utils.runtime_config import check_stale_backup, prompt_backup_action

bak_file = check_stale_backup()
if bak_file:
    action = prompt_backup_action(bak_file)
    if action == 'overwrite':
        # 从 bak 恢复配置
        ...
    else:
        # 删除 bak 继续
        ...
```

---

#### `cleanup_backup_after_migration() -> None`

配置迁移成功后清理所有 `.bak` 备份文件。

**Behavior**:
- 扫描配置目录下所有 `*.json.bak*` 文件
- 删除所有找到的 bak 文件
- 输出删除日志

**Example**:
```python
from utils.runtime_config import migrate_legacy_config, cleanup_backup_after_migration

migrate_legacy_config()
cleanup_backup_after_migration()  # 迁移成功后清理
```

---

### Classes

#### `UserConfig`

用户配置数据类（用户可编辑）。

**Fields**:
| 字段 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `version` | `str` | `"1.0"` | 配置版本 |
| `ui_settings` | `UISettings` | `UISettings()` | UI 设置 |

**Storage**: `~/.remote-claude/config.json`

---

#### `RuntimeConfig`

运行时配置数据类（程序自动管理）。

**Fields**:
| 字段 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `version` | `str` | `"1.0"` | 配置版本 |
| `session_mappings` | `Dict[str, str]` | `{}` | 截断名 → 原始路径（会话退出时删除） |
| `lark_group_mappings` | `Dict[str, str]` | `{}` | 群组 ID → 会话名（持久保留） |

**Storage**: `~/.remote-claude/runtime.json`

**Methods**:

##### `get_session_mapping(truncated_name: str) -> Optional[str]`

获取截断名称对应的原始路径。

**Returns**:
- `str`: 原始路径
- `None`: 映射不存在

---

##### `set_session_mapping(truncated_name: str, original_path: str) -> None`

设置会话映射。

**Validation**:
- 映射数量超过 500 时输出警告日志

---

##### `remove_session_mapping(truncated_name: str) -> None`

删除会话映射（会话退出时调用）。

---

#### `UISettings`

UI 设置数据类。

**Methods**:

##### `is_quick_commands_visible() -> bool`

判断快捷命令选择器是否应该显示。

**Returns**:
- `bool`: `enabled=True` 且 `commands` 非空时返回 `True`

---

##### `get_quick_commands() -> List[QuickCommand]`

获取快捷命令列表。

**Returns**:
- `List[QuickCommand]`: 快捷命令列表（已启用时）
- `[]`: 未启用或列表为空

---

## Error Handling

| 错误场景 | 处理方式 |
|---------|---------|
| 用户配置文件不存在 | 返回默认配置 |
| 用户配置文件损坏 | 备份损坏文件，返回默认配置 |
| 运行时配置文件不存在 | 返回默认配置 |
| 运行时配置文件损坏 | 备份损坏文件（保留最近 2 个），返回默认配置 |
| 映射数量超限（>500） | 输出警告日志，允许继续添加（软限制） |
| 文件写入失败 | 抛出 `IOError` |
| JSON 解析失败 | 备份并返回默认配置 |
| 并发写入冲突 | 使用文件锁（fcntl.flock）等待并写入 |
| bak 文件残留 | 启动时提示用户选择覆盖或跳过 |
| 配置目录权限不足 | 使用内存配置继续运行，输出警告日志 |
| 空会话名 | 拒绝操作，提示"会话名不能为空" |
| commands 超过 20 条 | 静默截断，只显示前 20 条 |

---

## File Format

### 用户配置文件

**Location**: `~/.remote-claude/config.json`

**Format**: JSON

**Purpose**: 存储用户可编辑的配置（如 UI 设置）

### 运行时配置文件

**Location**: `~/.remote-claude/runtime.json`

**Format**: JSON

**Purpose**: 存储程序自动管理的状态（如会话映射）

### 锁文件

**Location**: `~/.remote-claude/runtime.json.lock`

**Format**: 纯文本注释

**Content**:
```
# Remote Claude 配置文件锁
# 用途: 防止并发写入导致配置损坏
# 创建进程 PID: <pid>
# 创建时间: <iso8601 timestamp>
# 说明: 此文件在配置写入时自动创建，写入完成后自动删除
#       如果程序异常退出，此文件可能残留，可安全删除
```

---

## Migration Notes

### 配置文件架构

`config.json` 和 `runtime.json` 均为全新配置文件，无需从旧版本迁移：
- `config.json`：存储用户可编辑配置（`ui_settings`）
- `runtime.json`：存储程序自动管理状态（`session_mappings`、`lark_group_mappings`）

### 从 lark_group_mapping.json 迁移

如果用户已有旧的 `lark_group_mapping.json`：
1. 读取旧文件内容
2. 写入 `runtime.json` 的 `lark_group_mappings` 字段
3. 删除旧文件
4. 输出迁移日志
