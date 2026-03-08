"""
工具函数

- tmux 操作封装
- Socket 路径管理
- 通用工具
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List
import uuid


# 常量
SOCKET_DIR = Path("/tmp/remote-claude")
TMUX_SESSION_PREFIX = "rc-"


def _safe_filename(session_name: str) -> str:
    """将会话名转为安全文件名（/ 和 . 替换为 _）"""
    return session_name.replace('/', '_').replace('.', '_')


def get_socket_path(session_name: str) -> Path:
    """获取会话的 socket 路径"""
    return SOCKET_DIR / f"{_safe_filename(session_name)}.sock"


def get_pid_file(session_name: str) -> Path:
    """获取会话的 PID 文件路径"""
    return SOCKET_DIR / f"{_safe_filename(session_name)}.pid"


def get_mq_path(session_name: str) -> Path:
    """获取会话的共享状态 mmap 文件路径"""
    return SOCKET_DIR / f"{_safe_filename(session_name)}.mq"


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
    args.append(command)

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
                    start_time = datetime.datetime.fromtimestamp(mtime).strftime("%H:%M")
                except OSError:
                    mtime = 0
                    start_time = "?"
                sessions.append({
                    "name": session_name,
                    "socket": str(sock_file),
                    "pid": pid,
                    "cwd": cwd or "",
                    "start_time": start_time,
                    "mtime": mtime,
                    "tmux": tmux_session_exists(session_name)
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
