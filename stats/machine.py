"""
机器标识模块

持久化 UUID（~/.remote-claude-id），用于 Mixpanel distinct_id 和跨机器去重。
"""

import os
import platform
import uuid
from pathlib import Path


_ID_FILE = Path.home() / ".remote-claude-id"
_machine_id: str | None = None


def get_machine_id() -> str:
    """获取（或生成）机器 UUID，持久化到 ~/.remote-claude-id"""
    global _machine_id
    if _machine_id:
        return _machine_id

    if _ID_FILE.exists():
        try:
            _machine_id = _ID_FILE.read_text().strip()
            if _machine_id:
                return _machine_id
        except Exception:
            pass

    # 首次生成
    _machine_id = str(uuid.uuid4())
    try:
        _ID_FILE.write_text(_machine_id)
    except Exception:
        pass  # 写失败也继续，只是无法持久化

    return _machine_id


def get_machine_info() -> dict:
    """获取机器基础信息（用于 Mixpanel user profile）"""
    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
    }
