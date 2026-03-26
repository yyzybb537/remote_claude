"""
Remote Claude 终端客户端模块

提供本地和远程客户端实现
"""

from client.local_client import LocalClient, run_client
from client.base_client import BaseClient, BaseWSClient, build_ws_url
from client.remote_client import RemoteClient, run_remote_client
from client.connection_config import (
    SavedConnection,
    list_connections,
    get_connection,
    get_default_connection,
    save_connection,
    delete_connection,
)

__all__ = [
    'LocalClient', 'BaseClient', 'BaseWSClient', 'RemoteClient',
    'run_client', 'run_remote_client', 'build_ws_url',
    'SavedConnection', 'list_connections', 'get_connection',
    'get_default_connection', 'save_connection', 'delete_connection',
]
