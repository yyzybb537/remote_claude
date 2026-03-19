"""
工具函数

- tmux 操作封装
- Socket 路径管理
- 通用工具
"""

import hashlib
import logging
import os
import platform
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List
import uuid


# 常量
SOCKET_DIR = Path("/tmp/remote-claude")
USER_DATA_DIR = Path.home() / ".remote-claude"
TMUX_SESSION_PREFIX = "rc-"

# 预编译正则表达式（避免每次调用 _safe_filename 时重新编译）
_UNDERSCORE_RE = re.compile(r'_+')

# 平台特定的 socket 路径限制
# macOS AF_UNIX sun_path 限制 104 字节
# Linux AF_UNIX sun_path 限制 108 字节
_SYSTEM = platform.system()
if _SYSTEM == "Darwin":
    _MAX_SOCKET_PATH = 104
elif _SYSTEM == "Linux":
    _MAX_SOCKET_PATH = 108
else:
    # 其他平台使用更保守的 macOS 限制
    _MAX_SOCKET_PATH = 104

# Socket 路径格式：/tmp/remote-claude/<name>.sock
# 固定前缀 19 字节 + 文件名 + 后缀 5 字节
_MAX_FILENAME = _MAX_SOCKET_PATH - len(str(SOCKET_DIR)) - 1 - len(".sock")

# 日志器
_session_logger = logging.getLogger('Session')


def get_env_file() -> Path:
    """获取 .env 配置文件路径"""
    return USER_DATA_DIR / ".env"


def get_chat_bindings_file() -> Path:
    """获取飞书聊天绑定持久化文件路径"""
    return USER_DATA_DIR / "lark_chat_bindings.json"


def get_lark_log_file() -> Path:
    """获取飞书客户端日志文件路径"""
    return USER_DATA_DIR / "lark_client.log"


def ensure_user_data_dir():
    """确保用户数据目录存在"""
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _safe_filename(session_name: str) -> str:
    """将会话名转为安全文件名

    优化策略：优先保留目录路径后缀，从右向左保留语义信息

    Args:
        session_name: 原始会话名（可能包含路径分隔符）

    Returns:
        安全的文件名，长度不超过 _MAX_FILENAME
    """
    # 检查空会话名
    if not session_name or not session_name.strip():
        raise ValueError("会话名不能为空")

    # 替换特殊字符
    name = session_name.replace('/', '_').replace('.', '_')

    # 合并连续下划线（如 a__b → a_b）
    name = _UNDERSCORE_RE.sub('_', name)

    # 去除首尾下划线
    name = name.strip('_')

    # 再次检查空（如原名称只有特殊字符）
    if not name:
        raise ValueError(f"会话名 '{session_name}' 无效（只包含特殊字符）")

    if len(name) <= _MAX_FILENAME:
        return name

    # 超长：从右向左保留路径后缀（优先保留目录标识）
    parts = name.split('_')
    result = []
    total_len = 0

    for part in reversed(parts):
        # 计算添加该部分后的长度（包括分隔符）
        new_len = total_len + len(part) + (1 if result else 0)
        if new_len > _MAX_FILENAME:
            break
        result.insert(0, part)
        total_len = new_len

    # 如果单个部分都超长，回退到 MD5 哈希
    if not result:
        hash_val = hashlib.md5(session_name.encode()).hexdigest()
        _session_logger.warning(
            f"会话名称 '{session_name[:50]}...' 超长且无法截断，使用 MD5 哈希: {hash_val}"
        )
        return hash_val[:_MAX_FILENAME]

    truncated = '_'.join(result)
    _session_logger.warning(
        f"会话名称 '{session_name[:50]}...' 被截断为 '{truncated}'"
    )
    return truncated


def resolve_session_name(original_path: str, config: "RuntimeConfig" = None) -> str:
    """解析会话名称，处理截断和冲突

    Args:
        original_path: 原始会话名/路径
        config: 运行时配置对象（可选，用于映射存储）

    Returns:
        最终的会话名（已处理截断和冲突）
    """
    from utils.runtime_config import load_runtime_config, save_runtime_config

    # 生成截断后的名称
    truncated = _safe_filename(original_path)

    # 如果名称未被截断，直接返回
    if truncated == original_path.replace('/', '_').replace('.', '_'):
        return truncated

    # 需要配置对象进行映射检查
    if config is None:
        config = load_runtime_config()

    # 检查映射
    existing = config.get_session_mapping(truncated)
    result_name = truncated
    need_save = False

    if existing:
        if existing == original_path:
            # 同一路径，复用已有会话
            _session_logger.debug(f"复用已有会话映射: {truncated} -> {original_path}")
            return truncated
        else:
            # 不同路径，使用完整 MD5 哈希确保唯一性
            unique_name = hashlib.md5(original_path.encode()).hexdigest()[:_MAX_FILENAME]
            _session_logger.warning(
                f"会话名冲突: '{truncated}' 已映射到 '{existing}'，"
                f"'{original_path}' 使用完整 MD5 哈希 '{unique_name}'"
            )
            config.set_session_mapping(unique_name, original_path)
            result_name = unique_name
            need_save = True
    else:
        # 新映射，记录并保存
        config.set_session_mapping(truncated, original_path)
        need_save = True
        _session_logger.info(f"记录会话映射: {truncated} -> {original_path}")

    if need_save:
        save_runtime_config(config)

    return result_name


def get_socket_path(session_name: str) -> Path:
    """获取会话的 socket 路径"""
    return SOCKET_DIR / f"{_safe_filename(session_name)}.sock"


def get_pid_file(session_name: str) -> Path:
    """获取会话的 PID 文件路径"""
    return SOCKET_DIR / f"{_safe_filename(session_name)}.pid"


def get_mq_path(session_name: str) -> Path:
    """获取会话的共享状态 mmap 文件路径"""
    return SOCKET_DIR / f"{_safe_filename(session_name)}.mq"


def get_env_snapshot_path(session_name: str) -> Path:
    """获取环境变量快照文件路径（cmd_start 写入，_start_pty 读取后删除）"""
    return SOCKET_DIR / f"{_safe_filename(session_name)}_env.json"


def ensure_socket_dir():
    """确保 socket 目录存在"""
    SOCKET_DIR.mkdir(parents=True, exist_ok=True)


def generate_client_id() -> str:
    """生成客户端 ID"""
    return uuid.uuid4().hex[:8]


def get_tmux_session_name(session_name: str) -> str:
    """获取 tmux 会话名称"""
    return f"{TMUX_SESSION_PREFIX}{_safe_filename(session_name)}"


# ============== tmux 操作 ==============

def tmux_session_exists(session_name: str) -> bool:
    """检查 tmux 会话是否存在"""
    tmux_name = get_tmux_session_name(session_name)
    result = subprocess.run(
        ["tmux", "has-session", "-t", tmux_name],
        capture_output=True
    )
    return result.returncode == 0


def tmux_create_session(session_name: str, command: str, detached: bool = True) -> bool:
    """创建 tmux 会话并运行命令"""
    tmux_name = get_tmux_session_name(session_name)
    args = ["tmux", "new-session", "-s", tmux_name]
    if detached:
        args.append("-d")
    args.extend(["-x", "200", "-y", "50"])  # 默认大小

    # 将 stderr 重定向到 startup.log，捕获 Python 启动错误（如 ModuleNotFoundError）
    # startup.log 位于 ~/.remote-claude/startup.log
    startup_log = USER_DATA_DIR / "startup.log"
    startup_log.parent.mkdir(parents=True, exist_ok=True)
    # 直接在命令末尾添加重定向，使用 str(startup_log) 确保路径正确展开
    command_with_stderr = f"{command} 2>> {startup_log}"

    args.append(command_with_stderr)

    import logging as _logging
    _logging.getLogger('Start').info(f"tmux_cmd: {' '.join(args)}")
    result = subprocess.run(args, capture_output=True)
    if result.returncode == 0:
        # 启用鼠标支持，允许在 tmux 窗口内用鼠标滚轮查看历史输出
        subprocess.run(
            ["tmux", "set-option", "-t", tmux_name, "-g", "mouse", "on"],
            capture_output=True
        )
    return result.returncode == 0


def tmux_new_window(session_name: str, window_name: str, command: str) -> bool:
    """在 tmux 会话中创建新窗口"""
    tmux_name = get_tmux_session_name(session_name)
    result = subprocess.run(
        ["tmux", "new-window", "-t", tmux_name, "-n", window_name, command],
        capture_output=True
    )
    return result.returncode == 0


def tmux_attach(session_name: str, window: Optional[str] = None) -> bool:
    """附加到 tmux 会话"""
    tmux_name = get_tmux_session_name(session_name)
    target = tmux_name
    if window:
        target = f"{tmux_name}:{window}"

    result = subprocess.run(["tmux", "attach-session", "-t", target])
    return result.returncode == 0


def tmux_kill_session(session_name: str) -> bool:
    """终止 tmux 会话"""
    tmux_name = get_tmux_session_name(session_name)
    result = subprocess.run(
        ["tmux", "kill-session", "-t", tmux_name],
        capture_output=True
    )
    return result.returncode == 0


def tmux_list_sessions() -> List[str]:
    """列出所有 remote-claude 相关的 tmux 会话"""
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return []

    sessions = []
    for line in result.stdout.strip().split("\n"):
        if line.startswith(TMUX_SESSION_PREFIX):
            sessions.append(line[len(TMUX_SESSION_PREFIX):])
    return sessions


def tmux_send_keys(session_name: str, keys: str, window: Optional[str] = None) -> bool:
    """向 tmux 会话发送按键"""
    tmux_name = get_tmux_session_name(session_name)
    target = tmux_name
    if window:
        target = f"{tmux_name}:{window}"

    result = subprocess.run(
        ["tmux", "send-keys", "-t", target, keys],
        capture_output=True
    )
    return result.returncode == 0


def tmux_select_window(session_name: str, window: str) -> bool:
    """选择 tmux 窗口"""
    tmux_name = get_tmux_session_name(session_name)
    result = subprocess.run(
        ["tmux", "select-window", "-t", f"{tmux_name}:{window}"],
        capture_output=True
    )
    return result.returncode == 0


# ============== 会话管理 ==============

def get_process_cwd(pid: int) -> Optional[str]:
    """获取进程的工作目录（macOS/Linux，通过 lsof）"""
    try:
        result = subprocess.run(
            ["lsof", "-p", str(pid), "-a", "-d", "cwd", "-F", "n"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if line.startswith("n"):
                return line[1:].strip()
    except Exception:
        pass
    return None


def list_active_sessions() -> List[dict]:
    """列出所有活跃会话"""
    ensure_socket_dir()
    sessions = []

    for sock_file in SOCKET_DIR.glob("*.sock"):
        session_name = sock_file.stem
        pid_file = get_pid_file(session_name)

        # 检查 socket 文件是否有效（进程是否存在）
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                # 检查进程是否存在
                os.kill(pid, 0)
                # 获取进程 CWD
                cwd = get_process_cwd(pid)
                # 获取启动时间（PID 文件的修改时间，文件可能已被并发清理）
                import datetime
                try:
                    mtime = pid_file.stat().st_mtime
                    start_time = datetime.datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
                except OSError:
                    mtime = 0
                    start_time = "?"

                # 读取 .mq 文件获取 cli_type（避免循环导入，在函数内导入）
                try:
                    import sys
                    from pathlib import Path
                    import logging
                    project_root = str(Path(__file__).parent.parent)
                    if project_root not in sys.path:
                        sys.path.insert(0, project_root)
                    from server.shared_state import SharedStateReader
                    reader = SharedStateReader(session_name)
                    snapshot = reader.read()
                    cli_type = snapshot.get("cli_type", "claude")
                except Exception as e:
                    # 添加详细日志记录，便于诊断问题
                    import logging
                    logger = logging.getLogger('Session')
                    logger.warning(f"读取共享内存 cli_type 失败: session={session_name}, error={e}")
                    cli_type = "claude"  # 读取失败时使用默认值

                sessions.append({
                    "name": session_name,
                    "socket": str(sock_file),
                    "pid": pid,
                    "cwd": cwd or "",
                    "start_time": start_time,
                    "mtime": mtime,
                    "tmux": tmux_session_exists(session_name),
                    "cli_type": cli_type
                })
            except (ProcessLookupError, ValueError, OSError):
                # 进程不存在或文件被并发清理，清理残留文件
                cleanup_session(session_name)
        else:
            # 没有 PID 文件，清理 socket
            sock_file.unlink(missing_ok=True)

    sessions.sort(key=lambda s: s.get("mtime", 0), reverse=True)
    return sessions


def cleanup_session(session_name: str):
    """清理会话残留文件"""
    sock_path = get_socket_path(session_name)
    pid_file = get_pid_file(session_name)

    sock_path.unlink(missing_ok=True)
    pid_file.unlink(missing_ok=True)
    get_mq_path(session_name).unlink(missing_ok=True)
    get_env_snapshot_path(session_name).unlink(missing_ok=True)


def is_session_active(session_name: str) -> bool:
    """检查会话是否活跃"""
    sock_path = get_socket_path(session_name)
    pid_file = get_pid_file(session_name)

    if not sock_path.exists() or not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError, OSError):
        return False


# ============== 终端工具 ==============

def get_terminal_size() -> tuple:
    """获取终端大小"""
    try:
        size = os.get_terminal_size()
        return (size.lines, size.columns)
    except OSError:
        return (24, 80)  # 默认大小


# ============== 飞书客户端管理 ==============

def get_lark_pid_file() -> Path:
    """获取飞书客户端的 PID 文件路径"""
    return SOCKET_DIR / "lark.pid"


def get_lark_status_file() -> Path:
    """获取飞书客户端的状态文件路径"""
    return SOCKET_DIR / "lark.status"


def is_lark_running() -> bool:
    """检查飞书客户端是否正在运行"""
    pid_file = get_lark_pid_file()

    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError, OSError):
        return False


def get_lark_pid() -> Optional[int]:
    """获取飞书客户端的 PID"""
    pid_file = get_lark_pid_file()

    if not pid_file.exists():
        return None

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, ValueError, OSError):
        return None


def get_lark_status() -> Optional[dict]:
    """获取飞书客户端状态信息

    Returns:
        dict: 包含 pid, start_time, uptime 等信息
        None: 如果客户端未运行
    """
    pid = get_lark_pid()
    if pid is None:
        return None

    status_file = get_lark_status_file()
    import datetime

    # 获取启动时间
    if status_file.exists():
        try:
            import json
            status_data = json.loads(status_file.read_text())
            start_timestamp = status_data.get("start_time")
            start_time_str = datetime.datetime.fromtimestamp(start_timestamp).strftime("%Y-%m-%d %H:%M:%S")

            # 计算运行时间
            uptime_seconds = int(datetime.datetime.now().timestamp() - start_timestamp)
            uptime_str = format_uptime(uptime_seconds)

            return {
                "pid": pid,
                "start_time": start_time_str,
                "uptime": uptime_str,
                "uptime_seconds": uptime_seconds
            }
        except (json.JSONDecodeError, ValueError, OSError):
            pass

    # 如果状态文件不存在或无法读取，使用 PID 文件的修改时间
    pid_file = get_lark_pid_file()
    try:
        mtime = pid_file.stat().st_mtime
        start_time_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        uptime_seconds = int(datetime.datetime.now().timestamp() - mtime)
        uptime_str = format_uptime(uptime_seconds)

        return {
            "pid": pid,
            "start_time": start_time_str,
            "uptime": uptime_str,
            "uptime_seconds": uptime_seconds
        }
    except OSError:
        return {
            "pid": pid,
            "start_time": "未知",
            "uptime": "未知",
            "uptime_seconds": 0
        }


def format_uptime(seconds: int) -> str:
    """格式化运行时间

    Args:
        seconds: 秒数

    Returns:
        str: 格式化后的运行时间，如 "2天3小时5分钟"
    """
    if seconds < 60:
        return f"{seconds}秒"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分钟"

    hours = minutes // 60
    minutes = minutes % 60
    if hours < 24:
        return f"{hours}小时{minutes}分钟"

    days = hours // 24
    hours = hours % 24
    return f"{days}天{hours}小时{minutes}分钟"


def save_lark_status(pid: int):
    """保存飞书客户端状态信息

    Args:
        pid: 进程 PID
    """
    import json
    import datetime

    status_file = get_lark_status_file()
    status_data = {
        "pid": pid,
        "start_time": datetime.datetime.now().timestamp()
    }

    status_file.write_text(json.dumps(status_data))


def cleanup_lark():
    """清理飞书客户端残留文件"""
    pid_file = get_lark_pid_file()
    status_file = get_lark_status_file()

    pid_file.unlink(missing_ok=True)
    status_file.unlink(missing_ok=True)
