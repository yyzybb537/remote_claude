"""进程管理工具函数"""

import subprocess
from typing import Optional


def terminate_process(proc: Optional[subprocess.Popen], timeout: float = 2.0) -> bool:
    """安全终止子进程

    先发送 SIGTERM，等待指定超时时间，如果进程未退出则发送 SIGKILL。

    Args:
        proc: 子进程对象，可为 None
        timeout: 等待退出的超时时间（秒）

    Returns:
        True 如果进程成功终止，False 如果进程不存在或终止失败
    """
    if proc is None or proc.poll() is not None:
        return True  # 进程已不存在或已退出

    proc.terminate()
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=1.0)
            return True
        except subprocess.TimeoutExpired:
            return False
