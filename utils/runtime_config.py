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
import fcntl
import glob
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from server.biz_enum import CliType

logger = logging.getLogger('RuntimeConfig')

# 常量
CURRENT_VERSION = "1.0"
USER_CONFIG_VERSION = "1.0"
MAX_SESSION_MAPPINGS = 500
MAX_BACKUP_FILES = 2  # 保留最近 2 个备份文件


class ConfigType:
    """配置文件类型常量"""
    CONFIG = "config"
    RUNTIME = "runtime"

# NFS 文件系统检测缓存
_nfs_checked = False
_nfs_is_nfs = False
_nfs_warning_shown = False

from utils.session import USER_DATA_DIR, ensure_user_data_dir

RUNTIME_CONFIG_FILE = USER_DATA_DIR / "runtime.json"
USER_CONFIG_FILE = USER_DATA_DIR / "config.json"
RUNTIME_LOCK_FILE = USER_DATA_DIR / "runtime.json.lock"
USER_CONFIG_LOCK_FILE = USER_DATA_DIR / "config.json.lock"
LEGACY_LARK_GROUP_MAPPING_FILE = USER_DATA_DIR / "lark_group_mapping.json"


# ============== NFS 文件系统检测 ==============

def _is_nfs_filesystem() -> bool:
    """检测配置目录是否位于 NFS 或网络文件系统上

    NFS 上 flock 不可靠，可能导致并发写入问题，因此需要检测并警告。

    Returns:
        True 如果是 NFS，False 如果是本地文件系统
    """
    try:
        str_path = str(USER_DATA_DIR)

        # macOS: 使用 mount 命令检查
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["mount"],
                capture_output=True,
                text=True,
                timeout=5
            )
            for line in result.stdout.split("\n"):
                # NFS 挂载行格式: //server/path on /mount/point (nfs, ...)
                if "nfs" in line.lower():
                    parts = line.split()
                    if len(parts) >= 3:
                        mount_point = parts[2]
                        if str_path.startswith(mount_point):
                            return True

        # Linux: 检查 /proc/mounts
        elif platform.system() == "Linux":
            try:
                with open("/proc/mounts", "r") as f:
                    for line in f:
                        # 格式: device mount_point fstype options ...
                        parts = line.split()
                        if len(parts) >= 3:
                            fstype = parts[2].lower()
                            mount_point = parts[1]
                            if "nfs" in fstype and str_path.startswith(mount_point):
                                return True
            except (IOError, FileNotFoundError):
                pass

    except Exception:
        pass

    return False


def _check_filesystem_and_warn() -> None:
    """检查文件系统并在 NFS 上发出一次性警告"""
    global _nfs_checked, _nfs_is_nfs, _nfs_warning_shown

    if _nfs_checked:
        return

    _nfs_is_nfs = _is_nfs_filesystem()
    _nfs_checked = True

    if _nfs_is_nfs and not _nfs_warning_shown:
        logger.warning(
            f"检测到配置目录 {USER_DATA_DIR} 位于 NFS 或网络文件系统上。"
            f"文件锁 (fcntl.flock) 在 NFS 上可能不可靠，可能导致并发写入问题。"
            f"建议将配置目录移至本地文件系统。"
        )
        _nfs_warning_shown = True


# 模块加载时执行检查
_check_filesystem_and_warn()


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
    print("1. 从备份恢复配置")
    print("2. 跳过（删除备份文件继续）")
    choice = input("请选择 [1/2]: ").strip()
    return 'overwrite' if choice == '1' else 'skip'


def cleanup_backup_files(config_type: Optional[str] = None) -> None:
    """清理 `.bak` 备份文件

    用于清理损坏配置文件的备份（由 _backup_corrupted_file 产生）。

    Args:
        config_type: ConfigType.CONFIG, ConfigType.RUNTIME, 或 None（全部）。
            - ConfigType.CONFIG: 仅清理 config.json.bak.*
            - ConfigType.RUNTIME: 仅清理 runtime.json.bak.*
            - None: 清理所有 *.json.bak* 文件
    """
    if config_type is None:
        pattern = "*.json.bak*"
    else:
        pattern = f"{config_type}.json.bak.*"

    for bak_file in USER_DATA_DIR.glob(pattern):
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
            "icon" : self.icon,
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
            "enabled" : self.enabled,
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
class NotifySettings:
    """通知设置"""
    ready_enabled: bool = True      # 就绪通知开关（默认开启）
    urgent_enabled: bool = False    # 加急通知开关（默认关闭）

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "ready_enabled": self.ready_enabled,
            "urgent_enabled": self.urgent_enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NotifySettings":
        """从字典创建"""
        return cls(
            ready_enabled=data.get("ready_enabled", True),
            urgent_enabled=data.get("urgent_enabled", False),
        )


@dataclass
class CustomCommand:
    """自定义 CLI 命令配置"""
    name: str           # 显示名称，如 "Claude"、"Aider"
    cli_type: str       # CLI 类型（必须为 CliType 枚举值之一)
    command: str        # 实际执行的命令，如 "claude"、"aider --message-args"
    description: str = ""  # 可选描述

    def __post_init__(self):
        """验证命令格式"""
        if not self.name:
            raise ValueError("命令名称不能为空")
        if not self.command:
            raise ValueError("命令值不能为空")
        if not self.cli_type:
            raise ValueError("CLI 类型不能为空")
        # 校验 cli_type 为有效枚举值
        try:
            CliType(self.cli_type)
        except ValueError:
            raise ValueError(f"CLI 类型必须是 {list(CliType)} 之一: {self.cli_type}")
        if len(self.name) > 20:
            raise ValueError(f"命令名称最大长度 20 字符: {self.name}")

    def to_dict(self) -> Dict[str, str]:
        """转换为字典"""
        return {
            "name": self.name,
            "cli_type": self.cli_type,
            "command": self.command,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CustomCommand":
        """从字典创建"""
        return cls(
            name=data.get("name", ""),
            cli_type=data.get("cli_type", ""),
            command=data.get("command", ""),
            description=data.get("description", ""),
        )


@dataclass
class CustomCommandsConfig:
    """自定义命令配置"""
    enabled: bool = False
    commands: List[CustomCommand] = field(default_factory=list)

    def get_command(self, name: str) -> Optional[str]:
        """根据名称获取命令"""
        for cmd in self.commands:
            if cmd.name == name:
                return cmd.command
        return None

    def get_default_command(self) -> str:
        """获取默认命令（第一个命令）"""
        if self.commands:
            return self.commands[0].command
        return "claude"

    def is_visible(self) -> bool:
        """判断是否显示自定义命令选择器"""
        return self.enabled and len(self.commands) > 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "enabled": self.enabled,
            "commands": [cmd.to_dict() for cmd in self.commands],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CustomCommandsConfig":
        """从字典创建"""
        commands_data = data.get("commands", [])
        commands = []
        for cmd_data in commands_data:
            try:
                commands.append(CustomCommand.from_dict(cmd_data))
            except ValueError as e:
                logger.warning(f"跳过无效自定义命令: {e}")
        return cls(
            enabled=data.get("enabled", False),
            commands=commands,
        )


@dataclass
class UISettings:
    """UI 设置"""
    quick_commands: QuickCommandsConfig = field(default_factory=lambda: QuickCommandsConfig())
    notify: NotifySettings = field(default_factory=lambda: NotifySettings())
    bypass_enabled: bool = False  # 新会话 bypass 开关（默认关闭）
    custom_commands: CustomCommandsConfig = field(default_factory=lambda: CustomCommandsConfig())

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "quick_commands": self.quick_commands.to_dict(),
            "notify": self.notify.to_dict(),
            "bypass_enabled": self.bypass_enabled,
            "custom_commands": self.custom_commands.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UISettings":
        """从字典创建"""
        qc_data = data.get("quick_commands", {})
        notify_data = data.get("notify", {})
        cc_data = data.get("custom_commands", {})
        return cls(
            quick_commands=QuickCommandsConfig.from_dict(qc_data),
            notify=NotifySettings.from_dict(notify_data),
            bypass_enabled=data.get("bypass_enabled", False),
            custom_commands=CustomCommandsConfig.from_dict(cc_data),
        )


@dataclass
class RuntimeConfig:
    """运行时配置对象（存储于 runtime.json，程序自动管理）

    仅包含运行时状态，不包含用户可编辑配置。
    """
    version: str = CURRENT_VERSION
    uv_path: Optional[str] = None  # uv 可执行文件路径
    session_mappings: Dict[str, str] = field(default_factory=dict)
    lark_group_mappings: Dict[str, str] = field(default_factory=dict)
    ready_notify_count: int = 0  # 全局就绪通知计数器

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

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version"            : self.version,
            "uv_path"            : self.uv_path,
            "session_mappings"   : self.session_mappings,
            "lark_group_mappings": self.lark_group_mappings,
            "ready_notify_count": self.ready_notify_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeConfig":
        """从字典创建"""
        return cls(
            version=data.get("version", CURRENT_VERSION),
            uv_path=data.get("uv_path"),
            session_mappings=data.get("session_mappings", {}),
            lark_group_mappings=data.get("lark_group_mappings", {}),
            ready_notify_count=data.get("ready_notify_count", 0),
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
            "version"    : self.version,
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

def _save_config_with_lock(
        config_obj: Any,
        config_file: Path,
        lock_path: Path,
) -> None:
    """使用文件锁保存配置的通用函数

    使用 fcntl.flock 对锁文件加排他锁，阻塞等待其他进程释放锁。
    锁文件本身不需要内容，flock 仅依赖文件描述符。

    Args:
        config_obj: 配置对象（需要有 to_dict() 方法）
        config_file: 配置文件路径
        lock_path: 锁文件路径
    """
    ensure_user_data_dir()

    try:
        # 使用 'a+' 模式打开锁文件：
        # - 文件不存在时自动创建
        # - 存在时不截断内容
        # - 获取文件描述符用于 flock
        with open(lock_path, 'a+', encoding="utf-8") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                # 在锁保护下写入配置文件
                content = json.dumps(config_obj.to_dict(), indent=2, ensure_ascii=False)
                with open(config_file, 'w', encoding="utf-8") as f:
                    f.write(content)
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
    except PermissionError:
        logger.warning("配置目录权限不足，配置将仅在内存中保留")
        raise


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
    except OSError as e:
        logger.warning(f"读取配置文件失败（系统错误）: {e}")
        return RuntimeConfig()
    except Exception as e:
        logger.warning(f"加载配置失败: {e}")
        return RuntimeConfig()


def save_runtime_config(config: RuntimeConfig) -> None:
    """保存运行时配置到文件

    使用文件锁（fcntl.flock）保护并发写入。
    通过对锁文件加 flock 实现真正的互斥，避免竞态条件。

    Args:
        config: 运行时配置对象

    Raises:
        IOError: 文件写入失败
    """
    _save_config_with_lock(config, RUNTIME_CONFIG_FILE, RUNTIME_LOCK_FILE)
    logger.debug(f"保存配置成功: {RUNTIME_CONFIG_FILE}")


def remove_session_mapping(truncated_name: str) -> None:
    """删除会话映射（会话退出时调用）

    Args:
        truncated_name: 截断后的会话名称
    """
    config = load_runtime_config()
    if config.remove_session_mapping(truncated_name):
        save_runtime_config(config)
        logger.info(f"已删除会话映射: {truncated_name}")


def get_uv_path() -> Optional[str]:
    """从 runtime.json 读取 uv 路径

    Returns:
        uv 路径字符串，不存在则返回 None
    """
    config = load_runtime_config()
    return config.uv_path


def set_uv_path(path: str) -> None:
    """写入 uv 路径到 runtime.json

    Args:
        path: uv 可执行文件的绝对路径
    """
    config = load_runtime_config()
    config.uv_path = path
    save_runtime_config(config)
    logger.info(f"已记录 uv 路径: {path}")


def validate_uv_path(path: str) -> tuple[bool, str]:
    """验证 uv 路径是否有效

    Args:
        path: uv 路径

    Returns:
        (是否有效, 错误信息)
    """
    import os

    if not path:
        return False, "uv 路径为空"

    path_obj = Path(path)
    if not path_obj.exists():
        return False, f"uv 路径不存在: {path}"

    if not path_obj.is_file():
        return False, f"uv 路径不是文件: {path}"

    if not os.access(path, os.X_OK):
        return False, f"uv 文件不可执行: {path}"

    return True, ""


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


# 旧开关文件路径
LEGACY_NOTIFY_COUNT_FILE = USER_DATA_DIR / "ready_notify_count"
LEGACY_NOTIFY_ENABLED_FILE = USER_DATA_DIR / "ready_notify_enabled"
LEGACY_URGENT_ENABLED_FILE = USER_DATA_DIR / "urgent_notify_enabled"
LEGACY_BYPASS_ENABLED_FILE = USER_DATA_DIR / "bypass_enabled"


def migrate_legacy_notify_settings() -> None:
    """迁移旧开关文件到 config.json 和 runtime.json

    处理以下旧文件：
    - ready_notify_count -> runtime.json
    - ready_notify_enabled -> config.json (ui_settings.notify.ready_enabled)
    - urgent_notify_enabled -> config.json (ui_settings.notify.urgent_enabled)
    - bypass_enabled -> config.json (ui_settings.bypass_enabled)

    迁移完成后删除旧文件。
    """
    legacy_files = [
        LEGACY_NOTIFY_COUNT_FILE,
        LEGACY_NOTIFY_ENABLED_FILE,
        LEGACY_URGENT_ENABLED_FILE,
        LEGACY_BYPASS_ENABLED_FILE,
    ]

    # 检查是否有旧文件需要迁移
    if not any(f.exists() for f in legacy_files):
        return

    logger.info("[迁移] 检测到旧开关文件，正在迁移...")

    # 迁移 ready_notify_count 到 runtime.json
    if LEGACY_NOTIFY_COUNT_FILE.exists():
        try:
            count_str = LEGACY_NOTIFY_COUNT_FILE.read_text().strip()
            count = int(count_str)
            runtime_config = load_runtime_config()
            runtime_config.ready_notify_count = count
            save_runtime_config(runtime_config)
            LEGACY_NOTIFY_COUNT_FILE.unlink()
            logger.info(f"[迁移] ready_notify_count -> runtime.json (count={count})")
        except ValueError:
            logger.warning(f"[迁移] ready_notify_count 内容无效: {count_str}")
            LEGACY_NOTIFY_COUNT_FILE.unlink()
        except Exception as e:
            logger.warning(f"[迁移] ready_notify_count 迁移失败: {e}")

    # 迁移开关到 config.json
    user_config = load_user_config()

    if LEGACY_NOTIFY_ENABLED_FILE.exists():
        try:
            val = LEGACY_NOTIFY_ENABLED_FILE.read_text().strip()
            user_config.ui_settings.notify.ready_enabled = (val == "1")
            LEGACY_NOTIFY_ENABLED_FILE.unlink()
            logger.info("[迁移] ready_notify_enabled -> config.json")
        except Exception as e:
            logger.warning(f"[迁移] ready_notify_enabled 迁移失败: {e}")
            LEGACY_NOTIFY_ENABLED_FILE.unlink()

    if LEGACY_URGENT_ENABLED_FILE.exists():
        try:
            val = LEGACY_URGENT_ENABLED_FILE.read_text().strip()
            user_config.ui_settings.notify.urgent_enabled = (val == "1")
            LEGACY_URGENT_ENABLED_FILE.unlink()
            logger.info("[迁移] urgent_notify_enabled -> config.json")
        except Exception as e:
            logger.warning(f"[迁移] urgent_notify_enabled 迁移失败: {e}")
            LEGACY_URGENT_ENABLED_FILE.unlink()

    if LEGACY_BYPASS_ENABLED_FILE.exists():
        try:
            val = LEGACY_BYPASS_ENABLED_FILE.read_text().strip()
            user_config.ui_settings.bypass_enabled = (val == "1")
            LEGACY_BYPASS_ENABLED_FILE.unlink()
            logger.info("[迁移] bypass_enabled -> config.json")
        except Exception as e:
            logger.warning(f"[迁移] bypass_enabled 迁移失败: {e}")
            LEGACY_BYPASS_ENABLED_FILE.unlink()

    save_user_config(user_config)
    logger.info("[迁移] 开关设置迁移完成")


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
    except OSError as e:
        logger.warning(f"读取用户配置文件失败（系统错误）: {e}")
        return UserConfig()
    except Exception as e:
        logger.warning(f"加载用户配置失败: {e}")
        return UserConfig()


def save_user_config(config: UserConfig) -> None:
    """保存用户配置到文件（config.json）

    使用文件锁（fcntl.flock）保护并发写入。
    通过对锁文件加 flock 实现真正的互斥，避免竞态条件。

    Args:
        config: 用户配置对象

    Raises:
        IOError: 文件写入失败
    """
    _save_config_with_lock(config, USER_CONFIG_FILE, USER_CONFIG_LOCK_FILE)
    logger.debug(f"保存用户配置成功: {USER_CONFIG_FILE}")


# ============== 通知设置访问函数 ==============

def get_notify_ready_enabled() -> bool:
    """获取就绪通知开关状态"""
    config = load_user_config()
    return config.ui_settings.notify.ready_enabled


def set_notify_ready_enabled(enabled: bool) -> None:
    """设置就绪通知开关状态"""
    config = load_user_config()
    config.ui_settings.notify.ready_enabled = enabled
    save_user_config(config)
    logger.info(f"就绪通知开关已{'开启' if enabled else '关闭'}")


def get_notify_urgent_enabled() -> bool:
    """获取加急通知开关状态"""
    config = load_user_config()
    return config.ui_settings.notify.urgent_enabled


def set_notify_urgent_enabled(enabled: bool) -> None:
    """设置加急通知开关状态"""
    config = load_user_config()
    config.ui_settings.notify.urgent_enabled = enabled
    save_user_config(config)
    logger.info(f"加急通知开关已{'开启' if enabled else '关闭'}")


def get_bypass_enabled() -> bool:
    """获取新会话 bypass 开关状态"""
    config = load_user_config()
    return config.ui_settings.bypass_enabled


def set_bypass_enabled(enabled: bool) -> None:
    """设置新会话 bypass 开关状态"""
    config = load_user_config()
    config.ui_settings.bypass_enabled = enabled
    save_user_config(config)
    logger.info(f"新会话 bypass 开关已{'开启' if enabled else '关闭'}")


def get_ready_notify_count() -> int:
    """获取就绪通知计数"""
    config = load_runtime_config()
    return config.ready_notify_count


def increment_ready_notify_count() -> int:
    """原子递增就绪通知计数器，返回新值"""
    config = load_runtime_config()
    config.ready_notify_count += 1
    save_runtime_config(config)
    return config.ready_notify_count


# ============== 自定义命令配置访问函数 ==============

def get_custom_commands() -> List[CustomCommand]:
    """获取自定义命令列表"""
    config = load_user_config()
    return config.ui_settings.custom_commands.commands


def get_custom_command(name: str) -> Optional[str]:
    """根据名称获取自定义命令"""
    config = load_user_config()
    return config.ui_settings.custom_commands.get_command(name)


def get_cli_command(cli_type: str) -> str:
    """获取 CLI 命令（优先自定义命令，回退到默认值）

    Args:
        cli_type: CLI 类型名称（如 "claude"、"codex"）

    Returns:
        实际执行的命令字符串
    """
    config = load_user_config()

    # 优先从自定义命令配置获取
    custom_cmd = config.ui_settings.custom_commands.get_command(cli_type)
    if custom_cmd:
        logger.debug(f"使用自定义命令: {cli_type} -> {custom_cmd}")
        return custom_cmd

    # 回退到默认值
    default_commands = {
        "claude": "claude",
        "codex": "codex",
    }
    return default_commands.get(cli_type, cli_type)


def set_custom_commands(commands: List[CustomCommand]) -> None:
    """设置自定义命令列表"""
    config = load_user_config()
    config.ui_settings.custom_commands.commands = commands
    save_user_config(config)
    logger.info(f"已保存 {len(commands)} 个自定义命令")


def is_custom_commands_enabled() -> bool:
    """检查自定义命令功能是否启用"""
    config = load_user_config()
    return config.ui_settings.custom_commands.is_visible()
