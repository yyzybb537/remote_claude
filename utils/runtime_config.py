"""
运行时配置管理模块

提供统一的运行时配置存储，支持：
- 会话名称映射（截断名称 <-> 原始路径）
- 飞书群组映射（chat_id -> session_name）
- UI 设置（快捷命令配置等）

配置文件位置: ~/.remote-claude/settings.json, ~/.remote-claude/state.json
"""

import fcntl
import glob
import json
import logging
import os
import platform
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from server.biz_enum import CliType

logger = logging.getLogger('RuntimeConfig')

# 常量
SETTINGS_CURRENT_VERSION = "1.0"
STATE_CURRENT_VERSION = "1.0"
MAX_SESSION_MAPPINGS = 500
MAX_BACKUP_FILES = 2  # 保留最近 2 个备份文件
OPERATION_PANEL_ALLOWED_KEYS = {"up", "down", "ctrl_o", "shift_tab", "esc", "shift_tab_x3"}
OPERATION_PANEL_DEFAULT_KEYS = ["up", "down", "ctrl_o", "shift_tab", "esc"]


class ConfigType:
    """配置文件类型常量"""
    SETTINGS = "settings"
    STATE = "state"


# NFS 文件系统检测缓存
_nfs_checked = False
_nfs_is_nfs = False
_nfs_warning_shown = False

from utils.session import USER_DATA_DIR, ensure_user_data_dir

# 新版文件路径
SETTINGS_FILE = USER_DATA_DIR / "settings.json"
STATE_FILE = USER_DATA_DIR / "state.json"
SETTINGS_LOCK_FILE = USER_DATA_DIR / "settings.json.lock"
STATE_LOCK_FILE = USER_DATA_DIR / "state.json.lock"


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
        if "settings" in filename:
            lock_path = SETTINGS_LOCK_FILE
        elif "state" in filename:
            lock_path = STATE_LOCK_FILE
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
        config_type: ConfigType.SETTINGS, ConfigType.STATE, 或 None（全部）。
            - ConfigType.SETTINGS: 仅清理 settings.json.bak.*
            - ConfigType.STATE: 仅清理 state.json.bak.*
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


# 默认模糊指令列表
DEFAULT_VAGUE_PATTERNS = [
    "继续执行", "继续", "开始执行", "开始", "执行", "continue", "确认", "OK"
]

# 默认模糊指令提示
DEFAULT_VAGUE_PROMPT = (
    "[系统提示] 请使用工具执行下一步操作。"
    "如果不确定下一步，请明确询问需要做什么。"
    "不要只返回状态确认。"
)


@dataclass
class SessionSettings:
    """会话设置"""
    bypass: bool = False
    auto_answer_delay_sec: int = 5
    auto_answer_vague_patterns: List[str] = field(default_factory=lambda: DEFAULT_VAGUE_PATTERNS.copy())
    auto_answer_vague_prompt: str = field(default=DEFAULT_VAGUE_PROMPT)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bypass": self.bypass,
            "auto_answer_delay_sec": self.auto_answer_delay_sec,
            "auto_answer_vague_patterns": self.auto_answer_vague_patterns,
            "auto_answer_vague_prompt": self.auto_answer_vague_prompt,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionSettings":
        return cls(
            bypass=data.get("bypass", False),
            auto_answer_delay_sec=data.get("auto_answer_delay_sec", 5),
            auto_answer_vague_patterns=data.get("auto_answer_vague_patterns", DEFAULT_VAGUE_PATTERNS.copy()),
            auto_answer_vague_prompt=data.get("auto_answer_vague_prompt", DEFAULT_VAGUE_PROMPT),
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
    enabled_keys: List[str] = field(default_factory=lambda: OPERATION_PANEL_DEFAULT_KEYS.copy())

    def __post_init__(self):
        self.enabled_keys = _normalize_enabled_keys(self.enabled_keys)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "show_builtin_keys": self.show_builtin_keys,
            "enabled_keys": self.enabled_keys,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UiSettings":
        return cls(
            show_builtin_keys=data.get("show_builtin_keys", True),
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


def _write_config_atomically(config_obj: Any, config_file: Path) -> None:
    """将配置先写入同目录临时文件，再原子替换目标文件。"""
    content = json.dumps(config_obj.to_dict(), indent=2, ensure_ascii=False)
    config_file.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{config_file.name}.",
        suffix=".tmp",
        dir=str(config_file.parent),
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, config_file)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


# ============== 配置加载/保存函数 ==============

def _update_config_with_lock(
        config_file: Path,
        lock_path: Path,
        load_func: callable,
        config_class: type,
        mutator: callable,
) -> Any:
    """原子更新配置：持锁读取 -> 修改 -> 写回 -> 释放

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
                # 在锁保护下写入配置文件
                _write_config_atomically(config, config_file)
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
    _ensure_filesystem_checked()  # 添加延迟检测调用

    try:
        # 使用 'a+' 模式打开锁文件：
        # - 文件不存在时自动创建
        # - 存在时不截断内容
        # - 获取文件描述符用于 flock
        with open(lock_path, 'a+', encoding="utf-8") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                # 在锁保护下写入配置文件
                _write_config_atomically(config_obj, config_file)
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
    except PermissionError:
        logger.warning("配置目录权限不足，配置将仅在内存中保留")
        raise


# ============== 新版配置加载/保存函数 ==============

def load_settings() -> Settings:
    """加载用户设置"""
    _ensure_filesystem_checked()

    # 加载配置文件
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Settings.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"settings.json 损坏: {e}")
            _backup_corrupted_file(SETTINGS_FILE, SETTINGS_LOCK_FILE)

    # 返回默认配置
    return Settings()


def save_settings(settings: Settings) -> None:
    """保存用户设置"""
    _save_config_with_lock(settings, SETTINGS_FILE, SETTINGS_LOCK_FILE)


def load_state() -> State:
    """加载运行时状态"""
    _ensure_filesystem_checked()

    # 加载状态文件
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return State.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"state.json 损坏: {e}")
            _backup_corrupted_file(STATE_FILE, STATE_LOCK_FILE)

    # 返回默认状态
    return State()


def save_state(state: State) -> None:
    """保存运行时状态"""
    _save_config_with_lock(state, STATE_FILE, STATE_LOCK_FILE)


# ============== 向后兼容辅助函数 ==============


def get_notify_ready_enabled() -> bool:
    """获取就绪通知开关状态"""
    settings = load_settings()
    return settings.notify.ready


def set_notify_ready_enabled(enabled: bool) -> None:
    """设置就绪通知开关状态（原子更新）"""

    def mutator(settings: Settings):
        if settings.notify.ready != enabled:
            settings.notify.ready = enabled
            logger.info(f"就绪通知开关已{'开启' if enabled else '关闭'}")
            return settings
        return None  # 无变化

    _update_config_with_lock(
        SETTINGS_FILE,
        SETTINGS_LOCK_FILE,
        load_settings,
        Settings,
        mutator,
    )


def get_notify_urgent_enabled() -> bool:
    """获取加急通知开关状态"""
    settings = load_settings()
    return settings.notify.urgent


def set_notify_urgent_enabled(enabled: bool) -> None:
    """设置加急通知开关状态（原子更新）"""

    def mutator(settings: Settings):
        if settings.notify.urgent != enabled:
            settings.notify.urgent = enabled
            logger.info(f"加急通知开关已{'开启' if enabled else '关闭'}")
            return settings
        return None  # 无变化

    _update_config_with_lock(
        SETTINGS_FILE,
        SETTINGS_LOCK_FILE,
        load_settings,
        Settings,
        mutator,
    )


def get_bypass_enabled() -> bool:
    """获取 bypass 开关状态"""
    settings = load_settings()
    return settings.session.bypass


def set_bypass_enabled(enabled: bool) -> None:
    """设置 bypass 开关状态（原子更新）"""

    def mutator(settings: Settings):
        if settings.session.bypass != enabled:
            settings.session.bypass = enabled
            logger.info(f"bypass 开关已{'开启' if enabled else '关闭'}")
            return settings
        return None  # 无变化

    _update_config_with_lock(
        SETTINGS_FILE,
        SETTINGS_LOCK_FILE,
        load_settings,
        Settings,
        mutator,
    )


def get_ready_notify_count() -> int:
    """获取就绪通知计数"""
    state = load_state()
    return state.ready_notify_count


def increment_ready_notify_count() -> int:
    """原子递增就绪通知计数器，返回新值"""

    def mutator(state: State):
        state.ready_notify_count += 1
        return state.ready_notify_count

    return _update_config_with_lock(
        STATE_FILE,
        STATE_LOCK_FILE,
        load_state,
        State,
        mutator,
    )


def get_session_auto_answer_enabled(session_name: str) -> bool:
    """获取指定 session 的自动应答开关状态"""
    state = load_state()
    session = state.sessions.get(session_name)
    return session.auto_answer_enabled if session else False


def set_session_auto_answer_enabled(session_name: str, enabled: bool, enabled_by: str = "") -> None:
    """设置指定 session 的自动应答开关状态（原子更新）"""

    def mutator(state: State):
        if session_name not in state.sessions:
            state.sessions[session_name] = SessionState(path="")
        state.sessions[session_name].auto_answer_enabled = enabled
        return None

    _update_config_with_lock(
        STATE_FILE,
        STATE_LOCK_FILE,
        load_state,
        State,
        mutator,
    )


# ============== 模糊指令配置 ==============

def get_vague_commands_config() -> tuple:
    """获取模糊指令配置（从用户配置文件读取）

    Returns:
        tuple: (vague_commands: List[str], vague_command_prompt: str)
    """
    settings = load_settings()
    return settings.session.auto_answer_vague_patterns, settings.session.auto_answer_vague_prompt


def get_auto_answer_delay() -> int:
    """获取自动应答延迟时间（秒）"""
    settings = load_settings()
    return settings.session.auto_answer_delay_sec


def get_card_expiry_enabled() -> bool:
    """卡片过期功能是否启用（始终启用）"""
    return True


def get_card_expiry_seconds() -> int:
    """获取卡片过期时间（秒）"""
    settings = load_settings()
    return settings.card.expiry_sec


def get_launcher_command(launcher_name: str) -> Optional[str]:
    """根据启动器名称获取命令

    从 settings.launchers 中查找匹配名称的启动器，
    返回其 command 字段。

    Args:
        launcher_name: 启动器名称

    Returns:
        命令字符串，未找到则返回 None
    """
    settings = load_settings()
    launcher = settings.get_launcher(launcher_name)
    return launcher.command if launcher else None


def get_launcher_by_name(launcher_name: str) -> Optional[Launcher]:
    """根据启动器名称获取 Launcher 对象

    Args:
        launcher_name: 启动器名称

    Returns:
        Launcher 对象，未找到则返回 None
    """
    settings = load_settings()
    return settings.get_launcher(launcher_name)


def remove_session_mapping(truncated_name: str) -> bool:
    """删除会话映射

    Args:
        truncated_name: 截断后的会话名

    Returns:
        bool: 是否成功删除
    """

    def mutator(state: State):
        return state.remove_session(truncated_name)

    return _update_config_with_lock(
        STATE_FILE,
        STATE_LOCK_FILE,
        load_state,
        State,
        mutator,
    )
