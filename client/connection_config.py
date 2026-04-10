"""
远程连接配置管理

提供远程连接配置的持久化存储和管理功能。
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from pathlib import Path
import json
from datetime import datetime

from utils.session import USER_DATA_DIR, ensure_user_data_dir


# 配置文件路径
CONNECTIONS_FILE = USER_DATA_DIR / "remote_connections.json"
CONFIG_VERSION = "1.0"

# 缓存：避免频繁读取文件
_connections_cache: Optional[Dict[str, "SavedConnection"]] = None
_cache_dirty: bool = False


def _invalidate_cache() -> None:
    """清除缓存（写入后调用）"""
    global _connections_cache, _cache_dirty
    _connections_cache = None
    _cache_dirty = False


@dataclass
class SavedConnection:
    """保存的远程连接配置"""
    name: str = ""  # 配置名称
    host: str = ""
    port: int = 8765
    token: str = ""
    session: str = ""  # 默认会话名称
    description: str = ""  # 描述
    created_at: str = ""  # 创建时间
    last_used: str = ""  # 最后使用时间
    is_default: bool = False  # 是否为默认配置

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "token": self.token,
            "session": self.session,
            "description": self.description,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "is_default": self.is_default,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SavedConnection":
        """从字典创建"""
        return cls(
            name=data.get("name", ""),
            host=data.get("host", ""),
            port=data.get("port", 8765),
            token=data.get("token", ""),
            session=data.get("session", ""),
            description=data.get("description", ""),
            created_at=data.get("created_at", ""),
            last_used=data.get("last_used", ""),
            is_default=data.get("is_default", False),
        )


def _load_connections() -> Dict[str, SavedConnection]:
    """加载所有保存的连接配置（带缓存）"""
    global _connections_cache

    if _connections_cache is not None:
        return _connections_cache

    if not CONNECTIONS_FILE.exists():
        _connections_cache = {}
        return _connections_cache

    try:
        data = json.loads(CONNECTIONS_FILE.read_text())
        connections = {}
        for name, conn_data in data.get("connections", {}).items():
            connections[name] = SavedConnection.from_dict(conn_data)
        _connections_cache = connections
        return _connections_cache
    except json.JSONDecodeError as e:
        print(f"警告: 配置文件损坏: {e}")
        _connections_cache = {}
        return _connections_cache
    except Exception as e:
        print(f"警告: 加载配置失败: {e}")
        _connections_cache = {}
        return _connections_cache


def _save_connections(connections: Dict[str, SavedConnection]) -> None:
    """保存所有连接配置"""
    global _connections_cache

    ensure_user_data_dir()

    try:
        data = {
            "version": CONFIG_VERSION,
            "connections": {
                conn.name: conn.to_dict()
                for conn in connections.values()
            }
        }
        CONNECTIONS_FILE.write_text(json.dumps(data, indent=2))
        # 更新缓存
        _connections_cache = connections.copy()
    except Exception as e:
        print(f"警告: 保存配置失败: {e}")


def list_connections() -> List[SavedConnection]:
    """列出所有保存的连接配置"""
    return list(_load_connections().values())


def get_connection(name: str) -> Optional[SavedConnection]:
    """获取保存的连接配置

    Args:
        name: 配置名称

    Returns:
        SavedConnection 对象，不存在返回 None
    """
    connections = _load_connections()
    conn = connections.get(name)
    if conn:
        # 更新最后使用时间
        conn.last_used = datetime.now().isoformat()
        _save_connections(connections)
    return conn


def get_default_connection() -> Optional[SavedConnection]:
    """获取默认连接配置

    Returns:
        默认的 SavedConnection，如果没有默认则返回第一个配置
    """
    connections = _load_connections()

    # 查找标记为默认的配置
    for conn in connections.values():
        if conn.is_default:
            return conn

    # 如果没有标记为默认的，返回第一个配置
    if connections:
        return list(connections.values())[0]

    return None


def save_connection(
    name: str,
    host: str,
    port: int,
    token: str,
    session: str = "",
    description: str = "",
    is_default: bool = False,
) -> SavedConnection:
    """保存新的连接配置

    Args:
        name: 配置名称
        host: 主机地址
        port: 端口
        token: 认证令牌
        session: 会话名称
        description: 描述
        is_default: 是否设为默认

    Returns:
        保存的配置对象
    """
    connections = _load_connections()

    # 如果设置为默认，清除其他默认标记
    if is_default:
        for conn in connections.values():
            conn.is_default = False

    now_str = datetime.now().isoformat()

    conn = SavedConnection(
        name=name,
        host=host,
        port=port,
        token=token,
        session=session,
        description=description,
        created_at=now_str,
        last_used=now_str,
        is_default=is_default,
    )
    connections[name] = conn
    _save_connections(connections)
    return conn


def delete_connection(name: str) -> bool:
    """删除连接配置

    Args:
        name: 配置名称

    Returns:
        True 如果删除成功，False 如果不存在
    """
    connections = _load_connections()
    if name in connections:
        del connections[name]
        _save_connections(connections)
        return True
    return False
