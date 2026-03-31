"""
运行时配置管理模块

提供统一的运行时配置存储，支持：
- 会话名称映射（截断名称 ↔ 原始路径）
- 飞书群组映射（chat_id → session_name）
- UI 设置（快捷命令配置等）

配置文件位置: ~/.remote-claude/runtime.json
"""

import fcntl
import glob
import json
import logging
import os
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
USER_CONFIG_VERSION = "2.0"
MAX_SESSION_MAPPINGS = 500
MAX_BACKUP_FILES = 2  # 保留最近 2 个备份文件
OPERATION_PANEL_ALLOWED_KEYS = {"up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"}
OPERATION_PANEL_DEFAULT_KEYS = ["up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"]


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

def _find_longest_nfs_mount(str_path: str, mounts: list, mount_point_idx: int, fstype_idx: int = None) -> str:
    """从挂载点列表中查找匹配路径的最长 NFS 挂载点

    Args:
        str_path: 要检查的路径
        mounts: 挂载点行列表（每行已 split）
        mount_point_idx: 挂载点在 split 结果中的索引
        fstype_idx: 文件系统类型在 split 结果中的索引（可选，用于精确匹配）

    Returns:
        最长匹配的挂载点，无匹配返回空字符串
    """
    matched_point = ""
    for parts in mounts:
        if len(parts) < 3:
            continue
        mount_point = parts[mount_point_idx]
        # 如果提供了 fstype_idx，检查是否为 NFS
        if fstype_idx is not None:
            fstype = parts[fstype_idx].lower()
            if "nfs" not in fstype:
                continue
        # 匹配最长前缀
        if str_path.startswith(mount_point) and len(mount_point) > len(matched_point):
            matched_point = mount_point
    return matched_point


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
            # NFS 挂载行格式: //server/path on /mount/point (nfs, ...)
            # mount 输出没有固定列，需检查整行是否含 nfs
            mounts = [line.split() for line in result.stdout.split("\n") if "nfs" in line.lower()]
            # macOS mount 输出: device on mount_point (options)
            # parts[2] 是 mount_point
            return bool(_find_longest_nfs_mount(str_path, mounts, mount_point_idx=2))

        # Linux: 检查 /proc/mounts
        elif platform.system() == "Linux":
            try:
                with open("/proc/mounts", "r") as f:
                    # 格式: device mount_point fstype options ...
                    mounts = [line.split() for line in f]
                return bool(_find_longest_nfs_mount(
                    str_path, mounts, mount_point_idx=1, fstype_idx=2
                ))
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


# 延迟检查：首次访问配置文件时才执行 NFS 检测
# 避免模块导入时的阻塞开销
def _ensure_filesystem_checked() -> None:
    """确保文件系统检查已执行（延迟到首次使用）"""
    if not _nfs_checked:
        _check_filesystem_and_warn()


# ============== 备份文件管理 ==============

def _backup_corrupted_file(path: Path, lock_path: Optional[Path] = None) -> Path:
    """备份损坏的配置文件，保留最近 MAX_BACKUP_FILES 个备份

    使用文件锁保护备份操作，避免并发备份导致的数据竞争。

    Args:
        path: 损坏的配置文件路径
        lock_path: 锁文件路径（可选，用于保护备份操作）

    Returns:
        备份文件路径
    """
    # 确定锁文件路径
    if lock_path is None:
        # 根据配置文件类型确定锁文件
        filename = path.name
        if "runtime" in filename:
            lock_path = RUNTIME_LOCK_FILE
        elif "config" in filename:
            lock_path = USER_CONFIG_LOCK_FILE
        else:
            lock_path = Path(str(path) + ".lock")

    # 使用文件锁保护整个备份操作
    try:
        with open(lock_path, 'a+', encoding="utf-8") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                # 检查原文件是否还存在（可能被其他进程处理）
                if not path.exists():
                    logger.warning(f"配置文件已不存在，跳过备份: {path}")
                    return path.with_suffix(".json.bak.missing")

                # 生成带时间戳的备份文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup = path.with_suffix(f".json.bak.{timestamp}")
                path.rename(backup)

                # 清理旧备份，只保留最近 MAX_BACKUP_FILES 个
                backup_pattern = str(path.with_suffix(".json.bak.*"))
                backups = sorted(glob.glob(backup_pattern))
                for old_backup in backups[:-MAX_BACKUP_FILES]:
                    try:
                        Path(old_backup).unlink()
                        logger.info(f"清理旧备份: {old_backup}")
                    except OSError as e:
                        logger.warning(f"清理旧备份失败: {old_backup}, {e}")

                return backup
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
    except OSError as e:
        logger.warning(f"无法获取备份锁，直接备份: {e}")
        # 回退：无锁备份
        if path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = path.with_suffix(f".json.bak.{timestamp}")
            path.rename(backup)
            return backup
        return path.with_suffix(".json.bak.missing")


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
    ready_enabled: bool = True  # 就绪通知开关（默认开启）
    urgent_enabled: bool = False  # 加急通知开关（默认关闭）

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "ready_enabled" : self.ready_enabled,
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
class AutoAnswerSettings:
    """自动应答设置"""
    default_delay_seconds: int = 10
    # 模糊指令配置
    vague_commands: List[str] = field(default_factory=list)
    # 模糊指令增强提示文案
    vague_command_prompt: str = ''

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "default_delay_seconds": self.default_delay_seconds,
            "vague_commands"       : self.vague_commands,
            "vague_command_prompt" : self.vague_command_prompt,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AutoAnswerSettings":
        """从字典创建"""
        default_vague_commands = [
            "继续执行", "继续", "开始执行", "开始", "执行", "continue", "确认", "OK"
        ]
        default_prompt = (
            "[系统提示] 请使用工具执行下一步操作。"
            "如果不确定下一步，请明确询问需要做什么。"
            "不要只返回状态确认。"
        )
        return cls(
            default_delay_seconds=data.get("default_delay_seconds", 10),
            vague_commands=data.get("vague_commands", default_vague_commands),
            vague_command_prompt=data.get("vague_command_prompt", default_prompt),
        )


@dataclass
class CardExpirySettings:
    """卡片过期设置"""
    enabled: bool = True
    expiry_seconds: int = 3600  # 1小时

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "enabled"       : self.enabled,
            "expiry_seconds": self.expiry_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CardExpirySettings":
        """从字典创建"""
        return cls(
            enabled=data.get("enabled", True),
            expiry_seconds=data.get("expiry_seconds", 3600),
        )


@dataclass
class OperationPanelSettings:
    """操作面板设置"""
    show_builtin_keys: bool = True
    show_custom_commands: bool = True
    enabled_keys: List[str] = field(default_factory=lambda: OPERATION_PANEL_DEFAULT_KEYS.copy())

    @classmethod
    def _normalize_enabled_keys(cls, keys: Any) -> List[str]:
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
            logger.warning(f"operation_panel.enabled_keys 包含非法键，已忽略: {invalid}")

        if not filtered:
            return OPERATION_PANEL_DEFAULT_KEYS.copy()
        return filtered

    def __post_init__(self):
        self.enabled_keys = self._normalize_enabled_keys(self.enabled_keys)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "show_builtin_keys"   : self.show_builtin_keys,
            "show_custom_commands": self.show_custom_commands,
            "enabled_keys"        : self.enabled_keys,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OperationPanelSettings":
        """从字典创建"""
        return cls(
            show_builtin_keys=data.get("show_builtin_keys", True),
            show_custom_commands=data.get("show_custom_commands", True),
            enabled_keys=cls._normalize_enabled_keys(data.get("enabled_keys", OPERATION_PANEL_DEFAULT_KEYS)),
        )


@dataclass
class CustomCommand:
    """自定义 CLI 命令配置"""
    name: str  # 显示名称，如 "Claude"、"Aider"
    cli_type: str  # CLI 类型（必须为 CliType 枚举值之一)
    command: str  # 实际执行的命令，如 "claude"、"aider --message-args"
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
            "name"       : self.name,
            "cli_type"   : self.cli_type,
            "command"    : self.command,
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

    def get_command_by_cli_type(self, cli_type: str) -> Optional[str]:
        """根据 CLI 类型获取命令"""
        for cmd in self.commands:
            if cmd.cli_type == cli_type:
                return cmd.command
        return None

    def get_default_command(self) -> str:
        """获取默认命令（第一个命令）"""
        if self.commands:
            return self.commands[0].command
        return str(CliType.CLAUDE)

    def is_visible(self) -> bool:
        """判断是否显示自定义命令选择器"""
        return self.enabled and len(self.commands) > 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "enabled" : self.enabled,
            "commands": [cmd.to_dict() for cmd in self.commands],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CustomCommandsConfig":
        """从字典创建，支持迁移旧配置（无 cli_type 字段）"""
        commands_data = data.get("commands", [])
        commands = []
        for cmd_data in commands_data:
            try:
                # 迁移旧配置：如果没有 cli_type 字段，根据 name 推断
                if not cmd_data.get("cli_type"):
                    name_lower = cmd_data.get("name", "").lower()
                    if "codex" in name_lower:
                        cmd_data = {**cmd_data, "cli_type": str(CliType.CODEX)}
                    else:
                        cmd_data = {**cmd_data, "cli_type": str(CliType.CLAUDE)}
                commands.append(CustomCommand.from_dict(cmd_data))
            except ValueError as e:
                logger.warning(f"跳过无效自定义命令: {e}")
        return cls(
            enabled=data.get("enabled", False),
            commands=commands,
        )


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
    session_auto_answer: Dict[str, dict] = field(default_factory=dict)  # session 自动应答状态

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
            "ready_notify_count" : self.ready_notify_count,
            "session_auto_answer": self.session_auto_answer,
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
            session_auto_answer=data.get("session_auto_answer", {}),
        )


# ============== 用户配置类（config.json）==============

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


# ============== 配置加载/保存函数 ==============

def _update_config_with_lock(
        config_file: Path,
        lock_path: Path,
        load_func: callable,
        config_class: type,
        mutator: callable,
) -> Any:
    """原子更新配置：持锁读取 → 修改 → 写回 → 释放

    用于多进程安全地修改配置文件，避免"读-改-写"竞态条件。

    Args:
        config_file: 配置文件路径
        lock_path: 锁文件路径
        load_func: 加载函数，返回配置对象
        config_class: 配置类（用于 to_dict）
        mutator: 修改函数，接收配置对象，返回修改后的对象或任意值

    Returns:
        mutator 的返回值
    """
    ensure_user_data_dir()
    _ensure_filesystem_checked()

    try:
        with open(lock_path, 'a+', encoding="utf-8") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                # 在锁保护下读取最新配置
                config = load_func()
                # 应用修改
                result = mutator(config)
                # 直接写回文件（不再调用 save_func 避免死锁）
                content = json.dumps(config.to_dict(), indent=2, ensure_ascii=False)
                with open(config_file, 'w', encoding="utf-8") as f:
                    f.write(content)
                return result
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
    except PermissionError:
        logger.warning("配置目录权限不足，配置将仅在内存中保留")
        raise


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
    _ensure_filesystem_checked()  # 巻加延迟检测调用

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

    使用原子更新避免多进程竞态条件。

    Args:
        truncated_name: 截断后的会话名称
    """

    def mutator(config: RuntimeConfig):
        if config.remove_session_mapping(truncated_name):
            logger.info(f"已删除会话映射: {truncated_name}")
        return None

    _update_config_with_lock(
        RUNTIME_CONFIG_FILE,
        RUNTIME_LOCK_FILE,
        load_runtime_config,
        RuntimeConfig,
        mutator,
    )


def get_uv_path() -> Optional[str]:
    """从 runtime.json 读取 uv 路径

    Returns:
        uv 路径字符串，不存在则返回 None
    """
    config = load_runtime_config()
    return config.uv_path


def set_uv_path(path: str) -> None:
    """写入 uv 路径到 runtime.json（原子更新）

    Args:
        path: uv 可执行文件的绝对路径
    """

    def mutator(config: RuntimeConfig):
        config.uv_path = path
        logger.info(f"已记录 uv 路径: {path}")
        return None

    _update_config_with_lock(
        RUNTIME_CONFIG_FILE,
        RUNTIME_LOCK_FILE,
        load_runtime_config,
        RuntimeConfig,
        mutator,
    )


def validate_uv_path(path: str) -> tuple[bool, str]:
    """验证 uv 路径是否有效

    Args:
        path: uv 路径

    Returns:
        (是否有效, 错误信息)
    """
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
    - ready_notify_enabled -> config.json (behavior.notify.ready_enabled)
    - urgent_notify_enabled -> config.json (behavior.notify.urgent_enabled)
    - bypass_enabled -> config.json (session.bypass)

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


def get_ready_notify_count() -> int:
    """获取就绪通知计数"""
    config = load_runtime_config()
    return config.ready_notify_count


def increment_ready_notify_count() -> int:
    """原子递增就绪通知计数器，返回新值"""

    def mutator(config: RuntimeConfig):
        config.ready_notify_count += 1
        return config.ready_notify_count

    return _update_config_with_lock(
        RUNTIME_CONFIG_FILE,
        RUNTIME_LOCK_FILE,
        load_runtime_config,
        RuntimeConfig,
        mutator,
    )


# ============== 自动应答配置访问函数 ==============

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


# ============== 自定义命令配置访问函数 ==============

def get_custom_commands() -> List[CustomCommand]:
    """获取自定义命令列表"""
    config = load_user_config()
    return config.session.custom_commands.commands


def get_custom_command(name: str) -> Optional[str]:
    """根据名称获取自定义命令"""
    config = load_user_config()
    return config.session.custom_commands.get_command(name)


def get_cli_command(cli_type: str) -> str:
    """获取 CLI 命令（优先自定义命令，回退到默认值）

    Args:
        cli_type: CLI 类型名称（如 "claude"、"codex" 或 CliType 枚举）

    Returns:
        实际执行的命令字符串
    """
    # 标准化为字符串（支持枚举和字符串输入）
    cli_type_str = str(cli_type) if isinstance(cli_type, CliType) else cli_type

    config = load_user_config()

    # 优先从自定义命令配置获取（按 cli_type 匹配）
    custom_cmd = config.session.custom_commands.get_command_by_cli_type(cli_type_str)
    if custom_cmd:
        logger.debug(f"使用自定义命令: {cli_type_str} -> {custom_cmd}")
        return custom_cmd

    # 回退到默认值
    default_commands = {
        str(CliType.CLAUDE): str(CliType.CLAUDE),
        str(CliType.CODEX) : str(CliType.CODEX),
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


# ============== Session 自动应答状态管理 ==============

def load_session_auto_answer() -> Dict[str, dict]:
    """加载所有 session 的自动应答状态"""
    config = load_runtime_config()
    return config.session_auto_answer


def save_session_auto_answer(states: Dict[str, dict]) -> None:
    """保存所有 session 的自动应答状态（原子更新）"""

    def mutator(config: RuntimeConfig):
        config.session_auto_answer = states
        return None

    _update_config_with_lock(
        RUNTIME_CONFIG_FILE,
        RUNTIME_LOCK_FILE,
        load_runtime_config,
        RuntimeConfig,
        mutator,
    )


def get_session_auto_answer_enabled(session_name: str) -> bool:
    """获取指定 session 的自动应答开关状态"""
    states = load_session_auto_answer()
    return states.get(session_name, {}).get("enabled", False)


def set_session_auto_answer_enabled(session_name: str, enabled: bool, enabled_by: str = "") -> None:
    """设置指定 session 的自动应答开关状态（原子更新）"""

    def mutator(config: RuntimeConfig):
        if enabled:
            config.session_auto_answer[session_name] = {"enabled": True, "enabled_by": enabled_by}
        else:
            config.session_auto_answer.pop(session_name, None)
        return None

    _update_config_with_lock(
        RUNTIME_CONFIG_FILE,
        RUNTIME_LOCK_FILE,
        load_runtime_config,
        RuntimeConfig,
        mutator,
    )


# ============== 模糊指令配置 ==============

def get_vague_commands_config() -> tuple:
    """获取模糊指令配置（从用户配置文件读取）

    Returns:
        tuple: (vague_commands: List[str], vague_command_prompt: str)
    """
    config = load_user_config()
    auto_answer = config.behavior.auto_answer
    return auto_answer.vague_commands, auto_answer.vague_command_prompt
