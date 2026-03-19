"""
运行时配置管理模块

提供统一的运行时配置存储，支持：
- 会话名称映射（截断名称 ↔ 原始路径）
- 飞书群组映射（chat_id → session_name）
- UI 设置（快捷命令配置等）

配置文件位置: ~/.remote-claude/runtime.json
"""

import json
import logging
import hashlib
import fcntl
import os
import glob
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger('RuntimeConfig')

# 常量
CURRENT_VERSION = "1.0"
USER_CONFIG_VERSION = "1.0"
MAX_SESSION_MAPPINGS = 500
MAX_BACKUP_FILES = 2  # 保留最近 2 个备份文件

# 从 utils.session 导入 USER_DATA_DIR，避免重复定义
from utils.session import USER_DATA_DIR, ensure_user_data_dir

RUNTIME_CONFIG_FILE = USER_DATA_DIR / "runtime.json"
USER_CONFIG_FILE = USER_DATA_DIR / "config.json"
RUNTIME_LOCK_FILE = USER_DATA_DIR / "runtime.json.lock"
LEGACY_LARK_GROUP_MAPPING_FILE = USER_DATA_DIR / "lark_group_mapping.json"


# ============== 备份文件管理 ==============

def _backup_corrupted_file(path: Path) -> Path:
    """备份损坏的配置文件，保留最近 MAX_BACKUP_FILES 个备份

    Args:
        path: 损坏的配置文件路径

    Returns:
        备份文件路径
    """
    # 生成带时间戳的备份文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(f".json.bak.{timestamp}")
    path.rename(backup)

    # 清理旧备份，只保留最近 MAX_BACKUP_FILES 个
    backup_pattern = str(path.with_suffix(".json.bak.*"))
    backups = sorted(glob.glob(backup_pattern))
    for old_backup in backups[:-MAX_BACKUP_FILES]:
        Path(old_backup).unlink()
        logger.info(f"清理旧备份: {old_backup}")

    return backup


def check_stale_backup() -> Optional[Path]:
    """检查配置目录中是否存在残留的 `.bak` 备份文件

    Returns:
        Path: 第一个找到的 bak 文件路径
        None: 无残留 bak 文件
    """
    bak_files = list(USER_DATA_DIR.glob("*.json.bak*"))
    return bak_files[0] if bak_files else None


def prompt_backup_action(bak_path: Path) -> str:
    """提示用户处理残留的 bak 文件（交互式命令行）

    Args:
        bak_path: 残留的 bak 文件路径

    Returns:
        str: 'overwrite'（从 bak 恢复）或 'skip'（删除 bak 继续）
    """
    print(f"检测到残留的备份文件: {bak_path}")
    print("1. 覆盖当前配置并重新迁移")
    print("2. 跳过（删除备份文件继续）")
    choice = input("请选择 [1/2]: ").strip()
    return 'overwrite' if choice == '1' else 'skip'


def cleanup_backup_after_migration() -> None:
    """配置迁移成功后清理所有 `.bak` 备份文件"""
    for bak_file in USER_DATA_DIR.glob("*.json.bak*"):
        bak_file.unlink()
        logger.info(f"已删除备份文件: {bak_file}")


# ============== 数据类定义 ==============

@dataclass
class QuickCommand:
    """快捷命令对象"""
    label: str
    value: str
    icon: str = ""

    def __post_init__(self):
        """验证命令格式"""
        if not self.value.startswith('/'):
            raise ValueError(f"命令值必须以 / 开头: {self.value}")
        if ' ' in self.value:
            raise ValueError(f"命令值不能包含空格: {self.value}")
        if len(self.value) > 32:
            raise ValueError(f"命令值最大长度 32 字符: {self.value}")
        if len(self.label) > 20:
            raise ValueError(f"标签最大长度 20 字符: {self.label}")

    def to_dict(self) -> Dict[str, str]:
        """转换为字典"""
        return {
            "label": self.label,
            "value": self.value,
            "icon": self.icon,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuickCommand":
        """从字典创建"""
        return cls(
            label=data.get("label", ""),
            value=data.get("value", ""),
            icon=data.get("icon", ""),
        )


@dataclass
class QuickCommandsConfig:
    """快捷命令配置"""
    enabled: bool = False
    commands: List[QuickCommand] = field(default_factory=list)

    def is_visible(self) -> bool:
        """判断是否显示快捷命令选择器"""
        return self.enabled and len(self.commands) > 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "enabled": self.enabled,
            "commands": [cmd.to_dict() for cmd in self.commands],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuickCommandsConfig":
        """从字典创建"""
        commands_data = data.get("commands", [])
        commands = []
        for cmd_data in commands_data:
            try:
                commands.append(QuickCommand.from_dict(cmd_data))
            except ValueError as e:
                logger.warning(f"跳过无效快捷命令: {e}")
        return cls(
            enabled=data.get("enabled", False),
            commands=commands,
        )


@dataclass
class UISettings:
    """UI 设置"""
    quick_commands: QuickCommandsConfig = field(default_factory=lambda: QuickCommandsConfig())

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "quick_commands": self.quick_commands.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UISettings":
        """从字典创建"""
        qc_data = data.get("quick_commands", {})
        return cls(
            quick_commands=QuickCommandsConfig.from_dict(qc_data),
        )


@dataclass
class RuntimeConfig:
    """运行时配置对象"""
    version: str = CURRENT_VERSION
    session_mappings: Dict[str, str] = field(default_factory=dict)
    lark_group_mappings: Dict[str, str] = field(default_factory=dict)
    ui_settings: UISettings = field(default_factory=lambda: UISettings())

    def get_session_mapping(self, truncated_name: str) -> Optional[str]:
        """获取截断名称对应的原始路径

        Args:
            truncated_name: 截断后的会话名

        Returns:
            原始路径，不存在时返回 None
        """
        return self.session_mappings.get(truncated_name)

    def set_session_mapping(self, truncated_name: str, original_path: str) -> None:
        """设置会话映射

        Args:
            truncated_name: 截断后的会话名
            original_path: 原始完整路径
        """
        # 检查映射数量限制（软限制：允许继续添加，仅输出警告）
        if len(self.session_mappings) >= MAX_SESSION_MAPPINGS and truncated_name not in self.session_mappings:
            logger.warning(
                f"session_mappings 映射数量已达上限 {MAX_SESSION_MAPPINGS}，"
                f"建议手动清理旧映射。新映射仍会保存。"
            )
        self.session_mappings[truncated_name] = original_path

    def remove_session_mapping(self, truncated_name: str) -> bool:
        """删除会话映射（会话退出时调用）

        Args:
            truncated_name: 截断后的会话名

        Returns:
            是否成功删除
        """
        if truncated_name in self.session_mappings:
            del self.session_mappings[truncated_name]
            return True
        return False

    def get_lark_group_mapping(self, chat_id: str) -> Optional[str]:
        """获取飞书群组映射

        Args:
            chat_id: 飞书聊天 ID

        Returns:
            会话名，不存在时返回 None
        """
        return self.lark_group_mappings.get(chat_id)

    def set_lark_group_mapping(self, chat_id: str, session_name: str) -> None:
        """设置飞书群组映射

        Args:
            chat_id: 飞书聊天 ID
            session_name: 会话名
        """
        self.lark_group_mappings[chat_id] = session_name

    def remove_lark_group_mapping(self, chat_id: str) -> bool:
        """移除飞书群组映射

        Args:
            chat_id: 飞书聊天 ID

        Returns:
            是否成功移除
        """
        if chat_id in self.lark_group_mappings:
            del self.lark_group_mappings[chat_id]
            return True
        return False

    def is_quick_commands_visible(self) -> bool:
        """判断快捷命令选择器是否应该显示

        Returns:
            enabled=True 且 commands 非空时返回 True
        """
        return self.ui_settings.quick_commands.is_visible()

    def get_quick_commands(self) -> List[QuickCommand]:
        """获取快捷命令列表

        Returns:
            快捷命令列表（已启用时），未启用或列表为空时返回空列表
        """
        if self.ui_settings.quick_commands.enabled:
            return self.ui_settings.quick_commands.commands
        return []

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version": self.version,
            "session_mappings": self.session_mappings,
            "lark_group_mappings": self.lark_group_mappings,
            "ui_settings": self.ui_settings.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeConfig":
        """从字典创建"""
        ui_data = data.get("ui_settings", {})
        return cls(
            version=data.get("version", CURRENT_VERSION),
            session_mappings=data.get("session_mappings", {}),
            lark_group_mappings=data.get("lark_group_mappings", {}),
            ui_settings=UISettings.from_dict(ui_data),
        )


# ============== 用户配置类（config.json）==============

@dataclass
class UserConfig:
    """用户配置对象（存储于 config.json，用户可编辑）

    包含用户可自定义的 UI 设置等配置项。
    """
    version: str = USER_CONFIG_VERSION
    ui_settings: UISettings = field(default_factory=lambda: UISettings())

    def is_quick_commands_visible(self) -> bool:
        """判断快捷命令选择器是否应该显示"""
        return self.ui_settings.quick_commands.is_visible()

    def get_quick_commands(self) -> List[QuickCommand]:
        """获取快捷命令列表"""
        if self.ui_settings.quick_commands.enabled:
            return self.ui_settings.quick_commands.commands
        return []

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version": self.version,
            "ui_settings": self.ui_settings.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserConfig":
        """从字典创建"""
        ui_data = data.get("ui_settings", {})
        return cls(
            version=data.get("version", USER_CONFIG_VERSION),
            ui_settings=UISettings.from_dict(ui_data),
        )


# ============== 配置加载/保存函数 ==============

def load_runtime_config() -> RuntimeConfig:
    """加载运行时配置文件

    Returns:
        RuntimeConfig: 运行时配置对象
    """
    if not RUNTIME_CONFIG_FILE.exists():
        return RuntimeConfig()

    try:
        data = json.loads(RUNTIME_CONFIG_FILE.read_text(encoding="utf-8"))
        config = RuntimeConfig.from_dict(data)
        logger.debug(f"加载配置成功: {RUNTIME_CONFIG_FILE}")
        return config
    except json.JSONDecodeError as e:
        # 备份损坏文件
        backup = _backup_corrupted_file(RUNTIME_CONFIG_FILE)
        logger.warning(f"配置文件损坏，已备份到 {backup}: {e}")
        return RuntimeConfig()
    except Exception as e:
        logger.warning(f"加载配置失败: {e}")
        return RuntimeConfig()


def save_runtime_config(config: RuntimeConfig) -> None:
    """保存运行时配置到文件

    使用文件锁（fcntl.flock）保护并发写入。
    锁文件命名为 runtime.json.lock，包含详细注释。

    Args:
        config: 运行时配置对象

    Raises:
        IOError: 文件写入失败
    """
    ensure_user_data_dir()
    lock_path = USER_DATA_DIR / "runtime.json.lock"

    # 创建锁文件（带注释）
    lock_content = f"""# Remote Claude 配置文件锁
# 用途: 防止并发写入导致配置损坏
# 创建进程 PID: {os.getpid()}
# 创建时间: {datetime.now().isoformat()}
# 说明: 此文件在配置写入时自动创建，写入完成后自动删除
#       如果程序异常退出，此文件可能残留，可安全删除
"""
    lock_path.write_text(lock_content, encoding="utf-8")

    try:
        content = json.dumps(config.to_dict(), indent=2, ensure_ascii=False)
        with open(RUNTIME_CONFIG_FILE, 'w', encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(content)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        logger.debug(f"保存配置成功: {RUNTIME_CONFIG_FILE}")
    except PermissionError:
        logger.warning("配置目录权限不足，配置将仅在内存中保留")
        raise
    finally:
        # 删除锁文件
        if lock_path.exists():
            lock_path.unlink()


def remove_session_mapping(truncated_name: str) -> None:
    """删除会话映射（会话退出时调用）

    Args:
        truncated_name: 截断后的会话名称
    """
    config = load_runtime_config()
    if config.remove_session_mapping(truncated_name):
        save_runtime_config(config)
        logger.info(f"已删除会话映射: {truncated_name}")


def migrate_legacy_config() -> None:
    """迁移旧配置文件到新的 runtime.json

    - 检查 lark_group_mapping.json 是否存在
    - 存在时迁移到 runtime.json 的 lark_group_mappings 字段
    - 迁移后删除旧文件
    - 输出日志记录迁移过程
    """
    if not LEGACY_LARK_GROUP_MAPPING_FILE.exists():
        return

    try:
        # 读取旧文件
        legacy_data = json.loads(LEGACY_LARK_GROUP_MAPPING_FILE.read_text(encoding="utf-8"))
        if not legacy_data:
            # 空文件，直接删除
            LEGACY_LARK_GROUP_MAPPING_FILE.unlink()
            logger.info("[迁移] lark_group_mapping.json 为空，已删除")
            return

        # 加载或创建 runtime.json
        config = load_runtime_config()

        # 检查冲突
        if config.lark_group_mappings:
            # 已存在映射，以 runtime.json 为准
            logger.warning(
                "[迁移] runtime.json 已存在 lark_group_mappings，"
                "跳过迁移，删除旧文件"
            )
            LEGACY_LARK_GROUP_MAPPING_FILE.unlink()
            return

        # 执行迁移
        config.lark_group_mappings = legacy_data
        save_runtime_config(config)
        LEGACY_LARK_GROUP_MAPPING_FILE.unlink()
        logger.info(
            f"[迁移] 已将 lark_group_mapping.json 迁移到 runtime.json "
            f"({len(legacy_data)} 条映射)"
        )
    except json.JSONDecodeError as e:
        logger.warning(f"[迁移] 旧配置文件损坏，跳过: {e}")
        # 备份并删除损坏文件
        _backup_corrupted_file(LEGACY_LARK_GROUP_MAPPING_FILE)
    except Exception as e:
        logger.error(f"[迁移] 迁移失败: {e}")


# ============== 用户配置加载/保存函数 ==============

def load_user_config() -> UserConfig:
    """加载用户配置文件（config.json）

    Returns:
        UserConfig: 用户配置对象
    """
    if not USER_CONFIG_FILE.exists():
        return UserConfig()

    try:
        data = json.loads(USER_CONFIG_FILE.read_text(encoding="utf-8"))
        config = UserConfig.from_dict(data)
        logger.debug(f"加载用户配置成功: {USER_CONFIG_FILE}")
        return config
    except json.JSONDecodeError as e:
        # 备份损坏文件
        backup = _backup_corrupted_file(USER_CONFIG_FILE)
        logger.warning(f"用户配置文件损坏，已备份到 {backup}: {e}")
        return UserConfig()
    except Exception as e:
        logger.warning(f"加载用户配置失败: {e}")
        return UserConfig()


def save_user_config(config: UserConfig) -> None:
    """保存用户配置到文件（config.json）

    Args:
        config: 用户配置对象

    Raises:
        IOError: 文件写入失败
    """
    ensure_user_data_dir()

    try:
        content = json.dumps(config.to_dict(), indent=2, ensure_ascii=False)
        USER_CONFIG_FILE.write_text(content, encoding="utf-8")
        logger.debug(f"保存用户配置成功: {USER_CONFIG_FILE}")
    except PermissionError:
        logger.warning("配置目录权限不足，用户配置将仅在内存中保留")
        raise


def migrate_runtime_to_user_config() -> None:
    """迁移 runtime.json 中的 ui_settings 到 config.json

    - 检查 runtime.json 是否包含 ui_settings
    - 提取 ui_settings 到 config.json
    - 从 runtime.json 中移除 ui_settings 字段
    - 迁移完成后删除 bak 文件
    """
    if not RUNTIME_CONFIG_FILE.exists():
        return

    try:
        data = json.loads(RUNTIME_CONFIG_FILE.read_text(encoding="utf-8"))

        # 检查是否有 ui_settings 需要迁移
        if "ui_settings" not in data:
            return

        ui_settings = data["ui_settings"]
        if not ui_settings:
            return

        # 加载或创建 config.json
        user_config = load_user_config()

        # 检查是否已有配置
        if user_config.ui_settings.quick_commands.enabled or user_config.ui_settings.quick_commands.commands:
            # config.json 已有配置，跳过迁移
            logger.info("[迁移] config.json 已有 ui_settings，跳过从 runtime.json 迁移")
            return

        # 迁移 ui_settings
        user_config.ui_settings = UISettings.from_dict(ui_settings)
        save_user_config(user_config)

        # 从 runtime.json 中移除 ui_settings
        del data["ui_settings"]
        RUNTIME_CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info("[迁移] 已将 runtime.json 中的 ui_settings 迁移到 config.json")

    except json.JSONDecodeError as e:
        logger.warning(f"[迁移] runtime.json 格式错误，跳过迁移: {e}")
    except Exception as e:
        logger.error(f"[迁移] 迁移 ui_settings 失败: {e}")
